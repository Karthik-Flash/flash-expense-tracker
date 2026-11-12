# Notes

Quick reference and progress log. Updated after every task.
Repo: https://github.com/Karthik-Flash/flash-expense-tracker (private)

## Status

Phase 0 (scaffold, walking skeleton, closeout): **done**. Deploying is your next step.

- [x] Monorepo, Python 3.12 venv, exact pins everywhere, lockfile, LF endings
- [x] Backend: `/health`; `/health/db` with `X-Ping-Token` header; migration `0001`
- [x] `DATABASE_URL` normalised to psycopg; small pool (2 + 2), 5 s connect timeout
- [x] Migrations run in Render's build step; start command only starts uvicorn
- [x] Frontend: Vite React PWA, shows backend status, handles cold starts
- [x] `scripts/redact_sms.py`: default-deny, keep-list, HMAC fakes, required paths
- [x] Real data outside the repo: `D:\FlashPrivate\` (agent-blocked)
- [x] Agent deny rules: `D:\FlashPrivate\`, every `.env`, `*.xml` outside `mobile/`
- [x] CI green: ruff, backend + scripts pytest, typecheck, build
- [x] Deploy guide: [infra/README.md](infra/README.md)
- [ ] You: deploy (Supabase, Render, Vercel, cron-job.org)
- [ ] You: run the redaction script and review the sample
- [ ] Phase 1: planner refines it in [docs/PLAN.md](docs/PLAN.md)

## Your to-do list

1. Generate `PING_TOKEN` (command below). Save it in your password manager.
2. Deploy with [infra/README.md](infra/README.md), sections 1 to 4, in order:
   Supabase, Render, Vercel, cron-job.org (the DB job sends the `X-Ping-Token` header).
3. Redaction: `--list-senders`, then `--list-counterparties`, then the real run
   (commands below). Grow the keep-lists between runs if needed.
4. Skim `data\sample\redacted_sample.json`.
5. Tell me the sample exists. Only then can parsing work start (Phase 2).

## Cheat sheet

All commands run from the repo root in PowerShell unless noted.

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
.\.venv\Scripts\alembic.exe upgrade head                                 # apply all migrations
.\.venv\Scripts\alembic.exe current                                      # show applied revision
.\.venv\Scripts\alembic.exe revision --autogenerate -m "what changed"    # new migration after a model change
```

On Render, the build command runs `alembic upgrade head` once per deploy.

### PING_TOKEN

```powershell
# Generate (64 hex characters)
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString('x2') })

# Test the deployed endpoint (paste the token when asked)
$t = Read-Host "PING_TOKEN"
Invoke-RestMethod https://<service>.onrender.com/health/db -Headers @{ "X-Ping-Token" = $t }
```

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
- Back up `D:\FlashPrivate\private\redaction.key` and `name_map.json`. Losing
  them changes every fake on the next run.

### Git: daily loop

```powershell
git switch main; git pull                         # start from latest main
git switch -c feat/short-name                     # new branch (same as checkout -b)
git add -p                                        # stage piece by piece
git commit -m "feat(scope): what and why"
git switch main; git merge --no-ff feat/short-name
git branch -d feat/short-name
git push                                          # CI runs on every push to main
git log --oneline --graph -15                     # recent history
```

### Push and CI

```powershell
gh run list --limit 5                             # recent CI runs
gh run watch                                      # follow the latest run live
gh run view --log-failed                          # only the failing step logs
gh repo view --web                                # open the repo in the browser
```

For a branch you want reviewed: `git push -u origin feat/x`, then `gh pr create --fill`.

## Open items

1. Starlette warns `httpx` with `TestClient` is deprecated (suggests `httpx2`).
   Kept `httpx` until the replacement is verified (DECISIONS D-010).
2. Phase 1 schema: confirm the dedupe key recipe before the next migration.
3. Name detection covers the usual bank positions (to/from/by/at,
   `UPI/P2P/.../NAME`, `; NAME credited`, `Dear NAME`). A name elsewhere is
   not detected; skim the sample.
4. Replace the placeholder PWA icons before launch (UI spec: Phase 3, D-020).

## Log

### 2026-11-13: Phase 0 closeout addendum

- Real data moved out of the repo to `D:\FlashPrivate\`; script paths are now
  required flags with no defaults.
- Redaction is default-deny: every counterparty name and UPI ID local part is
  pseudonymised unless keep-listed; same-shape fakes via HMAC-SHA256 with a
  random key; `--list-counterparties`. 18 synthetic tests.
- `/health/db`: `X-Ping-Token` header, 503 when unset, DB-side timestamp.
  `DATABASE_URL` normalisation. 12 backend tests.
- Migrations moved to Render's build step. cron-job.org DB job sends the header.
- Deny rules for `.env` (anywhere) and `D:\FlashPrivate\`, verified with probe
  files. Frontend pins made exact, `save-exact` on.
- Decisions D-015 to D-020; PLAN shows `/health/db` done in Phase 0.

### 2026-11-13: Phase 0 closeout

- Repo pushed, CI green. Streaming redaction, `/health/db`, migration `0001`,
  click-by-click deploy guide, decisions D-010 to D-014.

### 2026-11-12: Phase 0 scaffold

- Scaffolded backend, frontend, scripts, infra, docs, CI.
- Git practice: one branch per area, merged with `--no-ff`, branches deleted.
