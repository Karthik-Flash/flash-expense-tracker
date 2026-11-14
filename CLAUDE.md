# CLAUDE.md

Flash Expense Tracker: a personal expense tracker. Minimal UI, algorithm-heavy
Python engine. Monorepo. **New session: read [docs/HANDOFF.md](docs/HANDOFF.md)
first**, then [NOTES.md](NOTES.md) for current status and
[docs/PLAN.md](docs/PLAN.md) for the phase you are in.

## Hard rules

- **Real data lives outside the repo, in `D:\FlashPrivate\` (`raw\` for SMS
  exports, `private\` for the name map, redaction key and private keep-list).
  Never read, open, list, grep, copy or run anything there**, nor in
  `data/raw/` or `data/private/`. Work only from
  `data/sample/redacted_sample.json`, and only after the user says it exists.
- Run `scripts/redact_sms.py` **only on synthetic files that tests create in a
  temp folder**. The user runs it on real data (command in `data/README.md`).
- **Never read any `.env` file and never print environment variable values.**
  `.env.example` files are fine.
- `.claude/settings.json` denies all of the above, plus `*.xml` everywhere except
  `mobile/`. A new top-level folder needs its own XML deny rule there.
- Redaction is **default-deny**: every counterparty name and UPI ID local part
  is pseudonymised unless keep-listed. Never add guessing logic that decides
  "this looks like a merchant". `scripts/keep_names.txt` holds public brands only.
- Money is an **integer number of paise**. Never use floats for money.
- Store timestamps in **UTC**. Convert to **IST (Asia/Kolkata)** only for display
  and for day/month bucketing.
- Ingestion is **idempotent**: every ingested item has a deterministic dedupe
  key, enforced by a DB unique constraint.
- Store the **raw message** and the **parser version** with every parsed
  transaction, so data can be re-parsed when a parser improves.
- Never commit `.env`, `data/`, virtualenvs, `node_modules/`, or `*.xml` backups.
- Small, tested modules. `ruff check .` and `ruff format --check .` stay clean.
  Every non-trivial algorithm ships with a pytest test.
- No scheduled GitHub workflows. Keep-alive pings live on cron-job.org.
- Never install a package you cannot verify (PyPI owner, source repo). Ask first.
- Exact dependency pins only (`==` in requirements, exact versions in
  `package.json`, `frontend/.npmrc` has `save-exact=true`); commit lockfiles.
- Never skip tests or loosen lint to get CI green. If stuck, stop and report.
- UI: minimalist and professional; it must not look AI-generated. The detailed
  design spec arrives in Phase 3.

## Layout

| Path        | What                                                         |
| ----------- | ------------------------------------------------------------ |
| `backend/`  | FastAPI app (`app/`), Alembic, pytest. Render root.          |
| `frontend/` | Vite + React + TS + Tailwind PWA. Vercel root.               |
| `scripts/`  | Standalone tools. `redact_sms.py` is stdlib only.            |
| `infra/`    | `render.yaml` and hosting/keep-alive guide.                  |
| `docs/`     | `PLAN.md` (phases), `DECISIONS.md` (decision log).           |
| `mobile/`   | Placeholder for the Capacitor Android shell.                 |
| `data/`     | Gitignored except README.                                    |

## Commands (Windows PowerShell; on macOS/Linux use `.venv/bin/`)

```powershell
# Backend (from backend/)
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\alembic.exe revision --autogenerate -m "msg"; .\.venv\Scripts\alembic.exe upgrade head

# Lint (from repo root, covers backend/ and scripts/)
backend\.venv\Scripts\ruff.exe check . ; backend\.venv\Scripts\ruff.exe format --check .
backend\.venv\Scripts\python.exe -m pytest -q scripts

# Frontend (from frontend/)
npm install; npm run dev; npm run typecheck; npm run build
```

Config comes from env vars (`backend/.env`, `frontend/.env`); copy the
`.env.example` files. Python deps: pin direct dependencies with `==` in
`requirements.txt` (runtime) and `requirements-dev.txt` (tools).

## Git workflow

- `main` is always green. Work on a short branch: `feat/...`, `fix/...`,
  `chore/...`, `docs/...`. Merge with `git merge --no-ff`, then delete the branch.
- Conventional Commits (`feat(backend): ...`, `fix(scripts): ...`, `ci: ...`).
- Commit identity: `Karthik-Flash <karthikeyareddy1905@gmail.com>`. Check with
  `git var GIT_AUTHOR_IDENT` before committing.
- Update `NOTES.md` after **every task**: tick what is done, add any new
  commands to its cheat sheet, list what is still open. Record lasting decisions in
  `docs/DECISIONS.md`. The planner owns `docs/PLAN.md`; propose changes there,
  do not silently rewrite it.
