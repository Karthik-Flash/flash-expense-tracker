# CLAUDE.md

Flash Expense Tracker: an expense tracker that reads Indian bank SMS. Minimal UI,
algorithm-heavy Python engine, an Android app. Monorepo. **New session: read
[Flashexpensetracker_Explained.md](Flashexpensetracker_Explained.md) first** (how
everything works, file by file), then [NOTES.md](NOTES.md) for status and open items and
[docs/operations.md](docs/operations.md) for the commands.

## Hard rules

### Real data and secrets

- **Real data lives outside the repo, in `D:\FlashPrivate\` (`raw\` for SMS
  exports, `private\` for the name map, redaction key and private keep-list,
  `backups\`, `review\`). Never read, open, list, grep, copy or run anything there**,
  nor in `data/raw/` or `data/private/`. Work only from FAKE fixtures, and from
  `data/sample/redacted_sample.json` only after the user says it exists.
- **Never read any `.env` file, never print environment variable values, never
  connect to the real database.** `.env.example` files are fine. Owner commands
  against the real database are the owner's to run.
- **Never run adb** and never install anything on a phone. APK check builds pass FAKE
  Supabase values on the command line only.
- Run `scripts/redact_sms.py` **only on synthetic files that tests create in a
  temp folder**. Redaction is **default-deny**: every counterparty name and UPI ID
  local part is pseudonymised unless keep-listed; `scripts/keep_names.txt` holds public
  brands only.
- `.claude/settings.json` denies all of the above, plus `*.xml` everywhere except
  `mobile/`. A new top-level folder needs its own XML deny rule there.
- Nothing you write (docs, tests, commits) holds real names, emails, phone numbers,
  account numbers or screenshots of real data. FAKE examples only.

### Money and data

- Money is an **integer number of paise**. Never use floats for money. Indian digit
  grouping and Indian English in the UI.
- Store timestamps in **UTC**. Convert to **IST (Asia/Kolkata)** only for display
  and for day/month bucketing.
- Ingestion is **idempotent**: every ingested item has a deterministic dedupe
  key, enforced by a DB unique constraint. Nothing is deleted except by Delete my
  account.
- Store the **raw message** and the **parser version** with every parsed
  transaction, so data can be re-parsed when a parser improves.
- **Owner data wins** and survives reparse; the engine never writes owner data.
  Precedence: an answer for one payment > an owner rule > the engine.
- **A guess never lowers Net.** Removing money from Spent or counting a credit as Paid
  back needs the owner's answer.
- **Totals only on the server.** The app shows the server's figures and never adds up
  money.
- Every owner write goes **through the outbox with an Idempotency-Key**.
- Every route is in the **two-user isolation test**; CORS headers come from the one
  shared list (`frontend/src/api/headers.ts` ↔ `backend/app/main.py`).
- Migrations are **additive**, with RLS on, deleted with the account, and a working
  downgrade (tested up, down and up on SQLite and Postgres 17).
- **Engine changes bump the engine's version** (parsers, merchant, reconcile,
  categorise).
- The ingest contract and the device token's scope (ingest only) change only for bug
  fixes, and stay backward compatible with installed APKs.

### Code and tooling

- Small, tested modules. `ruff check .` and `ruff format --check .` stay clean.
  Every non-trivial algorithm ships with a test.
- Exact dependency pins only (`==` in requirements, exact versions in
  `package.json`, `frontend/.npmrc` has `save-exact=true`); commit lockfiles.
- Never install a package you cannot verify (PyPI owner, source repo). No new package
  or version change without the owner's OK. Gradle, AGP and Capacitor are pinned.
- Ask before starting Docker Desktop.
- No scheduled GitHub workflows. Keep-alive pings live on cron-job.org.
- Never skip tests or loosen lint to get CI green. If stuck, stop and report.
- UI: minimalist and professional; it must not look AI-generated. No redesign without
  the owner. Follow [docs/ui-spec.md](docs/ui-spec.md).

## Layout

| Path        | What                                                         |
| ----------- | ------------------------------------------------------------ |
| `backend/`  | FastAPI app (`app/`: `api/`, `engine/`, `pipeline/`), Alembic, pytest. Render root. |
| `frontend/` | Vite + React + TS + Tailwind app: the website and the Android app's screens. Vercel root. |
| `mobile/`   | The Capacitor Android project and the Kotlin SMS plugin.     |
| `scripts/`  | Standalone tools (redaction, surveys, backups).              |
| `infra/`    | `render.yaml` and the hosting guide.                         |
| `docs/`     | `DECISIONS.md` (decision log), API, data model, engine, privacy, operations, UI spec. |
| `data/`     | Gitignored except README.                                    |

## Commands (Windows PowerShell; on macOS/Linux use `.venv/bin/`)

```powershell
# Backend (from backend/)
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
.\.venv\Scripts\python.exe -m pytest -q
$env:TEST_DATABASE_URL = 'postgresql+psycopg://flash:flash-ci@127.0.0.1:15432/flash_test'   # Postgres 17 in Docker
.\.venv\Scripts\alembic.exe revision --autogenerate -m "msg"; .\.venv\Scripts\alembic.exe upgrade head

# Lint (from repo root, covers backend/ and scripts/)
backend\.venv\Scripts\ruff.exe check . ; backend\.venv\Scripts\ruff.exe format --check .
backend\.venv\Scripts\python.exe -m pytest -q scripts

# Frontend (from frontend/)
npm ci; npm run dev; npm run lint; npm run typecheck; npm test; npm run build
node scripts/cross-origin-check.mjs; node scripts/perf-check.mjs; node scripts/screens.mjs --out <folder outside the repo>

# Android (from frontend/; JAVA_HOME = Android Studio's jbr; FAKE Supabase values for check builds)
npm run android:apk
# Kotlin tests (from mobile/android/)
.\gradlew.bat testDebugUnitTest; .\gradlew.bat --stop
```

Config comes from env vars (`backend/.env`, `frontend/.env`); copy the
`.env.example` files. All commands: [docs/operations.md](docs/operations.md).

## Git workflow

- `main` is always green. Work on a short branch: `feat/...`, `fix/...`,
  `chore/...`, `docs/...`. Merge with `git merge --no-ff`, then delete the branch.
  Never rewrite published history.
- Conventional Commits (`feat(backend): ...`, `fix(scripts): ...`, `ci: ...`). Commit
  messages are UTF-8 without a BOM (write them with a file, `git commit -F`).
- Commit identity: the owner's GitHub identity `Karthik-Flash` with the email set in the
  owner's global instructions; check with `git var GIT_AUTHOR_IDENT` before committing.
- No AI attribution lines in commits or PRs (`Co-Authored-By: Claude`,
  `Claude-Session`, "Generated with Claude Code"; D-109). `.githooks/commit-msg`
  rejects them; enable it once per clone: `git config core.hooksPath .githooks`.
- Push only when the owner asks.
- After **every task**: update `NOTES.md` (status, open items), add new commands to
  `docs/operations.md`, and record lasting decisions in `docs/DECISIONS.md`.
