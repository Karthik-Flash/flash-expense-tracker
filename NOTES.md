# Notes

Quick reference and progress log. Updated after every task.
Repo: https://github.com/Karthik-Flash/flash-expense-tracker (private)

## Status

Phase 0 (scaffold and walking skeleton): **done**. Deploying is your next step.

- [x] Monorepo, Python 3.12 venv, pinned deps, LF line endings
- [x] Backend: `/health`, `/health/db` (heartbeat write), first migration `0001`
- [x] Frontend: Vite React PWA, shows backend status, handles cold starts
- [x] `scripts/redact_sms.py`: streaming, pseudonymised names, fake refs
- [x] CI green on GitHub (ruff, pytest, typecheck, build)
- [x] Agent deny rules: `data/raw/`, `data/private/`, `*.xml` outside `mobile/`
- [x] Deploy guide: [infra/README.md](infra/README.md)
- [ ] You: deploy (Supabase, Render, Vercel, cron-job.org)
- [ ] You: run the redaction script and review the sample
- [ ] Phase 1: planner refines it in [docs/PLAN.md](docs/PLAN.md)

## Your to-do list

1. Generate `PING_TOKEN` (command below). Save it in your password manager.
2. Deploy with [infra/README.md](infra/README.md), sections 1 to 4, in order:
   Supabase, Render, Vercel, cron-job.org.
3. Run `--list-senders`, grow the allowlist if needed, then make the sample.
4. Review `data/sample/redacted_sample.json` and `data/private/name_map.json`.
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

### Database migrations (from `backend/`)

```powershell
.\.venv\Scripts\alembic.exe upgrade head                                 # apply all migrations
.\.venv\Scripts\alembic.exe current                                      # show applied revision
.\.venv\Scripts\alembic.exe revision --autogenerate -m "what changed"    # new migration after a model change
```

Render runs `alembic upgrade head` automatically on every start.

### PING_TOKEN (64 hex characters)

```powershell
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString('x2') })
```

Test the deployed endpoint: open
`https://<service>.onrender.com/health/db?token=<PING_TOKEN>`. Expect `{"db":"ok",...}`.

### SMS redaction (you run these; agents never do)

```powershell
backend\.venv\Scripts\python.exe scripts\redact_sms.py --list-senders     # sender IDs + counts, no text
backend\.venv\Scripts\python.exe scripts\redact_sms.py --limit 50         # writes data/sample/redacted_sample.json
backend\.venv\Scripts\python.exe scripts\redact_sms.py --help
```

Merchant mistaken for a person? In `data/private/name_map.json` set its value to
the name itself, for example `"CHAI POINT": "CHAI POINT"`, then re-run.

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
git push                                          # push main
gh run list --limit 5                             # recent CI runs
gh run watch                                      # follow the latest run live
gh run view --log-failed                          # only the failing step logs
gh repo view --web                                # open the repo in the browser
```

For a branch you want reviewed: `git push -u origin feat/x`, then `gh pr create --fill`.

## Open items

1. Starlette warns `httpx` with `TestClient` is deprecated (suggests `httpx2`).
   Kept `httpx` until the replacement is verified (DECISIONS D-010).
2. `docs/PLAN.md` still lists `/health/db` under Phase 1. It shipped in
   Phase 0; the planner should move it.
3. Phase 1 schema: confirm the dedupe key recipe before the next migration.
4. Name pseudonymisation is a heuristic. Expect a few merchants marked as
   people on first run; fix them in `name_map.json`.
5. Replace the placeholder PWA icons before launch.

## Log

### 2026-11-13: Phase 0 closeout

- Agent deny rules extended and tested with probe files (root and `scripts/`
  XML blocked, `mobile/` XML readable). `git status --ignored`: only
  `data/README.md` tracked under `data/`, no XML tracked.
- Repo created and pushed with `gh`; CI green on the first run.
- `redact_sms.py` hardened: streams with flat memory (0.2 MB peak on a 2.6 MB
  test file vs 11 MB for a full parse); fixes emoji char refs that would crash
  XML parsing; skips MMS; prefix/suffix-agnostic sender match; drops `-P`;
  pseudonymises P2P names; stable fake refs; `--list-senders`; summary.
  17 synthetic tests.
- `/health/db` + `heartbeat` table + migration `0001`. 401 bad token, 503 DB
  down (5 s connect timeout), `/health` unaffected. 6 backend tests.
- Deploy guide rewritten as click-by-click steps. Decisions D-010 to D-014.

### 2026-11-12: Phase 0 scaffold

- Scaffolded backend, frontend, scripts, infra, docs, CI.
- Git practice: one branch per area, merged with `--no-ff`, branches deleted.
