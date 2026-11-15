# Data model and import pipeline

Phase 2 stores every bank SMS once, keeps every parse of it, and turns money
messages into transactions without guessing. Code: `backend/app/models.py`,
migration `backend/alembic/versions/0002_import_pipeline_tables.py`,
`backend/app/pipeline/`, `backend/app/importers/sms_backup.py`,
`backend/app/cli.py`. Decisions: D-046 to D-050.

```
SMS Backup XML --importer--> raw_messages --engine--> parse_results --money?--> transactions
   (filters: registry senders,     (1 per SMS)          (1 per SMS and         (1 per event)
    no OTP / promotional / MMS)                          parser version)            |
                                                         transaction_sources <------+
                                                         duplicate_candidates (pairs, open)
```

## Conventions

- Money is `BIGINT` paise (Python `int`), never floats. `transactions.amount_paise > 0`.
- Every time is `timestamptz` in UTC. The ORM column type rejects naive
  datetimes and always returns UTC (SQLite, used in tests, has no time zone
  type, so UTC is attached on read). IST is for display and month buckets only.
- `owner_id` (UUID) on `import_batches`, `raw_messages`, `transactions`. From
  setting `OWNER_ID`, default `00000000-0000-0000-0000-000000000001` until auth.
- Postgres: row level security is **enabled with no policies** on every new
  table and on `heartbeat` (`0003`). The app connects as the table owner. The
  Data API exposes only the `keepalive` schema (D-053), so RLS is defence in
  depth, not the access control.

## Tables

| Table | Key columns | Constraints |
| ----- | ----------- | ----------- |
| `import_batches` | `source`, `started_at`, `finished_at`, `status` (running, done, failed), `input_fingerprint` (sha256 of the input bytes, never the file name), `app_version`, `parser_versions` (JSON), `counts` (JSON) | |
| `raw_messages` | `source` (sms_backup, manual, statement, live_sms, gmail), `sender_raw`, `sender_core`, `body`, `received_at`, `content_hash`, `first_batch_id` | UNIQUE (`owner_id`, `content_hash`) |
| `parse_results` | `raw_message_id`, `parser_version`, `status` (parsed, unknown), `unknown_reason`, `unknown_detail`, `is_current`, every `ParsedMessage` field (`hints` as JSON) | UNIQUE (`raw_message_id`, `parser_version`); one `is_current` row per message (partial unique index) |
| `transactions` | `dedupe_key`, `type`, `direction`, `amount_paise`, `currency`, `account_last4`, `channel`, `counterparty_raw`, `reference`, `balance_paise`, `txn_time_utc`, `time_inferred`, `bank`, `hints`, `status` (active, superseded) | UNIQUE (`owner_id`, `dedupe_key`); `amount_paise > 0` |
| `transaction_sources` | `transaction_id`, `raw_message_id`, `parse_result_id` | UNIQUE (`raw_message_id`) |
| `duplicate_candidates` | `txn_a` < `txn_b`, `rule`, `status` (open, confirmed, dismissed) | UNIQUE (`txn_a`, `txn_b`) |

Indexes: `transactions.txn_time_utc`, `transactions.status`, a candidate
lookup on (`owner_id`, `bank`, `direction`, `amount_paise`),
`parse_results.is_current`, `.unknown_reason`, `.type`,
`raw_messages.sender_core`, `import_batches.status`,
`duplicate_candidates.status`.

**What lives where.** Non-money results (mandate, upcoming_debit,
other_info including `H_INFO` notices and MF orders) live in
`parse_results` only, queryable by `type` for later features (forecasts,
subscriptions). Unknown results are the **unknown queue**: current rows with
`status = 'unknown'`, by `unknown_reason`. Messages from a known bank without
a parser yet get `no_parser_for_bank` with `parser_version = 'none'`.
`unknown_detail` can contain values from the message; it is stored, never
printed.

## Dedupe rules (`app/pipeline/dedupe.py`, D-046)

1. **Raw level.** `content_hash = sha256(sender_core, body, received_at in
   epoch ms)`. The source is excluded, so the same SMS arriving later by live
   SMS (Phase 5) is still a duplicate. `VM-HDFCBK` and `AD-HDFCBK-S` share
   the core `HDFCBK`. Re-importing a message is a no-op.
2. **Transaction level**, money results only:
   - with a per-payment reference: `sha256("ref", bank, direction,
     amount_paise, reference)`. The account is excluded so email and
     statements can merge with SMS later;
   - without one: `sha256("raw", content_hash)`. No fuzzy merging.
   - A reference that identifies a **mandate** (engine hint
     `mandate_reference`: HDFC H08 SI Hub ID, H13 Mandate ID) repeats on
     every monthly charge, so those results use the raw key. Otherwise two
     same-amount subscription charges would become one transaction.
   - Zero amounts create no transaction (counted as `zero_amount`).
3. **Fuzzy candidates**, recorded and never merged: same owner, bank,
   `account_last4`, direction and amount within 10 minutes gives one
   `duplicate_candidates` row (rule `same_amount_10min`), unless both
   carry a reference: equal references are one mandate, different ones are
   two payments (D-069). Typical case: an AutoPay success SMS and the card
   "Spent" SMS for the same charge (D-047).
4. Different directions never merge or match: a self-transfer is a debit and
   a credit for Reconcile to pair.

## Import (`python -m app.cli import-sms`)

Streams the XML (file or every `*.xml` in a folder) with `iterparse`,
clearing finished elements. Per SMS:

1. Skip, counted by reason: `mms`, `invalid` (no body or date),
   `unregistered_sender` (core not in `SENDER_BANKS`), `promotional`
   (TRAI suffix P), `otp` (`app/engine/filters.py`, same rule and shared test
   table as `scripts/redact_sms.py`). Skipped messages are never stored.
2. Raw insert, or count a duplicate and stop.
3. Parse, insert the current `parse_results` row.
4. Money result: find the transaction by dedupe key (merge) or create it, and
   link it in `transaction_sources`.
5. New transaction: record duplicate candidates.

Ids can skip: on Postgres a dry run uses sequence values and rolls back,
and sequences never give values back. On the real import the dry run took
batch id 1, so the first saved batch is 2. Harmless; nothing depends on
ids being dense.

Commits every 500 messages. All steps for one message share a transaction,
so a crash loses only uncommitted messages; a re-run skips the committed
ones as duplicates and finishes the rest. The batch row records versions,
fingerprint, counts and status (`failed` if it raised). `--dry-run` does
everything inside one transaction and rolls it back.

## Reparse (`python -m app.cli reparse`)

Parser versions are per bank (`hdfc-1.1.1`; `none` without a parser). For
each raw message whose current result is behind its bank's version:

1. Parse again, insert a new `parse_results` row (or reuse the row for that
   version if one exists), move `is_current` to it.
2. Transaction:
   - no link yet and now money: merge or create, as on import;
   - linked, same key or a key no other transaction has: update the
     transaction **in place** (its id stays stable for the same event);
   - linked, the key belongs to another transaction: move the source there
     and mark the old one `superseded` once it has no sources left;
   - linked but no longer money: remove the link, supersede the orphan.

Nothing is deleted from `raw_messages` or `parse_results`. A second run finds
nothing stale and changes nothing.

## Invariants (each has a test)

| | Invariant | Test |
| -- | --------- | ---- |
| I1 | Same file imported twice: 0 new raw messages, 0 new transactions | `test_i1_*` |
| I2 | Overlapping backups sharing messages: no duplicates | `test_i2_*` |
| I3 | Every transaction traces to ≥ 1 raw message and the parse result (with `parser_version`) that produced it | `test_i3_*` |
| I4 | Reparse after a version bump: idempotent, transaction ids stable, nothing deleted | `test_i4_*` (3 tests) |
| I5 | Non-money results never create transactions; Unknown results form the queryable queue | `test_i5_*` |
| I6 | OTP, promotional and unregistered senders are never stored | `test_i6_*` |
| I7 | Money is integer paise; stored times are UTC and round-trip exactly | `test_i7_*` |
| I8 | Crash midway then re-run equals one clean run | `test_i8_*` |
| I9 | Logs and CLI output contain no bodies, amounts, references or account digits | `tests/test_cli.py` |

Tests run on SQLite locally and on a Postgres 17 service container in CI
(`TEST_DATABASE_URL`), which also runs `alembic upgrade head` and
`alembic check`.

## What Reconcile adds (Phase 3)

Design: [design/phase-3-backbone.md](design/phase-3-backbone.md) (D-059 to
D-067). Reconcile reads the active `transactions` and the owner's data. It
gives every transaction one role, finds duplicate pairs itself (an AutoPay
success SMS plus the card spend among them), pairs self-transfers and card
bill payments (hint `card_bill_payment`), and links refunds to their
purchases. It links and flags; nothing is merged or deleted (D-062).
`duplicate_candidates` is frozen: import still records into it, and its
`status` is never written. Closing mandates on cancellation (hint
`mandate_cancelled`) is deferred to Phase 6 (D-067). Phase 2 only records;
it never merges on a guess.
