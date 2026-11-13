# Notes

Quick reference and progress log. Updated after every task.

## Links

| What               | URL                                                          |
| ------------------ | ------------------------------------------------------------ |
| App (Vercel)       | https://flash-expense-tracker.vercel.app                     |
| API (Render)       | https://flash-expense-tracker.onrender.com                   |
| GitHub repo        | https://github.com/Karthik-Flash/flash-expense-tracker (private) |
| GitHub Actions     | https://github.com/Karthik-Flash/flash-expense-tracker/actions |
| Render dashboard   | https://dashboard.render.com/web/srv-dbra0pei0phs73f8c250    |
| Vercel dashboard   | https://vercel.com/karthik-flashs-projects                   |
| Supabase dashboard | https://supabase.com/dashboard (project in Singapore)        |
| cron-job.org       | https://console.cron-job.org/jobs                            |

## Status

Phase 0 (scaffold, closeout, deploy): **deployed and verified**. Two checks left.

- [x] Monorepo, Python 3.12 venv, exact pins, lockfile, LF endings, CI green
- [x] Backend `/health`, `/health/db` (`X-Ping-Token`), migration `0001`
- [x] Frontend PWA showing backend status, handles cold starts
- [x] `scripts/redact_sms.py`: default-deny, keep-list, HMAC fakes
- [x] Agent deny rules: `D:\FlashPrivate\`, every `.env`, `*.xml` outside `mobile/`
- [x] Supabase, Render, Vercel, cron-job.org set up and tested (13 Nov 2026)
- [ ] Overnight cron check: after 03:30 IST, confirm `heartbeat.last_seen` moved
- [ ] Redaction run on the real backup, then review the sample
- [ ] Phase 1: planner refines it in [docs/PLAN.md](docs/PLAN.md)

## Your to-do list

1. Tomorrow morning: open cron-job.org history. Both jobs should show 200
   around 03:27 to 03:30 IST. In Supabase Table Editor, `heartbeat.last_seen`
   should be about 22:00 UTC of the previous day (= 03:30 IST).
2. Run the three redaction commands (Cheat sheet below), review the sample.
3. Tell me the sample exists. Then parsing work can start (Phase 2).

## Architecture

### The pieces and how they connect

```
                          you (browser / phone)
                                   |
                                   | 1. HTTPS: load the app
                                   v
  +-----------------------------------------------------+
  | Vercel  (global CDN)                                 |
  | https://flash-expense-tracker.vercel.app             |
  | Static PWA built from frontend/                      |
  | VITE_API_URL baked in at build time                  |
  +-----------------------------------------------------+
                                   |
                                   | 2. fetch(VITE_API_URL + "/health")
                                   |    from your browser, cross-origin
                                   v
  +-----------------------------------------------------+        3. GET /health (03:27, 03:28 IST)
  | Render  (Free web service, Singapore)                | <----- 4. GET /health/db + X-Ping-Token
  | https://flash-expense-tracker.onrender.com           |           (03:30 IST)
  | Cloudflare edge -> uvicorn -> FastAPI (backend/)     |        +--------------------------------+
  | Env: DATABASE_URL, PING_TOKEN, CORS_ORIGINS,         |        | cron-job.org                   |
  |      PYTHON_VERSION                                  |        | "Flash wake-up"                |
  | Sleeps after 15 min idle; cold start ~50 s           |        | "Flash DB heartbeat"           |
  +-----------------------------------------------------+        | emails you if the DB job fails |
                                   |                             +--------------------------------+
                                   | 5. Postgres over TLS (sslmode=require)
                                   |    via Supabase Session pooler, port 5432
                                   v
  +-----------------------------------------------------+
  | Supabase  (Free Postgres, Singapore)                 |
  | tables: heartbeat, alembic_version                   |
  | Data API off: no public REST access to tables        |
  | Pauses after 7 days without activity                 |
  +-----------------------------------------------------+

  +-----------------------------------------------------+
  | GitHub  Karthik-Flash/flash-expense-tracker          |
  | push to main  -> GitHub Actions CI (lint, tests, build)
  |               -> Render auto-deploy  (backend/)      |
  |               -> Vercel auto-deploy  (frontend/)     |
  +-----------------------------------------------------+
```

### Flow 1: you open the app

1. Browser loads `https://flash-expense-tracker.vercel.app`. Vercel serves the
   static files from its CDN. Render is not involved yet.
2. The page runs `fetch("https://flash-expense-tracker.onrender.com/health")`.
   The URL is whatever `VITE_API_URL` was when Vercel last built the frontend.
3. The request reaches Render (Cloudflare in front, then uvicorn). If the
   service is asleep, Render holds the request while it boots (~50 s). The
   page shows "Server is waking up (attempt n/24)" and retries every 5 s.
4. FastAPI answers `{"status":"ok","version":"0.1.0"}`. Because the page's
   origin is in `CORS_ORIGINS`, the response carries
   `access-control-allow-origin`, and the browser lets the page read it.
5. The page shows "Backend online · v0.1.0". `/health` never touches the
   database.

### Flow 2: nightly keep-alive (all times IST)

1. 03:27 and 03:28: "Flash wake-up" calls `GET /health`. This wakes Render.
   The first call may time out (cron-job.org waits only 30 s); that is
   expected, so its alerts are off.
2. 03:30: "Flash DB heartbeat" calls `GET /health/db` with header
   `X-Ping-Token`. Render is warm, so it answers fast.
3. FastAPI checks the header against `PING_TOKEN` (`secrets.compare_digest`).
   Missing or wrong: 401. `PING_TOKEN` unset on Render: 503.
4. FastAPI connects to Supabase through the Session pooler and runs one upsert:
   `heartbeat` row `id=1` gets `last_seen = now()` from the database clock.
5. Supabase records activity, so the free project does not pause.
6. FastAPI returns `{"db":"ok","latency_ms":N}`. If anything fails (Render
   down, DB down, wrong token), cron-job.org emails you.

### Flow 3: you push code

1. `git push` to `main` on GitHub.
2. Three things start in parallel. They do not wait for each other:
   - GitHub Actions CI: ruff, backend pytest, scripts pytest, typecheck, build.
   - Render: `pip install -r requirements.txt && alembic upgrade head`
     (migrations hit Supabase during the build), then starts
     `uvicorn app.main:app`. If the build or migration fails, the old version
     keeps serving.
   - Vercel: `npm install` and `npm run build` in `frontend/`, with
     `VITE_API_URL` baked in, then publishes to the CDN.
3. Check CI with `gh run watch`. A red CI does not stop Render or Vercel from
   deploying, so do not push to `main` with failing checks.

### Flow 4: real data to a shareable sample (you run it, agents never do)

1. Your phone's SMS Backup & Restore export sits in `D:\FlashPrivate\raw\`
   (outside the repo).
2. You run `scripts/redact_sms.py`. It reads the export, and keeps its key and
   name map in `D:\FlashPrivate\private\`.
3. It writes `data\sample\redacted_sample.json` (gitignored). Only this file
   is shared with agents and the planner.
4. Phase 2 parsers are built and tested against that sample.

### Where each setting lives

Values are never written in git or chat. Keep them in your password manager.

| Setting        | Used by          | Lives in                                                  |
| -------------- | ---------------- | --------------------------------------------------------- |
| `DATABASE_URL` | Render, Alembic  | Render env; `backend/.env` for local; password manager   |
| `PING_TOKEN`   | `/health/db`     | Render env; cron-job.org job header; password manager    |
| `CORS_ORIGINS` | FastAPI CORS     | Render env: `http://localhost:5173,https://flash-expense-tracker.vercel.app` |
| `VITE_API_URL` | Frontend build   | Vercel env: `https://flash-expense-tracker.onrender.com`; `frontend/.env` for local |
| `PYTHON_VERSION` | Render build   | Render env: `3.12.12`                                     |
| DB password    | Supabase         | Supabase dashboard; password manager (letters + digits only) |
| GitHub login   | `git push`, `gh` | Windows credential store (`gh auth status`)               |

## Gotchas

- Run backend commands from `backend\` (cd first). Use
  `.\.venv\Scripts\python.exe -m alembic ...` for migrations.
- No trailing slash on base URLs (`VITE_API_URL`, `CORS_ORIGINS`, `$u` in the
  test commands). `https://...onrender.com//health` returns 404.
- Opening `/health/db` in a browser returns 401 by design: a browser cannot
  send the `X-Ping-Token` header.
- `GET /` on Render returns 404 by design. Only `/health` and `/health/db` exist.
- Run only one Vite dev server at a time. If it starts on port 5174, CORS
  blocks it because only 5173 is allowed.
- DB password: letters and digits only. `#` and `%` broke `DATABASE_URL`
  parsing.
- Supabase shows "RLS disabled" / "UNRESTRICTED" on `heartbeat` and
  `alembic_version`. Harmless while the Data API stays off; the app connects
  as the `postgres` role directly. Turning the Data API back on would expose
  these tables.
- Render's own health checks (every few seconds from `10.x` addresses in the
  log) are normal.
- After changing `VITE_API_URL` in Vercel, redeploy the frontend; the value is
  baked in at build time. After changing Render env vars, Render redeploys by
  itself.

## Cheat sheet

All commands run from the repo root in PowerShell unless noted.

### Check the live system

```powershell
$u = "https://flash-expense-tracker.onrender.com"
Invoke-RestMethod "$u/health"                                            # status ok, no token needed
$t = Read-Host "PING_TOKEN"
Invoke-RestMethod "$u/health/db" -Headers @{ "X-Ping-Token" = $t }       # db ok + latency_ms
```

### Run the apps locally

```powershell
cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000   # terminal 1
cd frontend; npm run dev                                                             # terminal 2, http://localhost:5173
```

### Checks (same as CI)

```powershell
backend\.venv\Scripts\ruff.exe check . ; backend\.venv\Scripts\ruff.exe format --check .
cd backend; .\.venv\Scripts\python.exe -m pytest -q; cd ..
backend\.venv\Scripts\python.exe -m pytest -q scripts
cd frontend; npm run typecheck; npm run build; cd ..
```

### Dependencies

```powershell
cd frontend; npm ci; cd ..                      # install exactly what package-lock.json says
cd frontend; npm install some-pkg; cd ..        # .npmrc save-exact pins it automatically
```

Python: edit the `==` pin in `backend\requirements*.txt`, then
`backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt`.

### Database migrations (from `backend\`)

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head                               # apply all migrations
.\.venv\Scripts\python.exe -m alembic current                                    # show applied revision
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "what changed"  # after a model change
```

Render's build runs `alembic upgrade head` once per deploy.

### PING_TOKEN

```powershell
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString('x2') })
```

Rotation steps: [infra/README.md](infra/README.md), Runbook.

### SMS redaction (you run these; agents never do)

```powershell
# 1. Sender IDs and counts only
backend\.venv\Scripts\python.exe scripts\redact_sms.py --input D:\FlashPrivate\raw --private-dir D:\FlashPrivate\private --list-senders

# 2. Names and UPI IDs with counts; anything not marked "yes" gets pseudonymised
backend\.venv\Scripts\python.exe scripts\redact_sms.py --input D:\FlashPrivate\raw --private-dir D:\FlashPrivate\private --list-counterparties

# 3. Write the sample
backend\.venv\Scripts\python.exe scripts\redact_sms.py --input D:\FlashPrivate\raw --private-dir D:\FlashPrivate\private --output data\sample\redacted_sample.json --limit 50
```

- Keep a public brand: add it to `scripts\keep_names.txt` (committed).
- Keep something private: add it to `D:\FlashPrivate\private\keep_names.txt`.
- Back up `D:\FlashPrivate\private\redaction.key` and `name_map.json`.

### Git: daily loop

```powershell
git switch main; git pull                         # start from latest main
git switch -c feat/short-name                     # new branch (same as checkout -b)
git add -p                                        # stage piece by piece
git commit -m "feat(scope): what and why"
git switch main; git merge --no-ff feat/short-name
git branch -d feat/short-name
git push                                          # CI + Render + Vercel all start
git log --oneline --graph -15                     # recent history
```

### Push and CI

```powershell
gh run list --limit 5                             # recent CI runs
gh run watch                                      # follow the latest run live
gh run view --log-failed                          # only the failing step logs
gh repo view --web                                # open the repo in the browser
```

## Open items

1. Starlette warns `httpx` with `TestClient` is deprecated (suggests `httpx2`).
   Kept `httpx` until the replacement is verified (DECISIONS D-010).
2. Phase 1 schema: confirm the dedupe key recipe before the next migration.
3. Name detection covers the usual bank positions only; skim the sample.
4. Replace the placeholder PWA icons before launch (UI spec: Phase 3, D-020).
5. Optional: set Render **Auto-Deploy** to "After CI Checks Pass" so a red CI
   never reaches production.

## Log

### 2026-11-13: Phase 0 deploy (done by hand)

- **Supabase**: project in Singapore. Session pooler connection string,
  Data API off. DB password reset to letters and digits only (the old one had
  `#` and `%`, which broke URL parsing). Migration `0001` applied through the
  Render build; `heartbeat` row verified in Table Editor.
- **Render**: service `flash-expense-tracker`, Singapore, Free, root
  `backend`, health check `/health`. URL
  https://flash-expense-tracker.onrender.com. Verified: `/health` 200,
  `/health/db` with header 200 (~165 ms), without header 401.
- **Vercel**: https://flash-expense-tracker.vercel.app, root `frontend`,
  `VITE_API_URL` set. Shows "Backend online · v0.1.0".
- **CORS_ORIGINS** on Render:
  `http://localhost:5173,https://flash-expense-tracker.vercel.app`
  (comma-separated, no trailing slashes).
- **cron-job.org**: time zone Asia/Kolkata. "Flash wake-up" `GET /health` at
  03:27 and 03:28 (failure alerts off). "Flash DB heartbeat" `GET /health/db`
  with `X-Ping-Token` header at 03:30 (failure + disabled alerts on). Test run
  200 in 412 ms; `last_seen` updated to 06:11:56 UTC (11:41:56 IST).
- **Status**: Phase 0 deploy done. Remaining: overnight cron check, then the
  redaction run.

### 2026-11-13: Phase 0 closeout addendum

- Real data moved out of the repo to `D:\FlashPrivate\`; script paths are
  required flags. Default-deny redaction with keep-list and HMAC fakes.
- `/health/db` uses the `X-Ping-Token` header; migrations in Render's build.
- Deny rules for `.env` and `D:\FlashPrivate\`; exact frontend pins.

### 2026-11-13: Phase 0 closeout

- Repo pushed, CI green. Streaming redaction, `/health/db`, migration `0001`,
  click-by-click deploy guide.

### 2026-11-12: Phase 0 scaffold

- Scaffolded backend, frontend, scripts, infra, docs, CI.
- Git practice: one branch per area, merged with `--no-ff`, branches deleted.
