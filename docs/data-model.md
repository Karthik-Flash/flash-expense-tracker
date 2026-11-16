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

## Owner tables (migration `0004`)

What the owner tells the app. Written only by owner commands (`owner-load`
now; the terminal review and the app later). Import, reparse and recompute
read them and never write them. They hold the owner's own words and
transaction ids, never merchant keys (D-065). Everything in them is private:
never printed, never in git, fixtures or logs. RLS is enabled with no
policies, as on every table.

| Table | Key columns | Constraints |
| ----- | ----------- | ----------- |
| `own_accounts` | `label`, `kind` (bank_account, credit_card, wallet, fd), `bank`, `source` | UNIQUE (`owner_id`, `label`) |
| `own_identifiers` | `own_account_id`, `kind` (last4, text), `value`, `source` | UNIQUE (`owner_id`, `kind`, `value`, `own_account_id`) |
| `parties` | `label`, `kind` (person, business), `income_label` (null: not an income source), `source` | UNIQUE (`owner_id`, `label`) |
| `party_texts` | `party_id`, `text`, `source` | UNIQUE (`owner_id`, `text`) |
| `owner_link_decisions` | `kind` (duplicate, self_transfer, card_bill, refund, fd), `txn_a`, `txn_b`, `verdict` (same, different), `decided_at`, `source` | UNIQUE (`owner_id`, `kind`, `txn_a`, `txn_b`); CHECK `txn_a < txn_b` |
| `owner_roles` | `transaction_id` (primary key), `role` (every role except duplicate), `decided_at`, `source` | |

`source` says who wrote a row: `file`, `terminal` or `app` (D-070). The
checked values repeat the engine's vocabulary; a test keeps the two in step,
because a change needs a migration.

## Owner file (`python -m app.cli owner-load <file> [--dry-run]`)

One JSON file that the owner keeps outside the repo, in
`D:\FlashPrivate\private\`. Agents never read it. Example with fake values:
[owner.example.json](owner.example.json).

| Key | Meaning |
| --- | ------- |
| `accounts[].label` | The owner's name for the account. Required, at most 80 characters, unique among accounts (case does not matter) |
| `accounts[].kind` | `bank_account`, `credit_card`, `wallet` or `fd` |
| `accounts[].bank` | The bank code the app uses (`HDFC`, `SBI`, `ICICI`, `AXIS`, `KOTAK`, `YES`, `INDIA_POST`, `PHONEPE`). Needed when `last4` is given |
| `accounts[].last4` | The account's last 4 digits and the last 4 of every debit card on it; for a credit card, the card's last 4. Strings of 4 digits |
| `accounts[].texts` | How the account shows up as a counterparty in an SMS: the owner's name, a UPI ID, a biller name. Copy it as the SMS shows it; case, spacing and punctuation do not matter |
| `parties[].label` | The owner's name for a person or business. Required, unique among parties |
| `parties[].kind` | `person` or `business` |
| `parties[].income` | Only for an income source: its name, for example "Pocket money" |
| `parties[].texts` | How the party shows up as a counterparty: names and UPI IDs. At least one |

- **Strict.** An unknown key, a wrong type, a bad kind or bank, a label used
  twice, a last 4 listed twice at one bank, an entry with nothing to match
  on, and one text claimed in two places (compared the way the engine
  matches, so `Test Owner` and `TEST-OWNER` are the same text) are all
  errors. Every problem is reported, each by its field path
  (`parties[2].texts[0]: same text as accounts[1].texts[0]`), never by its
  value. With any error nothing is loaded.
- **One database transaction.** The file's rows are made equal to the file:
  entries are matched by label, so an unchanged entry keeps its id; new ones
  are added, changed ones updated, missing ones removed. Loading the same
  file twice changes nothing.
- **Only file rows.** Rows whose `source` is not `file`, and every decision,
  are never changed or removed. The file may not claim a label or text that
  such a row holds.
- **Output**: counts per table (added, updated, removed, unchanged), the
  number of income sources, and the field paths of texts that match no
  transaction (a likely typo). `--dry-run` checks and counts, saves nothing.
- Decisions are not part of the file yet (D-070).

## Derived tables (migration `0005`)

What the engine works out. Written only by `recompute`; the owner tables are
only read. Deleting every row and running `recompute` gives the same rows
back. RLS is enabled with no policies.

| Table | Key columns | Constraints |
| ----- | ----------- | ----------- |
| `txn_derived` | `transaction_id` (primary key); merchant: `merchant_key`, `merchant_kind`, `merchant_confidence`, `display_name`, `brand_id`, `merchant_reasons` (JSON); owner match: `party_id`, `own_account_id` (ON DELETE SET NULL); role: `role`, `role_rule`, `role_basis` (engine, owner), `role_reasons` (JSON), `duplicate_of` | CHECK (`role` = 'duplicate') = (`duplicate_of` IS NOT NULL) |
| `txn_links` | `kind`, `txn_a`, `txn_b`, `status` (linked, candidate), `rule`, `reason`, `decided_by` (engine, owner) | UNIQUE (`kind`, `txn_a`, `txn_b`); CHECK `txn_a < txn_b` |
| `derive_runs` | `started_at`, `finished_at`, `status`, `trigger` (import, reparse, owner, manual), `versions` (JSON), `counts` (JSON, counts only) | |

- One `txn_derived` row per active transaction. The merchant is the engine's;
  when the transaction's text belongs to an owner party, the party's kind and
  label are stored as `merchant_kind` and `display_name`. The key stays the
  engine's.
- A link is identified by its kind and its two transactions. Its `id`
  changes when the link changes.
- `derive_runs` gets a row only when a run wrote something, so the derived
  tables always match the last row and the engine versions on it.

## Recompute (`python -m app.cli recompute [--dry-run] [--accept-key-changes]`)

Reads the active transactions, the owner tables and the recorded
`duplicate_candidates` pairs, calls the pure `derive()`, and writes only the
rows that differ, in one database transaction (`app/pipeline/recompute.py`).

- A run with nothing to change writes nothing. A changed row is replaced
  (delete, then insert), rows go 1000 to a statement, so a run is eleven
  reads and about five writes whatever the size.
- It runs as the last step of `import-sms`, `reparse` and `owner-load` (not
  on a dry run), and by hand. If it fails after an import, the import stays
  saved, the derived tables stay as they were, the command exits with an
  error, and `recompute` is run again once the cause is fixed.
- **Key-change check.** When the stored rows were made by another merchant
  engine version and a transaction would lose or change its party or own
  account, it stops, writes nothing and exits with code 3. Check the owner
  file, then run it with `--accept-key-changes`.
- Owner data that cannot hold (one text in two places, a decision that does
  not fit) stops it with the engine's message; nothing is written.
- Output is counts only. Any other error prints only the error's type.
- `reconcile-stats` shows the "stored run": the last run, its versions and
  the number of stored rows that differ from a fresh derive (0 right after a
  recompute).

## Invariants I10 to I21

| | Invariant | Test |
| -- | --------- | ---- |
| I10 | One `txn_derived` row and one role per active transaction; none for a superseded one | `test_storage.py::test_i10_*` |
| I11 | Recompute twice: the second run writes nothing | `test_i11_*` |
| I12 | Derived data is a pure function: emptied and recomputed, the rows are the same | `test_i12_*` |
| I13 | Import, reparse and recompute never change an owner table | `test_i13_*` |
| I14 | The owner always wins | `test_i14_*` |
| I15 | A duplicate group counts once | `test_i15_*` (storage and engine) |
| I16 | Totals from stored roles equal the sums over roles of a fresh derive | `test_i16_*` (storage and engine) |
| I17 | A candidate changes no role and no total | `test_reconcile_links.py::test_i17_*` |
| I18 | Roles respect direction | `test_reconcile.py::test_i18_*` |
| I19 | Links are sound | `test_reconcile_links.py::test_i15_i19_*` |
| I20 | Owner decisions survive reparse | `test_i20_*` |
| I21 | Commands print counts, ids and versions only, also on errors | `test_i21_*`, `test_owner_load.py` |

RLS on every app table and no policy anywhere: `tests/test_migration.py`
(Postgres job). Migrations are tested up and down, empty and with data.

## Review, export, totals (owner only)

- `reconcile-review [--list]`: terminal only. Decisions are written with
  source `terminal` (the owner tables have no `review` source; the review is
  the terminal). A link decision replaces an earlier one on the same pair.
- `owner-export <file>`: one JSON file, format `flash-owner-export-1`, every
  owner row. Decisions carry `a`, `b` (ids) and `a_key`, `b_key` (dedupe
  keys); a role decision carries `transaction` and `dedupe_key`. Ids and
  creation times of accounts and parties are not kept; labels are.
- `owner-load <export>`: restores only into empty owner tables, every row
  with its source. Each decision is attached by dedupe key; "mapped to another
  id" counts those whose id changed. A key that is not in the database stops
  the restore: import the messages first.
- `totals --month YYYY-MM`: terminal only, reads `txn_derived` joined to
  `transactions`, refuses when no recompute has run, the versions differ, or
  stored rows differ from a fresh derive.

## Categories and labels (migration `0006`)

Additive. RLS on the three new tables.

| Table or column | What | Constraints |
| --------------- | ---- | ----------- |
| `parties.category` | The owner's default category for the party (slug, null: none) | |
| `owner_categories` | `transaction_id` (primary key), `category`, `decided_at`, `source`: the owner's decision on one transaction | |
| `labels` | `name`, `source`: a label the owner made (D-056) | UNIQUE (`owner_id`, `name`) |
| `txn_labels` | `transaction_id` (primary key), `label_id`, `source` | one label per transaction |
| `txn_derived.category`, `.category_rule`, `.category_basis` | The engine's result, never blank (defaults `uncategorised`, `NONE`, `engine`) | index on `category` |

- A category is a slug; no CHECK, so a new category needs no migration.
- `owner-load`: a party may state `"category"`. One the file does not state
  is left as it is. `owner-export` and the restore cover `categories` and
  `labels`, by dedupe key.
- `recompute` writes the three derived columns and records
  `"categorise"` in `derive_runs.versions`.

| | Invariant | Test |
| -- | --------- | ---- |
| I22 | Exactly one category per active transaction, always from the list | `test_category_storage.py::test_i22_*` |
| I23 | The breakdown adds up to Spent for any range | `test_i23_*` (storage and engine) |
| I24 | Transaction decision beats party default beats engine | `test_i24_*` |
| I25 | Recompute twice changes nothing | `test_i25_*` |
| I26 | Corrections survive reparse | `test_i26_*` |
| I27 | A transaction imported after a merchant correction gets that category | `test_i27_*` |

## Login and the API (D-078)

No migration. Settings: `SUPABASE_URL`, `AUTH_USERS` (`"<sub>:<owner_id>"`,
comma-separated). API writes are owner rows with source `app`
(`app/pipeline/owner_actions.py`), committed in one transaction with their
recompute. `recompute()` takes `owner_lock()`: a per-owner lock in the
process, and `pg_advisory_xact_lock` on Postgres. Routes: `docs/api.md`.
