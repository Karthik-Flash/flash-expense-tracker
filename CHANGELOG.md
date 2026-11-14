# Changelog

What shipped in each phase. Decision numbers refer to
[docs/DECISIONS.md](docs/DECISIONS.md). Phases follow the prompt labels:
Phase 1 is parsing, Phase 2 is the database and import (in
[docs/PLAN.md](docs/PLAN.md) these are its Phases 2 and 1).

## Phase 2: database, SMS import, dedupe (14 Nov 2026, tag `phase-2-done`)

- Migration `0002`: `import_batches`, `raw_messages`, `parse_results`,
  `transactions`, `transaction_sources`, `duplicate_candidates`. BIGINT paise,
  timestamptz UTC, row level security enabled on Postgres
  ([docs/data-model.md](docs/data-model.md)).
- Dedupe: raw `content_hash` without the source; transaction keys on a
  per-payment reference (account excluded) or the raw message; mandate IDs
  never merge monthly charges (`mandate_reference`, `hdfc-1.1.1`) (D-046).
- Fuzzy duplicate candidates recorded, never merged; merging moves to
  Reconcile (D-047).
- Importer for SMS Backup & Restore XML: registry senders only, never OTP,
  promotional or MMS; OTP rule shared with the redaction script (D-049).
  Batched commits, crash-safe re-runs, dry run.
- Reparse to the current parser version per bank, ids stable, nothing
  deleted.
- CLI `python -m app.cli import-sms | reparse | stats`, counts only.
- Tests: invariants I1-I9; a CI job on Postgres 17 runs migrations,
  `alembic check` and the backend tests.
- Real data lives in Supabase; AI tools never connect to it (D-048). Render
  deploys only after CI passes (D-050).
- Real import: 917 messages stored, 678 transactions, 18 duplicate
  candidates; re-import added nothing.
- Lock-in: the full redacted export stays in the private folder (D-051); one
  cron heartbeat job with retries replaces the wake-up job (D-052).

## Phase 1: redaction and the HDFC parser (14 Nov 2026, tag `phase-1-done`)

- Redaction hardening: sender ID normalisation and a 14-core allowlist
  (D-025, D-026, D-038), bank wording never redacted and link paths faked
  (D-039), always-redact list and `--verify` leak check (D-040), mandate IDs
  and payee names redacted (D-045).
- HDFC template survey on the redacted sample: 15 shapes, fake fixtures only
  (D-027, [docs/templates/hdfc.md](docs/templates/hdfc.md)). Parsing
  questions resolved (D-028 to D-037), including foreign currency deferred
  (D-035).
- Stdlib-only parser engine `backend/app/engine/` (D-041, D-043): literal
  whole-body templates, exactly one may match, strict fields, versioned per
  bank (D-042). `hdfc-1.0.0`, then `hdfc-1.1.0` with H16-H21 and the
  amount-free notice fallback `H_INFO` (D-044).
- `scripts/parse_coverage.py`: counts and Unknown shapes only. Full data: 764
  HDFC messages, 0 left without a template.

## Phase 0: scaffold and deploy (12-13 Nov 2026, tag `phase-0-done`)

- Monorepo: FastAPI backend, Vite React PWA, scripts, infra, docs (D-005);
  paise and UTC rules (D-001, D-002); idempotent ingestion and raw messages
  kept with parser versions as principles (D-003, D-004).
- Exact dependency pins and lockfiles (D-007), LF endings (D-009), httpx kept
  and no unverified packages (D-010).
- `/health` and `/health/db` keep-alive with a header token and a real DB
  write (D-011, D-017); migration `0001` heartbeat; migrations in the Render
  build (D-018).
- Default-deny redaction script; raw SMS outside the repo; agents denied
  `.env` and private data (D-008, D-014, D-015, D-016, D-019).
- Free-tier hosting in Singapore: Vercel, Render, Supabase, cron-job.org
  (D-006, D-012, D-013, D-021 to D-024).
