# Plan

Summary of phases 0 to 6. Draft from Phase 0; the planner owns this file and
refines each phase before it starts. Each phase ends with CI green and a
NOTES.md entry.

**Status (15 Nov 2026):** Phases 0, 1 and 2 done. **Next: Phase 3:
Normalise, reconcile, categorise and minimal dashboard.**

Phase numbers in this file match the git tags and CHANGELOG.md.

## Phase 0: Scaffold and walking skeleton (done 13 Nov 2026)

Done: tag `phase-0-done` (CHANGELOG Phase 0).

Monorepo, Python 3.12 venv, FastAPI `/health`, Vite React PWA that shows
backend status and survives cold starts, CI (ruff, pytest, typecheck, build),
Render Blueprint, hosting guide, `scripts/redact_sms.py` (default-deny).

Done in the Phase 0 closeout:

- `/health/db` keep-alive: `X-Ping-Token` header, upserts the `heartbeat` row
  with the database clock (migration `0001`), pinged daily by cron-job.org.

Deploy (13 Nov 2026), all done and verified:

- [x] Supabase Postgres (Singapore, Session pooler, Data API off), `0001` applied
- [x] Render API https://flash-expense-tracker.onrender.com (`/health` 200,
      `/health/db` 200 with header, 401 without)
- [x] Vercel app https://flash-expense-tracker.vercel.app ("Backend online")
- [x] `CORS_ORIGINS` set for localhost and the Vercel URL
- [x] cron-job.org wake-up (03:27, 03:28 IST) and DB heartbeat (03:30 IST);
      replaced on 14 Nov by one heartbeat job, 03:30 to 03:38 IST (D-052)

Last open Phase 0 items:

- [ ] Overnight check of the D-053 keep-alive: first scheduled run 16 Nov 2026
      03:30 IST; confirm job history 200 and `last_seen` moved
- [x] Redaction run on the real backup; sample reviewed (14 Nov 2026)

## Phase 1: SMS parsing engine (done 14 Nov 2026)

Done: tag `phase-1-done` (CHANGELOG Phase 1).

As built: HDFC parser `hdfc-1.1.1` ([engine.md](engine.md), D-041 to D-045),
fake-fixture tests, per-bank versions and `python -m app.cli reparse`. Other
banks are stored with `no_parser_for_bank` and need only a parser plus
reparse. Draft scope as planned:

- Per-bank rule parsers built from `data/sample/redacted_sample.json`.
- Golden-file tests: one fixture per message shape.
- Amount to paise, debit/credit, account last 4, merchant text, balance.
- Parser registry with versions. Re-parse stored raw messages when a version
  changes.

## Phase 2: Data model and idempotent ingestion (done 14 Nov 2026)

Done: tag `phase-2-done` (CHANGELOG Phase 2).

As built: migration `0002` with `import_batches`, `raw_messages`,
`parse_results`, `transactions`, `transaction_sources`,
`duplicate_candidates` ([data-model.md](data-model.md), D-046 to D-050). A
CLI importer (`python -m app.cli import-sms`) replaced the batch endpoint for
now; no `accounts` table yet. Real import: 917 messages, 678 transactions.
Draft scope as planned:

- Schema: `raw_messages` (sender, body, received_at UTC, dedupe_key UNIQUE),
  `transactions` (amount_paise, direction, account_last4, merchant_raw,
  occurred_at UTC, parser_version, raw_message_id), `accounts`.
- Alembic migration for this schema (after `0001` heartbeat).
- `POST /ingest/sms` batch endpoint. Re-sending the same batch is a no-op.

## Phase 3: Normalise, reconcile, categorise and minimal dashboard (next)

Goal: the owner logs in on their phone and sees their real spending,
correctly counted and categorised, on a minimal dashboard. Scope and order:
D-054. What counts as spend: D-055.

Steps, in this order. Each ends with tests green, a counts-only check on real
data run by the owner, and a tag (`phase-3a-done` ... `phase-3f-done`).

- 3A Groundwork: docs alignment; a one-page UI design spec and a clickable
  dashboard mockup with fake numbers, both approved by the owner before any
  screen is built.
- 3B Merchant normalisation: raw counterparty -> merchant, marked person,
  business or unsure. Pure engine. The built-in dictionary holds only
  well-known public brands. The owner's own merchants and people are learned
  from corrections and live only in the database.
- 3C Reconcile: a "my accounts / my UPI IDs" list; self-transfers (D-029);
  card bill payments (D-030); refund linking (D-031); AutoPay + card spend
  (D-032, D-047); the open duplicate candidates. It links and flags, never
  deletes, and is safe to re-run. Unclear duplicates are reviewed by the
  owner in the terminal.
- 3D Categorise: rules -> merchant dictionary -> owner corrections.
  Corrections always win and survive reparse. Owner labels (D-056): create a
  label and attach it to a transaction; stored like corrections.
- 3E Auth and read-only API: Supabase Auth, single user, sign-ups off; JWT
  verified in FastAPI; no data endpoint without auth. The Data API stays
  keepalive-only (D-053).
- 3F Minimal dashboard: month net spend (with spent and paid back), category
  breakdown, transaction list with category correction, label view (D-056),
  and a count of unknown and not-yet-counted items.

Done when: the owner privately checks one normal month and one messy month
against the bank statement and reports "match" or the difference in rupees;
nothing is double-counted; a corrected category stays corrected.

Known limits: HDFC and INR only. Foreign-currency (D-035) and other-bank
messages are not in totals and appear as a "not counted yet" count. A month
is a calendar month in IST, computed from a from/to date range so salary
cycles can replace it later. The server can take about a minute to wake
until Phase 4.

## Phase 4: Full deploy and installable offline-first PWA

No detail yet.

## Phase 5: Android shell and live SMS

No detail yet.

## Phase 6: Statements, Gmail, insights, differentiators

Budget cycles, P2P tagging, roommate splits, subscription tracker,
first-salary mode. No detail yet.

Revisit D-026 (investment, broker and exchange senders): decide whether to
include them.
