# Handoff

For a fresh Claude Code session with no memory of earlier work. Read this
first, then [NOTES.md](../NOTES.md) (status, cheat sheet, log) and the phase
in [PLAN.md](PLAN.md). State as of 15 Nov 2026: Phases 0-2 done (tags
`phase-0-done`, `phase-1-done`, `phase-2-done`); Phase 3 is in progress
(3B merchant engine and 3C-2 Reconcile roles are built; NOTES.md has the
current step).

## Goal and locked stack

Flash Expense Tracker: a personal expense tracker for one user in India. It
turns bank SMS into transactions. Minimal UI, algorithm-heavy Python engine.
Monorepo.

| Part | Stack (exact pins) | Hosting |
| ---- | ------------------ | ------- |
| Backend | Python 3.12.12, FastAPI 0.162.5, SQLAlchemy 2.1.8, Alembic 1.20.1, psycopg 3.3.9, pydantic-settings 2.16.2 | Render free, Singapore |
| Database | Postgres (Supabase free, Singapore, Session pooler; Data API exposes only `keepalive`, D-053); SQLite for local and tests | Supabase |
| Frontend | Vite 8, React 19, TypeScript 7, Tailwind 4, vite-plugin-pwa | Vercel |
| Tools | pytest 9.2.0, ruff 0.17.4, httpx 0.28.1 | GitHub Actions |
| Keep-alive | cron-job.org calls `keepalive.ping()` via the Data API (D-053) | |

The stack is locked. Never install a package you cannot verify (PyPI owner,
source repo); ask first (D-010).

## Non-negotiable rules

- **Real data never reaches git or AI tools.** SMS exports live in
  `D:\FlashPrivate\raw\`; the redaction key, name map, keep and always-redact
  lists and the full redacted export live in `D:\FlashPrivate\private\`
  (D-015, D-051). Never read, list, grep, copy or run anything there, nor in
  `data/raw/` or `data/private/`. `.claude/settings.json` enforces this, plus
  every `.env` file and `*.xml` outside `mobile/`.
- **Never read any `.env` file or print environment variable values.**
  `.env.example` files are fine.
- **Never connect to Supabase and never run the importer or the redaction
  script on real data.** Supabase holds the real data (D-048). The user runs
  those commands. Agents use synthetic data: tests build fake messages from
  `backend/tests/fixtures/sms/hdfc.json`. Only
  `data/sample/redacted_sample.json` (288 redacted messages) may be read, and
  no message body from it may be copied into a committed file.
- **Logs and CLI output: counts, ids, versions, timings only.** Never bodies,
  names, amounts, references or account digits (invariant I9).
- **Money is an integer number of paise** (`Decimal` while parsing, BIGINT in
  the database). Never floats (D-001).
- **Times are stored in UTC.** IST (fixed +05:30, no zoneinfo) only for
  display and day/month buckets (D-002, D-043).
- **Ingestion is idempotent.** Raw messages dedupe on `content_hash`;
  transactions on `dedupe_key`; both enforced by unique constraints (D-046).
- **Keep the raw message and the parser version** with every parse, so data
  can be re-parsed (D-004, D-042).
- **Redaction is default-deny.** Every counterparty name and UPI local part
  is pseudonymised unless keep-listed. No "looks like a merchant" guessing.
- Exact pins only (`==`; `frontend/.npmrc` has `save-exact=true`), lockfiles
  committed. `ruff check .` and `ruff format --check .` stay clean. Never skip
  tests or loosen lint to get CI green; if stuck, stop and report.
- No scheduled GitHub workflows. UI must look minimalist and professional.

## Repo map

```
backend/            Render root
  app/main.py         FastAPI app, CORS
  app/api/health.py   /health (no DB), /health/db (X-Ping-Token, heartbeat upsert)
  app/config.py       settings from env / backend/.env (DATABASE_URL, PING_TOKEN, CORS_ORIGINS, OWNER_ID)
  app/db.py           engine, SessionLocal, Base
  app/models.py       ORM models; UtcDateTime column type
  app/engine/         stdlib-only parser: senders, money, timeparse, filters (OTP), models, parsers/{base,hdfc}, merchant (+ brands.json), reconcile (roles, in memory)
  app/pipeline/       dedupe.py (pure rules), store.py (per-message ingest), reparse.py
  app/importers/      sms_backup.py (streaming XML importer)
  app/cli.py          python -m app.cli import-sms | reparse | stats | merchant-stats | merchant-review | reconcile-stats
  alembic/versions/   0001 heartbeat, 0002 import pipeline tables, 0003 keepalive.ping()
  tests/              pytest; conftest forces a throwaway SQLite DATABASE_URL
frontend/           Vercel root; src/App.tsx shows backend status, survives cold starts
scripts/            standalone, stdlib: redact_sms.py, shape_survey.py, parse_coverage.py (+ tests)
infra/              render.yaml (reference copy), README.md (setup and runbook)
docs/               PLAN, DECISIONS (D-001..D-068), engine.md, data-model.md, design/phase-3-backbone.md, templates/hdfc.md, this file
mobile/             placeholder for the Capacitor Android shell
data/               gitignored except README; only data/sample/redacted_sample.json is for agents
```

## Run, test, deploy (Windows PowerShell)

```powershell
# Backend (from backend\)
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
.\.venv\Scripts\python.exe -m pytest -q
# Lint and script tests (from the repo root)
backend\.venv\Scripts\ruff.exe check . ; backend\.venv\Scripts\ruff.exe format --check .
backend\.venv\Scripts\python.exe -m pytest -q scripts
# Frontend (from frontend\)
npm ci; npm run dev; npm run typecheck; npm run build
```

- `backend/.env` may point at Supabase. Before running anything that uses the
  database (Alembic, the CLI), set `DATABASE_URL` in the environment to a
  temp SQLite file; environment variables override `.env`. Tests do this
  themselves.
- Postgres tests: set `TEST_DATABASE_URL` to a disposable container (CI uses
  a `postgres:17` service). Locally, ask the user first, then `docker desktop start` and run
  `postgres:17` on a free port such as 15432 (Windows reserves some ports).
- CI (`.github/workflows/ci.yml`), three jobs: backend (ruff, backend and
  scripts pytest), backend on Postgres 17 (`alembic upgrade head`,
  `alembic check`, pytest), frontend (typecheck, build).
- Deploy: push to `main`. Render deploys after CI passes and runs
  `alembic upgrade head` in its build (D-018, D-050). Vercel deploys the
  frontend on every push. A new migration therefore reaches Supabase on the
  next deploy: keep migrations additive.

## Live URLs (public)

- App: https://flash-expense-tracker.vercel.app
- API: https://flash-expense-tracker.onrender.com (`/health`; `/health/db`
  needs the header and answers 401 without it)
- Repo (private): https://github.com/Karthik-Flash/flash-expense-tracker

Render sleeps after 15 min idle (cold start ~50 s). The keep-alive does not
use Render: cron-job.org "Flash DB heartbeat" sends
`POST https://<ref>.supabase.co/rest/v1/rpc/ping` daily at 03:30 IST
(`apikey` = publishable key, `Content-Profile: keepalive`). That runs
`keepalive.ping()`, which writes the heartbeat row so Supabase does not
pause. The Data API exposes only the `keepalive` schema; never add `public`
(D-053). `/health/db` with `X-Ping-Token` stays for manual checks.

## Data pipeline as built

```
phone export (XML) --user--> D:\FlashPrivate\raw\
   |                                  |
   | scripts/redact_sms.py (user)     | python -m app.cli import-sms (user, from backend\)
   v                                  v
redacted sample (288 msgs)        raw_messages --engine--> parse_results --money--> transactions
-> survey, fixtures, parsers      (registry senders;        (one current     (dedupe key) + sources
                                   no OTP/promo/MMS)         per message)     + duplicate_candidates
```

1. **Redaction** (`scripts/redact_sms.py`, user only): default-deny
   pseudonyms, HMAC fakes, `--verify` leak check (D-016, D-039, D-040).
2. **Engine** (`app/engine`): `parse_message(sender, body, received_at)`
   returns `ParsedMessage` or `Unknown(reason)`. Literal whole-body templates;
   exactly one may match; amount-free unmatched notices become `H_INFO`
   other_info; amounts are never guessed (docs/engine.md, D-041, D-044).
   HDFC is the only parser: `hdfc-1.1.1`.
3. **Import** (`app/importers`, `app/pipeline`): streams XML, stores only
   bank-registry senders (with or without a parser), parses, upserts
   transactions, records fuzzy candidates. Batched commits, crash-safe,
   `--dry-run` rolls back (docs/data-model.md).
4. **Reparse**: after a parser version bump, `python -m app.cli reparse`
   adds new results, keeps transaction ids stable, deletes nothing.

Real import (14 Nov): 917 messages stored, 720 parsed, 678 transactions,
18 open duplicate candidates; re-import added nothing.

## Open items and known limits

- Keep-alive switched to the Data API RPC and verified 15 Nov (security
  check 8/8 blocked, cron test run 200, `last_seen` moved); the first
  scheduled 03:30 run is still to check (D-053).
- Reconcile (3C) is partly built. Done: the approved design
  (`docs/design/phase-3-backbone.md`, D-059 to D-067) and step 3C-2, one
  role per transaction in memory plus `reconcile-stats`. Not built: owner
  data in the database, duplicates, pair links, storage, `recompute`, the
  terminal review (steps 3C-3 to 3C-8). So the 18 open duplicate
  candidates and the 1 merged refund are still to review, and nothing is
  stored or shown yet.
- Foreign currency is deferred: 44 messages (D-035).
- Only HDFC has a parser: 153 messages from SBI, ICICI, India Post, Kotak
  and PhonePe sit as `no_parser_for_bank`. Add a parser (docs/engine.md,
  "Adding a bank"), then reparse; no re-import.
- HDFC H09 word slot is still pseudonymised in the sample; harmless.
- Import speed ~6 min for 917 messages (about 8 round trips each); batch the
  lookups for a larger source.
- No API endpoints beyond health, no auth (single `OWNER_ID`), no UI beyond
  the status page, no categories, no manual entry or statements yet.
- Starlette's httpx deprecation warning is known and accepted (D-010).

## Where decisions live

- `docs/DECISIONS.md`: numbered, dated, never deleted; superseded entries
  say so (e.g. D-023 by D-052). Add a new number for each lasting decision.
- `docs/PLAN.md`: owned by the planner. Propose changes; do not rewrite.
- `docs/engine.md`, `docs/data-model.md`, `docs/templates/hdfc.md`: how the
  engine and pipeline work. `CHANGELOG.md`: what each phase shipped.
- `NOTES.md`: status, the user's to-do list, cheat sheet, open items, log.

## How the user works

- A separate planner writes phased prompts, often as lettered blocks. You
  implement them in order and stop when a block needs the user (real data,
  dashboards, secrets).
- Each task: a short branch (`feat/`, `fix/`, `docs/`, `chore/`), small
  Conventional Commits, `git merge --no-ff` into `main`, delete the branch,
  push, confirm CI green on all jobs.
- Commit identity: `Karthik-Flash <karthikeyareddy1905@gmail.com>`; check
  `git var GIT_AUTHOR_IDENT` first.
- Update NOTES.md after every task: status, cheat sheet, open items, log.
- End with a short report (commits, CI, test counts, what the user must do)
  and STOP. Do not start the next phase until asked.
- Raise spec problems instead of silently following them (example: mandate
  IDs as dedupe keys would have merged monthly charges; fixed in D-046).
