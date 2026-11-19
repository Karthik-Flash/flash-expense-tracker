# Handoff

For a fresh Claude Code session with no memory of earlier work. Read this
first, then [OVERVIEW.md](OVERVIEW.md) (the one-page tour),
[NOTES.md](../NOTES.md) (status, cheat sheet, log) and the phase in
[PLAN.md](PLAN.md).

## Current state (Phase 4, 19 Nov 2026)

- Phases 0 to 3 are done. Phase 4 runs as 4C, 4B, 4E, 4F, 4D, with 4A (the
  bank statement check carried from Phase 3) done before 4D
  ([PLAN.md](PLAN.md)). 4C (install and update prompt) and 4B-1 (phone
  copy and instant open) are done; next 4B-2 (queued taps).
- Engine versions: parser `hdfc-1.1.1`, `merchant-1.1.1`,
  `reconcile-1.3.0`, `categorise-1.0.0`.
- Alembic head: `0006` (categories and labels).
- Decisions: D-001 to D-090 ([DECISIONS.md](DECISIONS.md)).
- Live: app https://flash-expense-tracker.vercel.app, API
  https://flash-expense-tracker.onrender.com (more under "Live URLs").
- The app: real login (Supabase Auth) and data (`/api/v1`), every screen,
  category colours, the ring chart and the FLA$H logo
  ([ui-spec.md](ui-spec.md), [api.md](api.md)). Installable; a new deploy
  shows "New version available" and Home shows the build id (D-085 to
  D-087). Screens read one snapshot (`/api/v1/sync/snapshot`) kept on the
  phone in IndexedDB and open from it at once; every money figure comes
  from the server (D-088 to D-090).

### Owner commands

The owner runs these; agents never do (real data). Exact arguments are in
the NOTES.md cheat sheet. CLI commands run from `backend\` as
`.\.venv\Scripts\python.exe -m app.cli <command>`; all print counts only
unless marked private.

| Command | What it does |
| ------- | ------------ |
| `import-sms --input D:\FlashPrivate\raw` (`--dry-run` first) | Stores new bank messages and transactions; a repeat adds nothing |
| `reparse --dry-run`, then `reparse` | After a parser version bump: new results, same transaction ids |
| `recompute` (`--accept-key-changes` when asked) | Rebuilds roles, links and categories from transactions and owner data |
| `stats`, `merchant-stats`, `reconcile-stats`, `category-stats` | Counts, safe to paste |
| `totals --month 2026-11` | The month's totals (private) |
| `merchant-review`, `reconcile-review`, `category-review`, `credit-review` | Terminal-only reviews and answers (private) |
| `owner-load <file>`, `owner-export <file>` | Owner file into the owner tables, and back out (files in `D:\FlashPrivate\private\`) |
| `scripts\redact_sms.py ... --verify` (from the repo root) | Makes the redacted sample; must end with `Leaks: 0` |
| `powershell -ExecutionPolicy Bypass -File scripts\backup_db.ps1` (from the repo root) | Backs up the database to `D:\FlashPrivate\backups\` (Docker running) |

## Goal and locked stack

Flash Expense Tracker: a personal expense tracker for one user in India. It
turns bank SMS into transactions. Minimal UI, algorithm-heavy Python engine.
Monorepo.

| Part | Stack (exact pins) | Hosting |
| ---- | ------------------ | ------- |
| Backend | Python 3.12.12, FastAPI 0.162.5, SQLAlchemy 2.1.8, Alembic 1.20.1, psycopg 3.3.9, pydantic-settings 2.16.2, PyJWT 2.15.1, cryptography 50.0.2 | Render free, Singapore |
| Database | Postgres (Supabase free, Singapore, Session pooler; Data API exposes only `keepalive`, D-053); SQLite for local and tests | Supabase |
| Frontend | Vite 8, React 19, TypeScript 7, Tailwind 4, vite-plugin-pwa 2.0.0, @supabase/supabase-js 2.119.0, idb 8.0.4 (fake-indexeddb 6.2.8 in tests) | Vercel |
| Tools | pytest 9.2.0, ruff 0.17.4, httpx 0.28.1 | GitHub Actions |
| Keep-alive | cron-job.org calls `keepalive.ping()` via the Data API (D-053); a second job keeps Render warm | |

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
  app/api/auth.py     Supabase login (ES256 JWT via JWKS), AUTH_USERS -> owner
  app/api/v1.py       data API /api/v1 (docs/api.md)
  app/api/snapshot.py GET /api/v1/sync/snapshot: the app's one read, ETag and 304 (D-088)
  app/config.py       settings from env / backend/.env (DATABASE_URL, PING_TOKEN, CORS_ORIGINS, OWNER_ID)
  app/db.py           engine, SessionLocal, Base
  app/models.py       ORM models; UtcDateTime column type
  app/engine/         stdlib-only parser: senders, money, timeparse, filters (OTP), models, parsers/{base,hdfc}, merchant (+ brands.json), reconcile (roles and links), categorise
  app/pipeline/       dedupe.py (pure rules), store.py (per-message ingest), reparse.py, owner_load.py (owner file -> owner tables), recompute.py (derive -> derived tables)
  app/importers/      sms_backup.py (streaming XML importer)
  app/cli.py          python -m app.cli import-sms | reparse | stats | merchant-stats | merchant-review | reconcile-stats | owner-load | recompute | reconcile-review | owner-export | totals | category-stats | category-review | credit-review
  alembic/versions/   0001 heartbeat, 0002 import pipeline tables, 0003 keepalive.ping(), 0004 owner tables, 0005 derived tables, 0006 categories and labels
  tests/              pytest; conftest forces a throwaway SQLite DATABASE_URL
frontend/           Vercel root (docs/ui-spec.md): src/api (Api interface; http.ts real adapter, fake.ts demo adapter for VITE_DEMO=1 in dev), src/auth.ts (Supabase login), src/screens (Ring.tsx chart), src/brand.tsx ($ mark, FLA$H wordmark), src/lib (money, IST dates), src/view.ts (URL state), src/icons (Lucide SVGs), src/pwa.ts (manifest and service worker options, build id), src/update.ts (update bar), src/data (local.ts: the IndexedDB phone copy; store.ts: snapshot, refresh, freshness, timings), src/screens/Speed.tsx (Speed sheet)
scripts/            standalone, stdlib: redact_sms.py, shape_survey.py, parse_coverage.py (+ tests); backup_db.ps1 (owner: pg_dump via Docker)
infra/              render.yaml (reference copy), README.md (setup and runbook)
docs/               PLAN, DECISIONS (D-001..D-090), engine.md, data-model.md, api.md, design/phase-3-backbone.md, templates/hdfc.md, this file
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
npm ci; npm run dev; npm run lint; npm run typecheck; npm test; npm run build
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
  `alembic check`, pytest), frontend (lint, typecheck, test, build).
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

A second job, "Flash API warm 07-01 IST", sends `GET
https://flash-expense-tracker.onrender.com/health` with the header `Accept:
application/json` every 10 minutes in hours
07 to 23 and 00 IST (last ping 00:50), so the API is awake when the owner
uses the app. `/health` never touches the database
(`backend/app/api/health.py`). It uses about 560 of Render's 750 free hours a
month. The daily 03:30 IST Supabase keepalive job is unchanged.

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

## Open items

1. Bank statement check (step 4A): one normal and one messy month against
   the statement, "match" or the difference in rupees. 4A also settles the
   unticked "merged refund" check in NOTES (one event or two, D-064).
2. Joining one person seen under a name and a UPI ID, in the app (step 4E).
   Today only the owner file can list both texts on one party (D-079). 4E
   gives each To-do sender card "See payments", "Name this person" and
   "Same as…" (the person join).
3. November data ends at the 14 Nov 2026 export; live SMS is Phase 5.
4. Not counted: 153 messages from banks without a parser (SBI, ICICI, India
   Post, Kotak, PhonePe; add a parser, then reparse; step 4F) and 44
   foreign-currency messages (D-035).
5. Close category colour pairs (OKLab distance about 4 to 5, such as card
   bill and uncategorised); icons and names carry identity (D-081).
6. Not checked: real iOS, screen readers, 200 % text on the 3F-3 screens.
   The 4C update bar and version line were checked at 360 px, light, dark
   and 200 % in headless Edge only; the 4B-1 screens in headless Edge at
   390 px on demo data. Speed sheet timings on a real phone are still to come.
7. Accepted risk: npm audit, 4 moderate findings, build-time only: glob
   11.1.0 (GHSA-3g3m-2fjr-6pw4) and minimatch 10.2.6 and 5.1.9
   (GHSA-g3hv-75wg-m249), via vite-plugin-pwa 2.0.0 and workbox-build 7.4.1,
   the newest releases. No patched release in the same major, so no
   override. Recheck when Workbox ships a fix; never `npm audit fix --force`.
8. The labels column allows 80 characters, the API 30; owner-file labels
   may be longer than the app allows (step 4E).
9. The Supabase free plan has no backups; the owner runs
   `scripts/backup_db.ps1` (D-084).
10. The owner's To-do backlog (about 100 items) to work through on the
    phone (a faster To-do is step 4E).
11. The owner doubts the October People total: verify it person by person.
12. Vercel: `VITE_API_URL` is saved as a Secret. The owner changes it to a
    plain variable and redeploys with the build cache off.
13. Offline taps are not queued yet: owner actions need a connection
    (step 4B-2).
14. Later list: a friendlier Home, still minimal; revisit with 4D.

Known limits: HDFC and INR only; the card bill pair rule waits for credit
card SMS; the server sleeps when idle (about a minute to wake; kept awake
07:00 to 00:50 IST by the warm job); import takes about 6 minutes for 917
messages; Starlette's httpx warning is accepted (D-010).

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
  Conventional Commits, `git merge --no-ff` into `main`, delete the branch.
  Claude Code commits and merges locally and never pushes; the owner pushes
  after the planner reviews, then confirms CI.
- Commit identity: `Karthik-Flash <karthikeyareddy1905@gmail.com>`; check
  `git var GIT_AUTHOR_IDENT` first.
- Update NOTES.md after every task: status, cheat sheet, open items, log.
- End with a short report (commits, CI, test counts, what the user must do)
  and STOP. Do not start the next phase until asked.
- Raise spec problems instead of silently following them (example: mandate
  IDs as dedupe keys would have merged monthly charges; fixed in D-046).
