# Plan

Summary of phases 0 to 6. Draft from Phase 0; the planner owns this file and
refines each phase before it starts. Each phase ends with CI green and a
NOTES.md entry.

## Phase 0: Scaffold and walking skeleton (done)

Monorepo, Python 3.12 venv, FastAPI `/health`, Vite React PWA that shows
backend status and survives cold starts, CI (ruff, pytest, typecheck, build),
Render Blueprint, hosting guide, `scripts/redact_sms.py` (default-deny).

Done in the Phase 0 closeout:

- `/health/db` keep-alive: `X-Ping-Token` header, upserts the `heartbeat` row
  with the database clock (migration `0001`), pinged daily by cron-job.org.

## Phase 1: Data model and idempotent ingestion

- Schema: `raw_messages` (sender, body, received_at UTC, dedupe_key UNIQUE),
  `transactions` (amount_paise, direction, account_last4, merchant_raw,
  occurred_at UTC, parser_version, raw_message_id), `accounts`.
- Alembic migration for this schema (after `0001` heartbeat).
- `POST /ingest/sms` batch endpoint. Re-sending the same batch is a no-op.

## Phase 2: SMS parsing engine

- Per-bank rule parsers built from `data/sample/redacted_sample.json`.
- Golden-file tests: one fixture per message shape.
- Amount to paise, debit/credit, account last 4, merchant text, balance.
- Parser registry with versions. Re-parse stored raw messages when a version
  changes.

## Phase 3: Normalization and categorization

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
