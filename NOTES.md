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

Phase 0 (scaffold, closeout, deploy): **deployed and verified**.
Phase 1, prompts 1, 1b, 1c, 2, 3 (HDFC survey, redaction fixes, leak check,
HDFC parser engine, full-data gaps): **done**. Next: re-run the redaction and
full-data coverage once (to-do list), then Phase 2.

- [x] Monorepo, Python 3.12 venv, exact pins, lockfile, LF endings, CI green
- [x] Backend `/health`, `/health/db` (`X-Ping-Token`), migration `0001`
- [x] Frontend PWA showing backend status, handles cold starts
- [x] `scripts/redact_sms.py`: default-deny, keep-list, HMAC fakes
- [x] Agent deny rules: `D:\FlashPrivate\`, every `.env`, `*.xml` outside `mobile/`
- [x] Supabase, Render, Vercel, cron-job.org set up and tested (13 Nov 2026)
- [ ] Overnight cron check: after 03:30 IST, confirm `heartbeat.last_seen` moved
- [x] Redaction run on the real backup; `data/sample/redacted_sample.json` exists
- [x] HDFC template survey: 15 shapes, all 135 HDFC messages matched
      ([docs/templates/hdfc.md](docs/templates/hdfc.md)), 49 fake fixtures
- [x] All 10 open questions resolved (hdfc.md "Resolved", DECISIONS D-028 to D-037)
- [x] Redaction fixes: hyphenated sender IDs, `BANK_VOCABULARY`, link paths
- [x] `always_redact.txt` final pass and `--verify` leak check
- [x] Sample refreshed with `--verify` (Leaks: 0) and re-surveyed
- [x] HDFC parser engine `backend/app/engine/` ([docs/engine.md](docs/engine.md)):
      14 templates seen in the sample + 13 expected forms; all 135 HDFC
      sample messages handled (131 parsed, 4 foreign currency deferred)
- [x] Full-data coverage (764 HDFC): 683 parsed, 44 foreign, 37 no_template
- [x] Gaps closed (`hdfc-1.1.0`): templates H16-H21, `H_INFO` fallback for
      amount-free notices, redaction of Mandate/SI Hub IDs and payee names
- [ ] Re-run redaction and full-data coverage with the new rules (to-do list)

## Your to-do list

1. If not done yet: check cron-job.org history for a 200 around 03:30 IST and
   that `heartbeat.last_seen` moved.
2. Redaction rules changed (Mandate/SI Hub IDs, payee names), so refresh
   both files: the STANDARD sample command under "SMS redaction" and the two
   full-data commands under "Parser coverage". Each must end with
   `Leaks: 0`. Expected full-data result: 0 `no_template` (the 15 messages
   of the six new shapes parse; the remaining notices become `H_INFO`).
   Paste the coverage output into the chat (counts and shapes only).

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

# 2. Names and UPI IDs with counts (real values: read locally, NEVER paste into a chat)
backend\.venv\Scripts\python.exe scripts\redact_sms.py --input D:\FlashPrivate\raw --private-dir D:\FlashPrivate\private --list-counterparties

# 3. STANDARD sample command: write the sample, then check it for leaks
backend\.venv\Scripts\python.exe scripts\redact_sms.py --input D:\FlashPrivate\raw --private-dir D:\FlashPrivate\private --output data\sample\redacted_sample.json --limit 100 --seed 42 --verify

# Re-check an existing sample only
backend\.venv\Scripts\python.exe scripts\redact_sms.py --private-dir D:\FlashPrivate\private --output data\sample\redacted_sample.json --verify
```

- Step 3 must end with `Leaks: 0` (exit code 0) before the sample is shared.
  `--verify` prints only tokens and message numbers
  (`LEAK PARTY_014 in message 37`), never real values.
- `D:\FlashPrivate\private\always_redact.txt`: one entry per line (own name
  variants, family names, own phone). Replaced everywhere in a final pass;
  checked by `--verify` as substrings. Add any leaked name here and re-run.
- `--list-senders` groups IDs by normalised core (`VKSBIBNK`, `VM-SBIBNK-S`
  -> `SBIBNK`); `VARIANTS` = raw IDs merged. Allowlist = banks and UPI only
  (`DEFAULT_SENDERS`, 14 cores). Add a bank by its core.
- Keep a public brand: add it to `scripts\keep_names.txt` (committed).
- Keep something private: add it to `D:\FlashPrivate\private\keep_names.txt`.
- Back up `D:\FlashPrivate\private\` (`redaction.key`, `name_map.json`,
  `seen_ids.json`, your keep and always-redact lists).

### Parser coverage (counts and shapes only, safe to paste)

```powershell
# On the 288-message sample
backend\.venv\Scripts\python.exe scripts\parse_coverage.py --input data\sample\redacted_sample.json

# On the full data: redact everything (no --limit) into a separate file, check it, then measure
backend\.venv\Scripts\python.exe scripts\redact_sms.py --input D:\FlashPrivate\raw --private-dir D:\FlashPrivate\private --output data\sample\redacted_full.json --verify
backend\.venv\Scripts\python.exe scripts\parse_coverage.py --input data\sample\redacted_full.json
```

`redacted_full.json` stays in `data\sample\` (gitignored). Only run the
coverage step if the first command ends with `Leaks: 0`.

### Template survey (reads only the redacted sample)

```powershell
backend\.venv\Scripts\python.exe scripts\shape_survey.py --input data\sample\redacted_sample.json --senders HDFCBK,HDFCBN --output data\sample\hdfc_shapes.json
```

Output stays in `data\sample\` (gitignored). Same command for other banks with
their sender cores. Fixtures for parsers: `backend\tests\fixtures\sms\<bank>.json`
(fake values only; checked by `backend\tests\test_sms_fixtures.py`).

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
6. Bank vocabulary covers HDFC wording only. Each new bank's survey should add
   its fixed phrases to `BANK_VOCABULARY` in `scripts/redact_sms.py`.

## Log

### 2026-11-14: Phase 1 prompt 3, full-data gaps

- Full-data coverage (your run, 764 HDFC messages): 683 parsed, 44 foreign
  currency deferred, 37 no_template.
- `hdfc-1.1.0`: H16 NEFT debit, H17 UPI AutoPay debit (`autopay`), H18 card
  AutoPay set up, H19 UPI mandate cancelled (`mandate_cancelled`), H20 FD
  closure notice (`fd_closure`), H21 MF order (`mf_order`). `parse_date`
  also takes yyyy-mm-dd.
- `H_INFO` fallback: no template and no amount gives `other_info`; with an
  amount it stays `no_template` (DECISIONS D-044).
- Redaction: IDs after `Mandate ID:` / `SI Hub ID:` get a same-shape fake
  regardless of digit count; the name after "added a payee" is a counterparty
  slot (D-045).
- 10 new fake fixtures (49 in total). Sample coverage unchanged (131 parsed).

### 2026-11-14: Phase 1 prompt 2, HDFC parser engine

- Re-survey of the refreshed sample: same 135 messages and 15 shapes. H03,
  H11, H12 now show the real card label (new shape ids); H09's word slot is
  still mapped by the private name map (harmless; template accepts any word).
- `backend/app/engine/`: `senders`, `money` (Decimal to paise), `timeparse`
  (fixed IST offset), `models` (`ParsedMessage`, `Unknown`), `parsers/base`
  and `parsers/hdfc` (`hdfc-1.0.0`). Stdlib only, no FastAPI/SQLAlchemy/config.
- All 39 fixtures parse to exactly their expected fields; each matches exactly
  one template. Shared sender-ID table runs against both implementations.
- `scripts/parse_coverage.py`: counts and Unknown shapes only. Sample: 288
  messages, 131 parsed (127 money), 4 foreign deferred, 153 banks without a
  parser, 0 no_template, 0 ambiguous.
- Docs: `docs/engine.md`; DECISIONS D-041 to D-043.

### 2026-11-14: Phase 1 prompt 1c, always-redact list and --verify

- Your manual check found your first name once in the sample, so the script
  now checks itself.
- `always_redact.txt` in the private folder: every whole-word occurrence is
  replaced in a final pass (same name map and tokens; phones get the usual
  fake). Entries are never printed.
- `--verify` (after writing, or alone on an existing sample): always-redact
  entries as substrings, 2+ word map names, and real UPI IDs/references by
  keyed digest (`seen_ids.json`; real values are not stored). Prints tokens
  and message numbers only; exit 1 on any leak (D-040).
- One standard sample command (`--limit 100 --seed 42 --verify`); older
  variants removed. 54 script tests.

### 2026-11-14: Phase 1 prompt 1b, redaction fixes and resolved questions

- Sender IDs with hyphens are split on hyphens (prefix, core, S/T/P/G
  suffix); length rules only for IDs without hyphens. `AB-ABCDE-P` is now
  core `ABCDE`, promo (D-038).
- `BANK_VOCABULARY` (29 phrases) is never pseudonymised; stale name-map
  entries made of bank wording are ignored; links keep scheme and host and
  get a same-length fake path (D-039). 50 script tests.
- Your answers recorded: hdfc.md "Resolved" and DECISIONS D-028 to D-037.
  New type `upcoming_debit`; FD closure is `credit`/`fd`; money types always
  have `txn_time_utc` (from `received_at` with `time_inferred: true` when the
  SMS has no time). Fixtures and their test updated.
- Correction: the fixture file has 39 fixtures (25 observed + 14 not yet
  seen); the previous entry said 38.

### 2026-11-14: Phase 1 prompt 1, HDFC template survey

- `scripts/shape_survey.py`: turns messages into placeholder shapes and
  groups them (stdlib, reusable per bank). 7 synthetic tests.
- HDFCBK + HDFCBN: 135 messages, 15 shapes, all matched. Types: debit 7
  shapes / 103 messages, credit 1/22, refund 1/1, mandate 2/2,
  foreign_currency 1/4, other_info 3/3.
- `docs/templates/hdfc.md`: shapes, proposed types, fields, 10 open
  questions, 14 "not yet seen" formats.
- `backend/tests/fixtures/sms/hdfc.json`: 39 fake fixtures (25 observed
  shapes + 14 not yet seen), checked by `test_sms_fixtures.py`.
- Leak scan before commit: no sample digits/VPAs/amounts/tokens below 900 in
  committed files (method in DECISIONS D-027).

### 2026-11-14: Sender ID normalisation and allowlist

- Your `--list-senders` run showed one bank under many IDs (no-hyphen
  prefixes like `VKSBIBNK`, 9-char forms like `JXSBIINBS`). Every ID is now
  reduced to its core before matching, counting and promo detection
  (rules: DECISIONS D-025). Promo suffix P is dropped with or without hyphens.
  `...@RBM.GOOG` IDs are never allowlisted.
- `--list-senders` adds a `VARIANTS` column.
- Default allowlist is now 14 bank/UPI cores (D-026, data minimisation).
- Commands unchanged. Re-run `--list-senders` to check the grouping, then
  continue with `--list-counterparties`. 28 script tests.

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
