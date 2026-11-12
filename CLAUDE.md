# CLAUDE.md

Flash Expense Tracker: a personal expense tracker. Minimal UI, algorithm-heavy
Python engine. Monorepo. Read [NOTES.md](NOTES.md) first for current status,
and [docs/PLAN.md](docs/PLAN.md) for the phase you are in.

## Hard rules

- **Never read, open, list, grep, copy or run anything on `data/raw/` or
  `data/private/`.** They hold private SMS exports and the real-to-fake
  pseudonym maps. Work only from `data/sample/redacted_sample.json`, and only
  after the user says it exists. Never run `scripts/redact_sms.py` on real
  data; the user does. `.claude/settings.json` denies these reads, plus `*.xml`
  everywhere except `mobile/`. A new top-level folder needs its own XML deny
  rule there.
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
