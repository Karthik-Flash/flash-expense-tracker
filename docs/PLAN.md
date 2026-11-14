# Plan

Summary of phases 0 to 6. Draft from Phase 0; the planner owns this file and
refines each phase before it starts. Each phase ends with CI green and a
NOTES.md entry.

**Status (14 Nov 2026):** Phases 0, 1 and 2 done. **Next: Phase 3:
Normalization and categorization.**

Prompt labels differ from this file's order: the parsing prompts were called
"Phase 1" and the import prompt "Phase 2". Both are done; this file keeps its
own numbering. What shipped: [CHANGELOG.md](../CHANGELOG.md).

## Phase 0: Scaffold and walking skeleton (done 13 Nov 2026)

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

- [ ] Overnight cron check: first night on the new schedule is 15 Nov 2026
- [x] Redaction run on the real backup; sample reviewed (14 Nov 2026)

## Phase 1: Data model and idempotent ingestion (done 14 Nov 2026)

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

## Phase 2: SMS parsing engine (done 14 Nov 2026)

As built: HDFC parser `hdfc-1.1.1` ([engine.md](engine.md), D-041 to D-045),
fake-fixture tests, per-bank versions and `python -m app.cli reparse`. Other
banks are stored with `no_parser_for_bank` and need only a parser plus
reparse. Draft scope as planned:

- Per-bank rule parsers built from `data/sample/redacted_sample.json`.
- Golden-file tests: one fixture per message shape.
- Amount to paise, debit/credit, account last 4, merchant text, balance.
- Parser registry with versions. Re-parse stored raw messages when a version
  changes.

## Phase 3: Normalization and categorization (next)

- Merchant canonicalization (token cleanup plus fuzzy matching).
- Rule-based categories with user overrides that become rules.
- Self-transfer detection between own accounts, so money is not counted twice.

## Phase 4: Insights engine

- Recurring payment and subscription detection.
- Monthly budgets, unusual-spend detection, cash-flow summaries.
- All day and month buckets in IST.

## Phase 5: Frontend

- Transaction list with search and filters, correction UI, dashboards.
- Manual entry. Offline-first PWA with sync.

## Phase 6: Android shell and hardening

- Capacitor Android app that reads SMS on device and sends them to ingestion.
- Auth, data export and backup, error monitoring, production deploy review.
