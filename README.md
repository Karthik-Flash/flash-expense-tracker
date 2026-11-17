# Flash Expense Tracker

Personal expense tracker. It turns bank, card and UPI SMS alerts into clean
transactions, then categorizes and analyzes them. Minimal UI, algorithm-heavy
Python engine.

Status: Phase 3 done (18 Nov 2026). New here? Start with
[docs/OVERVIEW.md](docs/OVERVIEW.md), a one-page tour. Then
[NOTES.md](NOTES.md) and [docs/PLAN.md](docs/PLAN.md).

## Stack

- **backend/**: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, pydantic-settings,
  pytest, ruff. Hosted on Render (free).
- **frontend/**: React, Vite, TypeScript, Tailwind CSS, installable PWA
  (vite-plugin-pwa). Hosted on Vercel.
- **Database**: SQLite locally, Supabase Postgres in production.

## Quick start (Windows PowerShell)

Needs Python 3.12 and Node 24. On macOS/Linux, use `.venv/bin/` in place of
`.venv\Scripts\`.

```powershell
# Backend: http://localhost:8000/health
cd backend
py -3.12 -m venv .venv          # or: uv venv --python 3.12 --seed .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# Frontend: http://localhost:5173 (second terminal)
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Checks (the same ones CI runs):

```powershell
backend\.venv\Scripts\ruff.exe check . ; backend\.venv\Scripts\ruff.exe format --check .
cd backend; .\.venv\Scripts\python.exe -m pytest -q; cd ..
backend\.venv\Scripts\python.exe -m pytest -q scripts
cd frontend; npm run typecheck; npm run build
```

## Layout

```
backend/    FastAPI app, Alembic migrations, tests
frontend/   Vite React PWA
scripts/    redact_sms.py (makes a safe SMS sample from a backup)
infra/      render.yaml and hosting guide (Vercel, Render, Supabase, cron-job.org)
docs/       HANDOFF.md, PLAN.md, DECISIONS.md, engine and data-model guides
mobile/     Capacitor Android shell (later phase)
data/       gitignored; see data/README.md
```

Rules for contributors and agents are in [CLAUDE.md](CLAUDE.md).
