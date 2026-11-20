# Plan

Summary of phases 0 to 6. Draft from Phase 0; the planner owns this file and
refines each phase before it starts. Each phase ends with CI green and a
NOTES.md entry.

**Status (20 Nov 2026):** Phases 0 to 3 done. **Phase 4 in progress**: 4C,
4B-1, 4B-2, 4B-3, 4E, 4F-A and 4F-B done; next the owner checks that queued
taps sync and runs the counts, then Phase 5, then the pilot. 4A, 4G and 4D
run during the pilot.

Phase numbers in this file match the git tags and [CHANGELOG.md](../CHANGELOG.md).

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

- [x] Overnight check of the D-053 keep-alive: first scheduled run 16 Nov 2026
      03:30 IST returned 200
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

## Phase 3: Normalise, reconcile, categorise and minimal dashboard (done 18 Nov 2026)

Goal: the owner logs in on their phone and sees their real spending,
correctly counted and categorised, on a minimal dashboard. Scope and order:
D-054. What counts as spend: D-055.

Steps, in this order. Each ends with tests green and a counts-only check on
real data run by the owner. The plan named a tag per step (`phase-3a-done`
... `phase-3f-done`); the tags actually made are `phase-3b-done` and
`phase-3-done`. No tags are made after the fact.

- [x] 3A Groundwork: docs alignment; a one-page UI design spec and a clickable
  dashboard mockup with fake numbers, both approved by the owner before any
  screen is built. The spec and mockup may be approved any time before 3E;
  engine steps do not wait for them.
- [x] 3B Merchant normalisation: raw counterparty -> merchant, marked person,
  business or unsure. Pure engine. The built-in dictionary holds only
  well-known public brands. The owner's own merchants and people are learned
  from corrections and live only in the database. Merchant storage is built
  in 3C-6.
- [x] 3C Reconcile and the derived-data backbone (design:
  docs/design/phase-3-backbone.md): owner data (own accounts and UPI IDs,
  parties, income sources, duplicate decisions) loaded from a private file;
  one role for every transaction; duplicates including AutoPay + card spend;
  self-transfers; card bill payments; refund linking; FD moves; paybacks and
  income; storage and one recompute command; terminal review; owner export.
  Built as steps 3C-2 to 3C-8. It links and flags, never deletes, and is
  safe to re-run.
- [x] 3D Categorise: rules -> merchant dictionary -> owner corrections.
  Corrections always win and survive reparse. Owner labels (D-056): create a
  label and attach it to a transaction; stored like corrections.
  Built 16 Nov 2026 (`categorise-1.0.0`, migration `0006`, D-073, D-074):
  fixed list of 20, party defaults, per-transaction decisions, labels
  (tables and a pure label view), `category-stats`, `category-review`.
- [x] 3E Auth and API: Supabase Auth, single user, sign-ups off; JWT verified in
  FastAPI; no data endpoint without auth. The Data API stays keepalive-only
  (D-053). Also: no feature needs the owner file (D-075); own accounts
  inferred from the messages (D-077); only confirmed paybacks lower Net and
  senders are confirmed in the app (D-076); category and label corrections
  through the API. Built 16 Nov 2026 (`docs/api.md`, D-078).
- [x] 3F Minimal dashboard: month net spend (with spent and paid back), category
  breakdown, transaction list with category correction, label view (D-056),
  and a count of unknown and not-yet-counted items. Built 17 Nov 2026 in
  3F-1 to 3F-3 (`docs/ui-spec.md`, D-079 to D-084): real login and data,
  category colours and a ring chart, the FLA$H logo, `scripts/backup_db.ps1`.

Done when (closed 18 Nov 2026):

- [x] Login and saving on the phone: verified by the owner.
- [x] Reparse and recompute keep owner corrections: verified.
- [x] Backup with `scripts/backup_db.ps1`: verified.
- [ ] OPEN, carried to Phase 4 as its first item: the owner privately checks
  one normal month and one messy month against the bank statement and
  reports "match" or the difference in rupees; nothing is double-counted.

Known limits: HDFC and INR only. Foreign-currency (D-035) and other-bank
messages are not in totals and appear as a "not counted yet" count. A month
is a calendar month in IST, computed from a from/to date range so salary
cycles can replace it later. The server can take about a minute to wake
until Phase 4.

## Phase 4: Installable offline-first PWA, owner fixes, second bank

Order (set 20 Nov 2026): 4C, 4B, 4E, then 4F (second bank), then Phase 5
(the pilot-ready Android app), then the pilot. 4A, 4G and 4D run during the
pilot. 4A (carried from Phase 3) must finish before 4D; before 4A the
planner reminds the owner to download two months of
statements (October and one messy month) as Excel or delimited text, not
PDF, into `D:\FlashPrivate`.

- [x] 4C Install and update prompt (19 Nov 2026): manifest and icons, the
  update bar instead of silent updates, app-shell-only service worker, the
  build id on Home (D-085 to D-087).
- [ ] 4B Offline-first: a copy of the data on the phone, refreshed in the
  background, with "Updated X ago"; taps made offline are queued as
  "Waiting to sync", and totals do not change until the server confirms;
  the copy is wiped on sign-out; timings measured on the phone. Targets:
  usable in 2 s from the phone copy, fresh data in 5 s when the server is
  awake, and a cold server never blocks the screen.
  4B-1 (19 Nov 2026, D-088 to D-090): the snapshot, the phone copy, the
  freshness line and the Speed sheet. 4B-2 (19 Nov 2026, D-091 to D-094):
  every owner action through the outbox, shown as "Waiting to sync".
  4B-3 (20 Nov 2026, D-095): offline boot, never a blank screen.
- [x] 4E Owner fixes (20 Nov 2026, D-096 to D-098): name a person and join
  one person seen under a name and a UPI ID ("Same as…", Separate, history
  kept), "See payments" and category chips on To-do, one label limit of 30,
  HEAD /health, sign-out clears the boot record. Three logo options in
  `docs/design/logo-options.html`; the owner picks, then the wordmark and
  every app icon are updated (a short follow-up).
- [ ] 4F Second bank: a counts-only survey of the 153 other-bank messages;
  pick the bank with the most money messages; vocabulary survey, parser,
  sender-registry entry, reparse.
  4F-A (20 Nov 2026, D-099 to D-103): CI fix (Postgres error class), the
  first read after a deploy recomputes, `payback-audit` (silent paybacks,
  dry run first), `bank-survey`, `redact-sample` with a leak scan and
  `--approve`, the generic parser `generic-1.0.0` for registered banks
  without a parser (check flag, debits count, credits never lower Net),
  `generic-preview`, To-do "Check these payments", "Not a payment" on every
  transaction, logo C2 everywhere.
  Next (proposed): the owner runs payback-audit, bank-survey and
  generic-preview and pastes the counts; then 4F-B, a dedicated parser for
  the owner's main other bank if the counts show the generic parser misses
  much of it (for example SBI amounts without "Rs"); then Phase 5.
  4F-B (21 Nov 2026, D-104 to D-108): the phone's writes were blocked by
  CORS (fixed; a cross-origin check joins the test routine); the outbox
  cannot get stuck; writes commit before the recompute; "Saved on phone"
  wording with a reason after 2 minutes; payback-audit honours explicit
  answers; SBI parser `sbi-1.0.0` (53 of 110 sample messages read, was 24).
  Next (proposed): the owner updates, checks that the 22:42 tap syncs, runs
  the counts; then Phase 5.
- [ ] 4G Cash wallet, after 4F and before 4D: ATM withdrawals keep counting
  as Spent under "Cash"; logging a cash expense moves that amount into its
  category, so Spent never drops because a log is missing; the wallet shows
  cash in hand (withdrawn minus logged); logging works offline through the
  outbox. Designed with the planner first.
- [ ] 4A Statement check: a PRIVATE CLI that reads a NetBanking statement
  file from `D:\FlashPrivate` and prints only count and rupee differences
  per IST month, with likely causes. The owner runs it on one normal and one
  messy month.
- [ ] 4D Multi-month analysis.

## Phase 5: Pilot-ready Android app (8-day target)

- Multi-user: invites, per-user data, delete account.
- Capacitor Android shell.
- Kotlin SMS reading, history and live, uploaded through the outbox.
- Onboarding, privacy policy, pilot invites.
- Pilot fixes.

Then the pilot; 4A, 4G and 4D run during it.

Ops note: the cron-job.org warm job needs a non-browser User-Agent (a
waking Render answers browser-like requests with an HTML page); the
fallback is `HEAD /health` (200, no body, no database, D-098).

## Phase 6: Statements, Gmail, insights, differentiators

Budget cycles, P2P tagging, roommate splits, subscriptions, first-salary mode, and D-026 (investment senders); no detail yet.
