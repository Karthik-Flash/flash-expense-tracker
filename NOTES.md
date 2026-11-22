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

**Phase 0-2 complete** (12-14 Nov 2026): scaffold and deploy, redaction,
HDFC parser engine, schema, import pipeline, dedupe, reparse. Real data is in
Supabase (917 messages, 678 transactions). Tags `phase-0-done`,
`phase-1-done`, `phase-2-done`. **Phase 3 done** (18 Nov 2026). **Phase 4 in
progress**: 4C (install and update prompt), 4B-1 (phone copy) and 4B-2
(offline queue) done 19 Nov; 4B-3 (offline boot), 4E (people, faster
To-do, logo options) and 4F-A (generic parser for other banks, payback
audit, refresh after deploy, logo C2) done 20 Nov; 4F-B (the CORS fix for
blocked taps, a queue that cannot get stuck, SBI parser), 4H (history
without AI attribution, person sheet actions, payback-audit any-answer rule
and `--restore`, polish pass) and 4A (statement check, own-account
transfers, statement names) and 4Z (statement reader 1.1.0 and import,
It's me and Investments, categories from names, Phase 4 retro) done 21 Nov.
**Phase 4 is done** ([docs/retro/phase-4.md](docs/retro/phase-4.md)).
**Phase 5A done 22 Nov** (not pushed): Flash on Android, bank SMS read on the
phone and uploaded in the background (devices and device tokens, bank-only
ingest, the Capacitor shell, the Kotlin SMS plugin, HDFC `hdfc-1.2.0`;
[docs/design/phase-5a-android.md](docs/design/phase-5a-android.md)). Next:
the owner's install on the phone (cheat sheet, "Android app"), then 5B.
**Phase 5C done 22 Nov** (not pushed): several users (invite codes,
`app_users`, sign-up, isolation test, Delete my account, first run, "What
Flash stores"); owner steps in the cheat sheet, "Several users".
**Phase 5B-1 done 22 Nov** (not pushed): daily-use correctness: To-do newest
first, refresh at once and every 60 s with pull-to-refresh, People only when
clearly personal (`categorise-1.3.0`), payback guesses need an earlier
payment and payback links (`reconcile-1.7.0`), Invested totals and "Count
investments in Spent" (migration `0016`), `category-diff` and
`payback-review` (D-133 to D-138). Owner steps: cheat sheet, "After the 5B-1
deploy". **Phase 5B-2 done 23 Nov** (not pushed): the phone uploads a new bank SMS
at once, keeps its place across sign-out, notifies new payments, and shows a status
screen with an event log; a 304 snapshot without building it (D-139 to D-144;
[docs/design/phase-5b2-phone.md](docs/design/phase-5b2-phone.md)). Owner steps and
the phone test plan: cheat sheet, "After the 5B-2 deploy". **5F part 1 done 23 Nov**
(not pushed): an Insights tab with Export (CSV and Excel), Profile and Admin (D-146);
Analytics and "Learn from the owner" still to come.
**Premium run, 23 Nov** (not pushed): part A pre-push safety (admin privacy test, Profile
facts, duplicate checks, export range tests, a cross-origin check that waits for the page;
D-147); part B Analytics at the top of Insights (D-148); part C rules and per-credit
Paid back answers (migration 0018, D-149); part D robustness (last X-Forwarded-For hop,
input limits, `doctor`, emoji copies of one SMS, snapshot reads once; D-150); part E
visual audit fixes at 360 and 1280 px (D-151); part F first-run checklist and About
(D-152).
History was rewritten on 21 Nov to drop AI attribution lines (D-109):
`main` before 4H is `c216442` (was `076ee9f`); old SHAs in older notes map
through [docs/history-rewrite-20261121.md](docs/history-rewrite-20261121.md).
A one-page tour:
[docs/OVERVIEW.md](docs/OVERVIEW.md).
New session? Start with [docs/HANDOFF.md](docs/HANDOFF.md).

- [x] Monorepo, Python 3.12 venv, exact pins, lockfile, LF endings, CI green
- [x] Backend `/health`, `/health/db` (`X-Ping-Token`), migration `0001`
- [x] Frontend PWA showing backend status, handles cold starts
- [x] `scripts/redact_sms.py`: default-deny, keep-list, HMAC fakes
- [x] Agent deny rules: `D:\FlashPrivate\`, every `.env`, `*.xml` outside `mobile/`
- [x] Supabase, Render, Vercel, cron-job.org set up and tested (13 Nov 2026)
- [x] Overnight check of the Render heartbeat (15 Nov): fails every night
      ("output too large"); replaced by the Data API ping (D-053)
- [x] Migration `0003`: `keepalive.ping()` for the Data API, RLS on `heartbeat`
- [x] Keep-alive switch-over verified (15 Nov): security check 8/8 blocked
      (public 406, keepalive 404), cron test run 200, `last_seen` moved
- [x] Overnight check of the new keep-alive (16 Nov 03:30 IST run returned 200)
- [x] Phase 3A-1: PLAN aligned with Phase 3 (D-054), spend definition (D-055)
- [x] Phase 3A: one-page UI design spec and clickable mockup, approved by you
- [x] Phase 3B-1: merchant engine `merchant-1.0.0` and `merchant-stats` (D-057)
- [x] Phase 3B-2: `merchant-1.1.0` (D-058), wider survey, `merchant-review`
- [x] Phase 3B: your `merchant-stats` run on the real data (counts only),
      and your own look with `merchant-review` (never pasted)
- [x] Phase 3C-1: design of the derived-data backbone and Reconcile
      ([docs/design/phase-3-backbone.md](docs/design/phase-3-backbone.md));
      approved 15 Nov with the planner's answers (D-059 to D-067)
- [x] Phase 3C-2: decisions recorded; `merchant-1.1.1` (D-068); roles in
      memory (`reconcile-1.0.0`, [docs/engine.md](docs/engine.md)) and
      `reconcile-stats`
- [x] Phase 3C-3 and 3C-5: duplicates and pair linking in memory
      (`reconcile-1.1.0`); `reconcile-stats` shows links, candidates and the
      existing candidates
- [x] Your `reconcile-stats` run on the real data (counts only, safe to
      paste). It answers: how many of the 18 pairs link, the AutoPay +
      card time gaps, and which message carries the brand
- [ ] Private look at the merged refund's two source messages (cheat sheet,
      "Merged refund"); tell the planner "one event" or "two events" only
- [x] Phase 3C-4 and 3C-6: `reconcile-1.2.0` (D-069), owner tables and
      `owner-load` (migration `0004`, D-070), derived tables and `recompute`
      (`0005`)
- [x] After the push: your owner file, `owner-load`, `recompute`,
      `reconcile-stats` on the real data (to-do list)
- [x] Phase 3C-7, 3C-8: `reconcile-review`, `owner-export`, `totals`;
      `reconcile-1.2.1` (D-072), duplicate primary (D-071)
- [ ] The card bill pair rule, when credit card SMS appear
- [x] Phase 3E: login, `/api/v1`, confirmed-only paybacks, inferred own
      accounts (D-075 to D-078)
- [x] Render: add `SUPABASE_URL` and `AUTH_USERS`, then the smoke test
- [x] Phase 3F-1: every screen on demo data ([docs/ui-spec.md](docs/ui-spec.md))
- [x] Phase 3F-2: URL state and Back by layers, icons, design pass, logo
      options
- [x] Phase 3F-3: API gaps closed (D-079), real login and data (D-080),
      category colours, ring chart, FLA$H logo and icons (D-081 to D-083),
      `scripts/backup_db.ps1` (D-084)
- [x] Vercel: set `VITE_API_URL`, `VITE_SUPABASE_URL`,
      `VITE_SUPABASE_PUBLISHABLE_KEY`; Supabase Auth settings and Render
      `SUPABASE_URL`, `AUTH_USERS` (infra/README.md section 5)
- [x] Your look at the app on your phone after the deploy (login and saving
      verified)
- [x] Your first backup (cheat sheet, "Back up and restore")
- [ ] Bank statement check, one normal and one messy month: carried from
      Phase 3 to Phase 4 as 4A (docs/PLAN.md)
- [x] Phase 3D: `categorise-1.0.0`, migration `0006`, `category-stats`,
      `category-review`, labels (D-073, D-074)
- [x] Your `category-stats` run (safe to paste) and `category-review`
      (private) on the real data
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
- [x] Full data on `hdfc-1.1.1`: 764 HDFC messages, 720 parsed, 44 foreign,
      0 no_template (from the real import)
- [x] Phase 2 Part A: migration `0002` (6 tables, RLS on Postgres), importer,
      dedupe, reparse, `python -m app.cli` ([docs/data-model.md](docs/data-model.md));
      invariants I1-I9 tested on SQLite and Postgres 17 in CI
- [x] Real import on Supabase (14 Nov): 917 raw, 678 transactions,
      re-import 0 new, reparse dry run 0

## Your to-do list

1. If `data\sample\redacted_full.json` exists from an earlier run, delete it.
   The full file now lives in `D:\FlashPrivate\private\` (D-051).
2. When the owner file changes (cheat sheet, "Owner data and recompute"):
   edit `D:\FlashPrivate\private\owner.json` (shape in
   `docs\owner.example.json`), check that `alembic current` says `0010`,
   run `owner-load`, then paste the `reconcile-stats` output.
3. Vercel: `VITE_API_URL` is saved as a Secret. Change it to a plain
   variable with the same value, then redeploy with the build cache off.
4. After the 4C deploy: close the app on the phone completely once (swipe it
   out of recent apps) and open it again; check the version line (cheat
   sheet, "Which build is on the phone").
5. Optional: refresh the sample with the newer redaction rules (STANDARD
   sample command under "SMS redaction"; must end with `Leaks: 0`).

## Architecture

### The pieces and how they connect

```
                          you (browser / phone)
                                   |
                                   | 1. HTTPS: load the app
                                   v
  +-----------------------------------------------------+
  | Vercel  (global CDN)                                |
  | https://flash-expense-tracker.vercel.app            |
  | Static PWA built from frontend/                     |
  | VITE_API_URL, VITE_SUPABASE_URL and                 |
  | VITE_SUPABASE_PUBLISHABLE_KEY baked in at build     |
  +-----------------------------------------------------+
                                   |
                                   | 2. fetch(VITE_API_URL + "/api/v1/...")
                                   |    with the Supabase Auth token,
                                   |    from your browser, cross-origin
                                   v
  +-----------------------------------------------------+
  | Render  (Free web service, Singapore)               |
  | https://flash-expense-tracker.onrender.com          |
  | Cloudflare edge -> uvicorn -> FastAPI (backend/)    |
  | Env: DATABASE_URL, PING_TOKEN, CORS_ORIGINS,        |
  |      SUPABASE_URL, AUTH_USERS, PYTHON_VERSION       |
  | Sleeps after 15 min idle; cold start ~50 s          |
  | Not kept awake (D-112): the phone copy covers it    |
  |                                                     |
  +-----------------------------------------------------+
                                   |
                                   | 3. Postgres over TLS (sslmode=require)
                                   |    via Supabase Session pooler, port 5432
                                   v
  +-----------------------------------------------------+        4. POST /rest/v1/rpc/ping (Data API)
  | Supabase  (Free Postgres, Singapore)                | <-----    apikey + Content-Profile: keepalive
  | heartbeat, alembic_version, import_batches,         |        +--------------------------------+
  | raw_messages, parse_results, transactions,          |        | cron-job.org                   |
  | transaction_sources, duplicate_candidates           |        | "Flash DB heartbeat"           |
  | owner: own_accounts, own_identifiers, parties,      |        | daily 03:30 IST                |
  |   party_texts, owner_link_decisions, owner_roles,   |        | alerts: fails, disabled        |
  |   owner_categories, labels, txn_labels              |        +--------------------------------+
  | derived: derive_runs, txn_derived, txn_links        |
  | schema keepalive: ping() (SECURITY DEFINER)         |
  | RLS on every app table                              |
  | Data API on: exposes schema keepalive ONLY          |
  | Auth: the owner's login (email, sign-ups off)       |
  | Pauses after 7 days idle (warning email first)      |
  +-----------------------------------------------------+
         ^
         | 5. python -m app.cli import-sms | reparse | stats
         |    (your PC, Postgres via backend\.env)

  +-----------------------------------------------------+
  | GitHub  Karthik-Flash/flash-expense-tracker         |
  | push to main -> GitHub Actions CI (3 jobs)          |
  |              -> Render deploys after CI passes      |
  |              -> Vercel auto-deploy (frontend/)      |
  +-----------------------------------------------------+
```

### Flow 1: you open the app

1. The phone opens `https://flash-expense-tracker.vercel.app` (or the
   installed app). The service worker serves the app shell from its cache;
   otherwise Vercel serves it from its CDN. Render is not involved yet.
2. Signed out: the login screen. `@supabase/supabase-js` signs in with email
   and password against Supabase Auth and keeps the session in
   localStorage, refreshing the token itself (D-080). At launch the app
   reads who is signed in from that stored session, without the network,
   and shows the phone copy at once; the refresh runs behind it (D-095).
3. Signed in: Home asks `GET /api/v1/summary?month=...` and the month's
   transactions from `VITE_API_URL` (baked in when Vercel last built the
   frontend), with `Authorization: Bearer <access token>`.
4. Render checks the token against Supabase's keys (ES256, JWKS) and maps the
   user to the owner (`AUTH_USERS`, D-078), then reads Postgres. If the
   service is asleep, Render holds the request while it boots (~50 s); after
   3 s the page shows "Starting up, this can take about a minute".
5. Because the page's origin is in `CORS_ORIGINS`, the browser lets it read
   the answer. Home shows Net, Spent, Paid back and the categories. A 401
   keeps the screen and shows "Sign in to sync" (D-095); a 403 shows "This
   account has no access" (D-080).

### Flow 2: nightly keep-alive (all times IST, D-053)

1. 03:30: cron-job.org job "Flash DB heartbeat" sends
   `POST https://<ref>.supabase.co/rest/v1/rpc/ping` with headers `apikey`
   (the publishable key), `Content-Profile: keepalive`,
   `Content-Type: application/json` and body `{}`. Render is not involved.
2. Supabase's Data API maps the publishable key to the `anon` role. Only the
   `keepalive` schema is exposed, and `anon` may only execute
   `keepalive.ping()`.
3. `ping()` runs as its owner (SECURITY DEFINER) and upserts `heartbeat` row
   `id=1` with `last_seen = now()`. It returns `{"ok": true}` and nothing
   else.
4. Supabase records activity, so the free project does not pause.
5. Alerts: cron-job.org emails on a failed run and when it disables the job.
   Backstop: Supabase emails a pause warning before it pauses an idle
   project.
6. `/health/db` with `X-Ping-Token` still works, for manual checks only.

Until 15 Nov 2026 the job called Render's `/health/db` (D-052). Asleep,
Render served its browser loading page to cron-job.org ("output too large")
and never woke, so every run failed.

The API warm job ("Flash API warm 07-01 IST") is retired (21 Nov 2026,
D-112): its pings got 503 from a sleeping free Render service and never
woke it, and the phone copy (D-089, D-095) already covers a cold start.
Delete it in cron-job.org (owner step). The 03:30 IST Supabase heartbeat
above stays: it is the only thing that keeps Supabase from pausing.

### Flow 3: you push code

1. `git push` to `main` on GitHub.
2. GitHub Actions CI runs three jobs: backend (ruff, backend and scripts
   pytest on SQLite), backend on Postgres 17 (`alembic upgrade head`,
   `alembic check`, pytest), frontend (lint, typecheck, test, build).
3. Render waits for CI ("After CI Checks Pass", D-050). Then it runs
   `pip install -r requirements.txt && alembic upgrade head` (migrations hit
   Supabase during the build) and starts `uvicorn app.main:app`. If the
   build or migration fails, the old version keeps serving.
4. Vercel does not wait for CI: `npm install` and `npm run build` in
   `frontend/`, with the `VITE_*` values and the commit's build id baked
   in, then publish to the CDN. Phones get the new version through the
   update bar (D-085).
5. Check CI with `gh run watch`. Keep `main` green. Claude Code commits and
   merges locally and never pushes; the owner pushes after the planner
   reviews.

### Flow 4: real data to a shareable sample (you run it, agents never do)

1. Your phone's SMS Backup & Restore export sits in `D:\FlashPrivate\raw\`
   (outside the repo).
2. You run `scripts/redact_sms.py`. It reads the export, and keeps its key and
   name map in `D:\FlashPrivate\private\`.
3. It writes `data\sample\redacted_sample.json` (gitignored). Only this file
   is shared with agents and the planner.
4. Parsers are built and tested against that sample and fake fixtures.
   For full-data coverage, the full redacted file goes to
   `D:\FlashPrivate\private\` (D-051), never the repo.

### Flow 5: real data into the database (you run it, agents never do)

1. From `backend\` on your PC: `python -m app.cli import-sms --input
   D:\FlashPrivate\raw`. `DATABASE_URL` in `backend\.env` points at Supabase.
2. The importer streams the XML, keeps only bank-registry senders and never
   stores OTP, promotional or MMS messages.
3. Per message: `raw_messages` (dedupe on `content_hash`), engine parse,
   `parse_results`, then for money a `transactions` row (merged on its dedupe
   key) linked in `transaction_sources`, plus `duplicate_candidates` pairs.
4. It prints counts only. `reparse` after a parser version bump; `stats` for
   totals. Details: [docs/data-model.md](docs/data-model.md).

### Where each setting lives

Values are never written in git or chat. Keep them in your password manager.

| Setting        | Used by          | Lives in                                                  |
| -------------- | ---------------- | --------------------------------------------------------- |
| `DATABASE_URL` | Render, Alembic  | Render env; `backend/.env` for local; password manager   |
| `PING_TOKEN`   | `/health/db`     | Render env; password manager (manual checks only)         |
| Supabase publishable key | cron-job.org `apikey` header | cron-job.org job header; password manager. Never in git |
| `CORS_ORIGINS` | FastAPI CORS     | Render env: `http://localhost:5173,https://flash-expense-tracker.vercel.app,https://localhost` (the last one: the Android app, 5A) |
| `SUPABASE_URL` | FastAPI login check (JWKS, issuer) | Render env: `https://<ref>.supabase.co` |
| `AUTH_USERS`   | FastAPI login -> owner (seed and fallback since 5C, D-129) | Render env: `"<auth user id>:<owner_id>"`; password manager |
| `SUPABASE_SECRET_KEY` | Invites and Delete my account: the Auth Admin API (5C, D-128) | Render env only (`sb_secret_...`); password manager. Never in the frontend |
| `VITE_API_URL` | Frontend build   | Vercel env: `https://flash-expense-tracker.onrender.com`; `frontend/.env` for local |
| `VITE_SUPABASE_URL` | Frontend login | Vercel env: `https://<ref>.supabase.co`; `frontend/.env` for local |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Frontend login | Vercel env (safe in the browser); `frontend/.env` for local |
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
- `GET /` on Render returns 404 by design. Only `/health`, `/health/db` and
  `/api/v1/...` (login needed) exist.
- Run only one Vite dev server at a time. If it starts on port 5174, CORS
  blocks it because only 5173 is allowed.
- DB password: letters and digits only. `#` and `%` broke `DATABASE_URL`
  parsing.
- The Data API is on but exposes only the `keepalive` schema (D-053).
  Never add `public` to the exposed schemas: Supabase grants `anon` access
  to public tables by default, and RLS (no policies) is then the only guard.
  `alembic_version` has no RLS, so it would be readable.
- cron-job.org must POST, with `Content-Profile: keepalive`. Without the
  header the Data API looks in its default schema and answers 404 or 406.
  If `ping` answers 404 `PGRST202` right after the migration, the schema
  cache is stale: run `NOTIFY pgrst, 'reload schema';` in the SQL editor.
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
(Invoke-WebRequest "$u/health" -Method Head -UseBasicParsing).StatusCode  # 200, no body (D-098)
$t = Read-Host "PING_TOKEN"
Invoke-RestMethod "$u/health/db" -Headers @{ "X-Ping-Token" = $t }       # db ok + latency_ms
```

```powershell
# Security check: ping works, every public table is unreachable (Data API, D-053)
$ref = Read-Host "Supabase project ref"
$k = Read-Host "Publishable key"
$base = "https://$ref.supabase.co/rest/v1"
Invoke-RestMethod "$base/rpc/ping" -Method Post -ContentType "application/json" -Body "{}" -Headers @{ apikey = $k; "Content-Profile" = "keepalive" }   # ok : True
foreach ($p in "public", "keepalive") {
  foreach ($t in "heartbeat", "transactions", "raw_messages", "alembic_version") {
    try { Invoke-RestMethod "$base/$t" -Headers @{ apikey = $k; "Accept-Profile" = $p } | Out-Null; "LEAK: $p.$t answered" }
    catch { "blocked $p.$t (HTTP $($_.Exception.Response.StatusCode.value__))" }
  }
}
```

Every table line must say `blocked` (406 for `public`: schema not exposed;
404 for `keepalive`: no such table). Any `LEAK` line: switch the Data API
off, then fix the exposed schemas.

### Run the apps locally

```powershell
cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000   # terminal 1
cd frontend; npm run dev                                                             # terminal 2, http://localhost:5173
```

The frontend uses the real API and Supabase login from `frontend\.env`
(`VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`; see
`.env.example`). For fake data with no login, add `VITE_DEMO=1` to
`frontend\.env` (dev only; a build ignores it).

### Checks (same as CI)

```powershell
backend\.venv\Scripts\ruff.exe check . ; backend\.venv\Scripts\ruff.exe format --check .
cd backend; .\.venv\Scripts\python.exe -m pytest -q; cd ..
backend\.venv\Scripts\python.exe -m pytest -q scripts
cd frontend; npm run lint; npm run typecheck; npm test; npm run build; cd ..
```

### Phone copy and speed (4B-1)

- The app opens from its copy on the phone and refreshes in the
  background; the line under the month says how fresh it is ("Updated 5
  min ago", "Offline · showing data from …").
- Tap the version line on Home for the Speed sheet: the last launches,
  measured on the phone (targets: 2 s from the phone copy, 5 s for fresh
  data with the server awake). Paste only those numbers to the planner.
- Sign out deletes the copy. Another login never sees it.
- Check the snapshot by hand (needs a token, so normally the app does it):
  `curl -H "Authorization: Bearer <token>" -H "Accept: application/json"
  --compressed https://flash-expense-tracker.onrender.com/api/v1/sync/snapshot`
  never paste its output (real data).

### Offline taps: your check list after the 4B-2 deploy

Render runs migration `0007` on deploy (`alembic current` says `0007`).

1. Airplane mode on. Give one sender an answer in To-do and one payment a
   category. Each shows "Waiting to sync"; Home's totals do not move; the
   line under the month says "2 waiting to sync".
2. Close the app completely and open it again (still offline): both are
   still waiting.
3. Tap Sign out: the app warns "2 changes haven't synced yet"; choose "Stay
   signed in".
4. Airplane mode off. Within a few seconds the waiting count goes away, then
   the totals change. Open the Speed sheet (version line): Sync shows the
   last drain (2 sent).
5. Undo: offline, change one more category, tap Undo; nothing is sent.
6. Paste to the planner only: the counts from step 4 and the Speed sheet
   numbers. Never paste names or amounts.

### Offline launch: your check list after the 4B-3 deploy

1. Open the app online once and wait for "Updated just now". Then leave the
   phone for more than an hour (the access token lasts an hour), turn
   airplane mode on and open the app. Home shows within 2 s with "Offline ·
   showing data from …". Not a blank screen.
2. Still offline, tap a category for one payment: it shows "Waiting to
   sync". Turn airplane mode off: within a few seconds the waiting count
   goes away, then the totals change.
3. Sign out (choose "Sign out anyway" if asked), turn airplane mode on and
   open the app: the login shows "You're offline. Connect to sign in.", and
   Sign in answers that at once instead of spinning.
4. Open the Speed sheet (version line): Boot shows "local copy" and the time
   to the first screen in ms; Boot errors should be "None".
5. Paste to the planner only: the Boot path, the ms, the boot error count
   and whether any step showed a blank screen. Never paste names or amounts.

### People: your check list after the 4E deploy

Render runs migration `0008`. Then run `python -m app.cli recompute` once
(or make any change on the phone) so the new engine versions apply; until
then Home says "Totals are being updated".

1. To-do: on a sender card with a masked UPI ID, tap "Same as…" and pick the
   friend it belongs to. If both have different answers, the app asks which
   one stays. The card merges into the friend's; the People ledger shows
   one row for them.
2. Tap that row: the person sheet lists both identifiers. Tap "Name" and
   give a short name; it shows everywhere, with the UPI ID in small text.
3. Airplane mode: rename someone; it says "Waiting to sync". Airplane mode
   off: it syncs.
4. "See payments" on a card shows that person's payments across months;
   Back returns to To-do. On merchant cards, a chip sets "All from".
5. Separate one identifier in the sheet: it is on its own again.
6. Logo: done (C picked; C2 applied in 4F-A).
7. Paste to the planner only: counts (how many joins, whether any step
   failed). Never paste names or amounts.

### After the 4F-B deploy: your check (phone)

1. Open the app once the new build is live (close it fully first; the
   version line on Home shows the new build).
2. Within a minute the 22:42 Friend tap syncs: it says "Synced" for a moment
   and leaves "Saved on phone"; Home stops saying "Totals are being updated".
3. Speed sheet (tap the version line): the Sync block is at the top. Paste to
   the planner: Saved on phone, Failed, Last attempt (time and result code),
   Last success. They are counts, times and codes: safe to paste.
4. Make one tap with Airplane mode on, then turn it off: it syncs within a
   few seconds.

### Android app: build, install, update (5A, D-122 to D-127)

In this order. Steps 1 to 3 once; step 4 for every new version.

1. **Push** after the planner's review: `git push`. Render runs migration
   `0014` (`devices`) on deploy.
2. **Render env** (dashboard, service, Environment): `CORS_ORIGINS` gets
   `,https://localhost` at the end (exactly, no port), so the line reads
   `http://localhost:5173,https://flash-expense-tracker.vercel.app,https://localhost`.
   Save, rebuild and deploy.
3. **Reparse** so the 44 HDFC forex notices are read (`hdfc-1.2.0`; from
   `backend\`, counts only, SAFE TO PASTE):
   ```powershell
   .\.venv\Scripts\python.exe -m app.cli reparse --dry-run   # every HDFC message is reparsed; foreign_currency_deferred should drop by 44
   .\.venv\Scripts\python.exe -m app.cli reparse
   .\.venv\Scripts\python.exe -m app.cli stats
   ```
4. **Build the APK** (from `frontend\`). It needs the Supabase sign-in
   settings: put `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` (the
   same values as on Vercel) in `frontend\.env`; the build stops without
   them. The API address is built in (the Render URL).
   ```powershell
   cd frontend; npm ci; npm run android:apk      # prints APK: ...\mobile\android\app\build\outputs\apk\debug\app-debug.apk
   ```
5. **Install over USB** (phone: Settings > About phone > tap Build number 7
   times; Developer options > USB debugging on; plug in, allow this computer):
   ```powershell
   adb devices                                   # the phone listed as "device"
   adb install -r D:\Projects\FinancesApp\mobile\android\app\build\outputs\apk\debug\app-debug.apk
   ```
   The same command installs a newer APK over the old one (data kept). The
   APK is signed with this laptop's debug key
   (`%USERPROFILE%\.android\debug.keystore`): keep it; another key means
   uninstall and install again (the phone's queue and token go).
6. **First run on the phone**: open Flash, sign in. Home says "Read bank SMS
   on this phone · Set up": tap it, then "Allow SMS access".
   - If Android says "Restricted setting" (or nothing happens): "Open App
     info", ⋮ (top right) > Allow restricted settings, then Permissions >
     SMS > Allow; back in Flash, "Check again".
   - The phone connects by itself (needs a connection). Pick the period:
     "From your newest message on the server" (the default), or 3, 6 or 12
     months; "Start reading".
   - Battery: when the sheet shows the battery card, "Open App info" >
     Battery > Unrestricted (Samsung).
7. **Pass looks like**: in Bank SMS (or the Speed sheet's Bank SMS block)
   "SMS permission allowed", "This phone connected", "Waiting on phone 0"
   within a few minutes, "Last upload <time>, N new", "Last error –". Home
   shows payments after 14 Nov. Then pay something small by UPI with the app
   open: it shows within a minute. Paste to the planner only the Bank SMS
   rows (codes, counts, times) and `stats`; never names or amounts.

Revoke a lost phone: Bank SMS sheet (any device, also the laptop browser),
Phones, Revoke. Signing out on the phone revokes it and wipes its token and
queue. Kotlin checks (from `mobile\android\`): `.\gradlew.bat
testDebugUnitTest`; on a connected phone only: `.\gradlew.bat
connectedDebugAndroidTest`.

### Several users: invites, testers, deleting an account (5C, D-128 to D-132)

After the planner's review, in this order:

1. **Push**: `git push`. Render runs migration `0015` (`app_users`,
   `invites`, `auth_deletions`).
2. **Render env** (dashboard, service, Environment): add
   `SUPABASE_SECRET_KEY` = the project's secret key (Supabase dashboard,
   Project Settings > API Keys, "Secret keys", `sb_secret_...`; create one if
   there is none). Server only: never in Vercel, `frontend\.env`, a chat or a
   file in git. Save, rebuild and deploy. Keep `AUTH_USERS` as it is for now.
3. **Become the admin**: open the app once (phone or laptop) and let it
   refresh. Your login is now the admin row of `app_users`. Check: ⋯
   (Settings) shows "People who use Flash" with you as admin.
4. Later, when everything works: you may remove `AUTH_USERS` from Render
   (it is only a fallback now). Not required.
5. **Invite a tester**: Settings > People who use Flash > New invite; send the
   code (shown once) privately. On the sign-in screen the tester taps "Have an
   invite code?", enters email, password (8 or more) and the code. Revoke an
   unused code in the same sheet.
6. **Survey of HDFC sender codes** (from `backend\`, SAFE TO PASTE: codes and
   counts only):
   ```powershell
   .\.venv\Scripts\python.exe -m app.cli sender-survey --contains HDFC --input D:\FlashPrivate\raw
   ```
   A row with `registered NO` and debit or credit counts is a missing HDFC
   sender; paste it to the planner (nothing is added without the planner).
7. If a deleted account's login could not be removed (the server log says
   "login deletion pending"):
   `.\.venv\Scripts\python.exe -m app.cli auth-cleanup` (counts only).

Owner commands now work on one owner's data: `--owner <owner_id>` before the
command, else the admin, else `OWNER_ID`. For your own data nothing changes.

### After the 5B-2 deploy: paybacks again (reconcile-1.7.1, D-145)

From `backend\`, after the push (no parser changed, so no reparse: a recompute is enough;
counts only, SAFE TO PASTE; the CSV is PRIVATE):
```powershell
.\.venv\Scripts\python.exe -m app.cli recompute
.\.venv\Scripts\python.exe -m app.cli payback-review --out D:\FlashPrivate\review\payback-review.csv
```
Expect "paybacks linked to a payment: linked" above 0 when your masked senders match one
payee each, and some of the 14 unanswered credits to become engine suggestions (To confirm).
Paid back and Net do not move.

### After the 5B-2 deploy: the phone test plan (D-139 to D-144)

1. **Backup**, then **push** (Render runs migration `0017`: `raw_messages.origin`,
   `data_versions`).
2. **Build and install the APK** (from `frontend\`, with the real Supabase values in
   `frontend\.env` as for 5A): `npm run android:apk`, then
   `adb install -r D:\Projects\FinancesApp\mobile\android\app\build\outputs\apk\debug\app-debug.apk`.
   The queue and the cursor of the installed app are kept (the queue moves to version 2).
3. **Open Flash once** (it reschedules the hourly check). Settings > Bank SMS: allow
   notifications when asked. On Samsung: "App battery" > Unrestricted, and "Never auto
   sleeping apps" > add Flash. Never Force stop Flash (Android 15 then blocks it until you
   open it again).
4. **App open**: pay Rs 1 by UPI. Pass: a notification "Paid ₹1 to …" within a minute, and
   the payment in Transactions without touching anything. Tap the notification: its sheet
   opens.
5. **App closed** (swipe it away, screen off for 5 minutes): pay Rs 1 again. Pass: the
   notification comes, and the payment is on the web (laptop) within a few minutes.
6. **Same payee twice**: pay the same person Rs 1 twice. Pass: two payments.
7. **Sign out and in** on the phone with the same login. Pass: no Bank SMS setup; Bank SMS
   says "connected" after a moment; a new payment still arrives.
8. **Airplane mode**: pay nothing, turn airplane mode on for 2 minutes, off again; then
   Sync now. Pass: "Last problem: none" after it, "Waiting on phone 0".
9. If anything fails: Bank SMS > Events on this phone > **Copy diagnostics** and paste it to
   the planner (codes and counts only, no message text).

### After the 5B-1 deploy (D-133 to D-138), in this order

1. **Backup** (from the repo root, Docker running): `powershell -ExecutionPolicy
   Bypass -File scripts\backup_db.ps1` (a new file in `D:\FlashPrivate\backups`).
2. **Push** after the planner's review: `git push`. Render runs migration
   `0016` (`owner_settings`). The first read after the deploy recomputes once
   (D-102).
3. **Reparse**, about 10 minutes (from `backend\`; no parser changed, so it
   mostly runs the recompute with `reconcile-1.7.0` and `categorise-1.3.0`;
   counts only, SAFE TO PASTE):
   ```powershell
   .\.venv\Scripts\python.exe -m app.cli reparse --dry-run
   .\.venv\Scripts\python.exe -m app.cli reparse
   ```
4. **category-diff** (counts SAFE TO PASTE; the CSV is PRIVATE, never paste
   it; `--out` must be outside the repository):
   ```powershell
   .\.venv\Scripts\python.exe -m app.cli category-diff --out D:\FlashPrivate\review\category-diff.csv
   ```
5. **payback-review** (the same rules):
   ```powershell
   .\.venv\Scripts\python.exe -m app.cli payback-review --out D:\FlashPrivate\review\payback-review.csv
   ```
   For another user's data put `--owner <owner_id>` before the command:
   `.\.venv\Scripts\python.exe -m app.cli --owner <owner_id> payback-review --out ...`
6. **Rebuild and install the APK** (from `frontend\`, then the phone over
   USB, as in "Android app" above):
   ```powershell
   cd frontend; npm ci; npm run android:apk
   adb install -r D:\Projects\FinancesApp\mobile\android\app\build\outputs\apk\debug\app-debug.apk
   ```
7. **Check on the phone**: To-do shows the newest first; pull down on Home and
   it says "Updated hh:mm"; a credit from a friend in Transactions has Paid
   back / Not paid back; Settings has "Count investments in Spent" (off).

### Cross-origin check (the test routine since 4F-B, D-104)

```powershell
cd frontend; node scripts/cross-origin-check.mjs   # needs backend\.venv and Edge; FAKE data
```

It builds the app into `frontend\dist-xo\` (git-ignored), serves it on
`localhost:4174`, starts the API on `127.0.0.1:8765` with a throwaway
SQLite file and a test key (no Supabase), and taps Friend online and
offline-then-online in headless Edge. Since 5A it then replays, with Origin
`https://localhost`, what the Android WebView sends: a preflight per method
with every app header, the snapshot, registering a phone, the phone's native
upload (no Origin), a revoke; and checks another origin is refused. It
prints every preflight and write with its status and ends with
`CROSS-ORIGIN CHECK: PASS` (exit 0) or `FAIL`.
Run it whenever headers, CORS or the outbox change. Since D-147 it warms the API first and
waits for the page's load event and the To-do card (prints "page ready after N s").

### Screens for design review (4H, D-113)

```powershell
cd frontend; node scripts/screens.mjs --out <folder>    # demo data, Edge, 360 px: light, dark, 200 % text
node scripts/screens-page.mjs --after <folder> --before <folder>   # docs\design\screens-4h.html
```

Since the premium run: `--widths 360,1280` adds a desktop width and `--only <prefix>` shoots
only matching screens (for example `--only insights`); the report also lists touch targets
under 44 px ("small"). A full run at two widths takes about 15 minutes.
`screens.mjs` starts the demo dev server (FAKE data) and writes one JPEG
per screen and mode plus `report.json` (sideways scroll, elements past the
edge, text squeezed to less than half). `--root <frontend folder>` shoots
another checkout (a `git worktree` of an older commit, with `node_modules`
linked). Pictures stay outside the repo; only the page is committed.

### Statement check, transfers and statement names (4A, from `backend\`)

Download the HDFC statement from NetBanking as **Delimited** (not PDF, not
Excel) into `D:\FlashPrivate\` (one normal month and one messy month). The
commands read the file and print; nothing is stored. Run a recompute first if
the app says "being updated".

```powershell
# 0. (4Z) The HDFC messages no parser reads, redacted (counts on screen; files PRIVATE)
.\.venv\Scripts\python.exe -m app.cli redact-sample --family HDFC --unparsed
#    After reading both files in D:\FlashPrivate\review\: scan again, copy to data\sample\
.\.venv\Scripts\python.exe -m app.cli redact-sample --approve HDFC-UNPARSED
# 1. The statement against the app (SAFE TO PASTE: counts and rupee sums per month)
.\.venv\Scripts\python.exe -m app.cli statement-check --file D:\FlashPrivate\<normal>.txt
.\.venv\Scripts\python.exe -m app.cli statement-check --file D:\FlashPrivate\<messy>.txt
#    PRIVATE (screen only, never paste): the unmatched rows, one per line
.\.venv\Scripts\python.exe -m app.cli statement-check --file D:\FlashPrivate\<normal>.txt --details
# 2. Names for senders shown only as a UPI ID (SAFE TO PASTE: counts; a dry run)
.\.venv\Scripts\python.exe -m app.cli statement-names --file D:\FlashPrivate\<normal>.txt --file D:\FlashPrivate\<messy>.txt
#    PRIVATE (screen only): the proposed names
.\.venv\Scripts\python.exe -m app.cli statement-names --file D:\FlashPrivate\<normal>.txt --file D:\FlashPrivate\<messy>.txt --show
#    (4Z) The statement-only rows as transactions: dry run (SAFE TO PASTE: counts by cause)
.\.venv\Scripts\python.exe -m app.cli statement-import --file D:\FlashPrivate\<normal>.txt --file D:\FlashPrivate\<messy>.txt
#    Only after the planner's OK: import them (counts; ends with a recompute)
.\.venv\Scripts\python.exe -m app.cli statement-import --file D:\FlashPrivate\<normal>.txt --file D:\FlashPrivate\<messy>.txt --apply
#    Only after the planner's OK: write them (counts; ends with a recompute)
.\.venv\Scripts\python.exe -m app.cli statement-names --file D:\FlashPrivate\<normal>.txt --file D:\FlashPrivate\<messy>.txt --apply
```

"balance breaks" should be 0; anything else means a row was read wrongly:
paste the count only. Transfers between your HDFC and SBI accounts need no
command: after the deploy's recompute, pairs with one UPI reference are
transfers, and close pairs without one appear in To-do as "Moved between
your accounts?" (answer Yes or No on the phone).

### Other banks and paybacks: commands after the 4F-A deploy (from `backend\`)

Render runs migration `0009`. The first time the phone (or any read) asks
after the deploy, the server recomputes once by itself; no "Totals are being
updated" wait. Run these in order; each prints counts only unless marked.

```powershell
# 1. Paybacks the old "All from" confirmed without your answer (SAFE TO PASTE: counts, months)
.\.venv\Scripts\python.exe -m app.cli payback-audit
# 2. What the repair would change (dry run, SAFE TO PASTE)
.\.venv\Scripts\python.exe -m app.cli payback-audit --fix
# 3. Only after the planner says so: make the change (counts; ends with a recompute)
.\.venv\Scripts\python.exe -m app.cli payback-audit --fix --apply
# 3b. (4H, D-111) Undo an earlier --apply where a Friend answer is on record (dry run, SAFE TO PASTE)
.\.venv\Scripts\python.exe -m app.cli payback-audit --restore
#     Only after the planner says so: restore them (counts; ends with a recompute)
.\.venv\Scripts\python.exe -m app.cli payback-audit --restore --apply
# 4. Your messages by bank, kind and parse status (SAFE TO PASTE: sender codes and counts)
.\.venv\Scripts\python.exe -m app.cli bank-survey
# 5. What the generic parser would read, before any reparse (SAFE TO PASTE: counts)
.\.venv\Scripts\python.exe -m app.cli generic-preview
# 6. A redacted sample of your main other bank, to D:\FlashPrivate\review\ (counts on screen)
.\.venv\Scripts\python.exe -m app.cli redact-sample --family SBI
#    PRIVATE: read sbi-sample.txt and sbi-vocabulary.txt there; never paste them
# 7. After reading both: scan again and copy into data\sample\ (git-ignored)
.\.venv\Scripts\python.exe -m app.cli redact-sample --approve SBI
# 8. Only after the planner says so: read the other banks' stored messages
.\.venv\Scripts\python.exe -m app.cli reparse --dry-run
.\.venv\Scripts\python.exe -m app.cli reparse
```

If `redact-sample` says "refused", paste only the counts per reason; the
lines it shows on your screen are PRIVATE. After a reparse, To-do lists the
new rows under "Check these payments": "Looks right" or "Not a payment".
Android may take up to a day to show the new C2 icon on an installed app;
reinstalling shows it at once.

### Which build is on the phone

Home shows one muted line next to Sign out: `Version 0.1.0 · build 1a2b3c4`.
The build id is the first 7 characters of the commit Vercel built
(`dev` on a local build). Compare it with `git log --oneline -1` on `main`
after the push, or with the commit on the Vercel deployment.

- A new deploy shows "New version available" at the bottom of the app
  (on launch, on return to the app, or within the hour). Reload switches to
  it; Later hides the bar until the next launch (D-085).
- The line still shows the old id: close the app completely (swipe it out of
  recent apps) and open it again. No need to clear site data.

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

# On the full data: redact everything (no --limit) into the PRIVATE folder, check it, then measure
backend\.venv\Scripts\python.exe scripts\redact_sms.py --input D:\FlashPrivate\raw --private-dir D:\FlashPrivate\private --output D:\FlashPrivate\private\redacted_full.json --verify
backend\.venv\Scripts\python.exe scripts\parse_coverage.py --input D:\FlashPrivate\private\redacted_full.json
```

The full redacted file never goes in the repo, not even in gitignored
`data\` (D-051). Only run the coverage step if the first command ends with
`Leaks: 0`.

### Import pipeline (you run these; agents never touch Supabase or real data)

From `backend\`. `DATABASE_URL` comes from `backend\.env` (Supabase). The
input is a backup file or a folder of `*.xml` files (not searched
recursively). Every command prints counts only.

```powershell
cd backend
# 1. Migrate (Render also runs this on deploy; repeating is safe). Expect 0007 (head)
.\.venv\Scripts\python.exe -m alembic upgrade head; .\.venv\Scripts\python.exe -m alembic current
# 2. Dry run: full pipeline inside one transaction, rolled back. Saves nothing
.\.venv\Scripts\python.exe -m app.cli import-sms --input D:\FlashPrivate\raw --dry-run
# 3. Import
.\.venv\Scripts\python.exe -m app.cli import-sms --input D:\FlashPrivate\raw
# 4. Re-import the same input: expect raw new 0 and no "new" under transactions
.\.venv\Scripts\python.exe -m app.cli import-sms --input D:\FlashPrivate\raw
# 5. Reparse dry run: expect reparsed 0 (everything is at the current parser version)
.\.venv\Scripts\python.exe -m app.cli reparse --dry-run
# 6. Stats: tables, types, unknown queue, candidates, month range, last batches
.\.venv\Scripts\python.exe -m app.cli stats
# 7. Merchant engine survey: read-only, counts only (kinds, reasons, key reuse, UPI handles)
.\.venv\Scripts\python.exe -m app.cli merchant-stats
# 8. PRIVATE, your screen only: merchants with real names. Never paste or redirect it
.\.venv\Scripts\python.exe -m app.cli merchant-review --kind unsure --sample 30 --seed 1
# 9. Reconcile: read-only, counts only (roles, rules, links, candidates, existing candidates)
.\.venv\Scripts\python.exe -m app.cli reconcile-stats
```

- After a parser version bump: `python -m app.cli reparse --dry-run`, then
  `reparse`. Nothing is deleted; transaction ids stay stable.
- A crashed import is safe to re-run: committed messages are skipped as
  duplicates. The crashed batch stays `failed` (or `running` if killed).
- `stats` shows months only (IST), never days, amounts or names.
- `import-sms` and `reparse` now end with a recompute block. If that block
  says "recompute failed", the import itself is saved: fix the cause and
  run `recompute`.
- `merchant-review` filters: `--kind business|person|unsure`,
  `--confidence high|low`, `--reason R5_digits`, `--direction
  debit|credit|refund`, `--sample N --seed S`. It shows real names, so it
  only prints to a console window (no pipe, no `>`).
- `reconcile-stats` runs with empty owner data until step 3C-4, so every
  basis is `engine` and the no-income-party warning always shows. Until
  then your own transfers count as spend and pocket money as a payback.
  In its output, "existing candidates ... lost" must be 0; tell the
  planner if it is not.

**Merged refund (PRIVATE, your screen only).** Two refund messages became
one transaction in Phase 2. To see both source messages, open the Supabase
dashboard, SQL Editor, and run this. It only reads. Never paste the result
anywhere; tell the planner only "one event" or "two events" (D-064).

```sql
select t.id, t.type, t.txn_time_utc, r.id as raw_id, r.received_at, r.sender_raw, r.body
from transactions t
join transaction_sources s on s.transaction_id = t.id
join raw_messages r on r.id = s.raw_message_id
where t.id in (select transaction_id from transaction_sources
               group by transaction_id having count(*) > 1)
order by t.id, r.received_at;
```

Same wording and the same date inside both messages: the bank sent one
refund twice (one event, nothing to fix). Different dates or wording, or
two credits on the bank statement: two events.

### Owner data and recompute (you run these; counts and field paths only)

The owner file is a **developer tool** (D-075): import and backup. Nothing
in the product needs it; the app answers through the API.

Your owner file lives at `D:\FlashPrivate\private\owner.json`. Copy the
shape of `docs\owner.example.json`; the keys are explained in
[docs/data-model.md](docs/data-model.md), "Owner file". Never paste the file.

```powershell
cd backend
# 1. Check the file, save nothing. Problems are named by field path
.\.venv\Scripts\python.exe -m app.cli owner-load D:\FlashPrivate\private\owner.json --dry-run
# 2. Load it. Ends with a recompute. Loading the same file again changes nothing
.\.venv\Scripts\python.exe -m app.cli owner-load D:\FlashPrivate\private\owner.json
# 3. Recompute by hand (after a deploy that changed an engine version). --dry-run counts only
.\.venv\Scripts\python.exe -m app.cli recompute
# 4. Only when recompute stops with exit code 3 and you checked the owner file
.\.venv\Scripts\python.exe -m app.cli recompute --accept-key-changes
```

```powershell
# 5. PRIVATE, your screen only: decide candidates, uncertain credits, debits with no payee
.\.venv\Scripts\python.exe -m app.cli reconcile-review --list
.\.venv\Scripts\python.exe -m app.cli reconcile-review
# 6. PRIVATE, your screen only: one IST month from the stored roles
.\.venv\Scripts\python.exe -m app.cli totals --month 2026-01
# 7. Backup of every owner row and decision (the free Supabase plan has none)
.\.venv\Scripts\python.exe -m app.cli owner-export D:\FlashPrivate\private\owner-export.json
# Restore after a rebuild: import the SMS first, then load the export into empty owner tables
.\.venv\Scripts\python.exe -m app.cli owner-load D:\FlashPrivate\private\owner-export.json
```

```powershell
# 8. Categories: counts and percentages only, safe to paste
.\.venv\Scripts\python.exe -m app.cli category-stats
# 9. PRIVATE, your screen only: give merchants a category (most transactions first)
.\.venv\Scripts\python.exe -m app.cli category-review --uncategorised --list
.\.venv\Scripts\python.exe -m app.cli category-review --uncategorised
```

- `credit-review` (PRIVATE): `friend`, `income <label>`, `ignore`, or enter
  to skip, for each sender to confirm. Only confirmed paybacks lower Net.
- `category-review`: answer a number or slug from the list it prints; enter
  skips, `none` clears a default, `quit` keeps earlier answers. A category
  on a merchant covers its past and future payments. In the owner file a
  party may also state `"category": "food_drinks"`.
- Review answers: pairs `same`, `different`, `skip`; uncertain credits
  `payback`, `income`, `ignored`, `leave`; debits with no payee
  `self_transfer`, `ignored`, `leave`; `quit` keeps earlier answers.
  Empty answer = skip or leave.
- `totals` refuses when stored rows are stale: run `recompute` first.
- "texts matching no transaction" lists field paths: a likely typo, or a
  text that has not appeared yet.
- In `reconcile-stats`, "stored rows that differ" must be 0 after a
  recompute.

### Frontend demo on your phone (same Wi-Fi as the PC)

```powershell
cd D:\Projects\FinancesApp\frontend
npm ci
npm run dev -- --host
# Vite prints a Network address such as http://192.168.1.23:5173/ : open it on the phone.
```

Allow Node through Windows Firewall on private networks when asked. Stop with
Ctrl+C. With `VITE_DEMO=1` in `frontend\.env` it shows demo data and nothing
reaches the API.

The logo and icons are at the same address plus `#/dev/logos` (demo only). Any screen can be
opened or shared by its URL, for example `#/home/category/people?m=2026-11`.

### Back up and restore (you run these; agents never do)

Back up (Docker Desktop running; reads `DATABASE_URL` from `backend\.env`,
prints only the file name and size):

```powershell
cd D:\Projects\FinancesApp
powershell -ExecutionPolicy Bypass -File scripts\backup_db.ps1
# flash-20261117-2210.dump  0.4 MB   -> D:\FlashPrivate\backups\
```

Use the Session pooler URL (port 5432), as the app does; the transaction
pooler (6543) cannot run pg_dump. A failure prints one line and keeps
nothing. Keep a copy of `D:\FlashPrivate\backups\` off this PC.

Look inside a backup (lists tables, no data):

```powershell
docker run --rm -v D:\FlashPrivate\backups:/in postgres:17 pg_restore --list /in/flash-20261117-2210.dump
```

Restore, into an **empty** database first (a new Supabase project, or a local
`postgres:17` container), never straight over the live one:

1. Put the target URL in an environment variable for this window only (it
   is not printed): `$env:FLASH_RESTORE_URL = Read-Host "Target postgresql:// URL"`
2. `docker run --rm -e FLASH_RESTORE_URL -v D:\FlashPrivate\backups:/in postgres:17 sh -c 'pg_restore --no-owner --no-privileges --dbname="$FLASH_RESTORE_URL" /in/flash-20261117-2210.dump'`
   One error, "schema public already exists", is expected and harmless.
3. `Remove-Item Env:FLASH_RESTORE_URL`
4. Point `DATABASE_URL` (backend\.env, Render) at it, then from `backend\`
   run `alembic current` (it should name the newest migration) and
   `python -m app.cli stats`. Only then switch the app over.

### Template survey (reads only the redacted sample)

```powershell
backend\.venv\Scripts\python.exe scripts\shape_survey.py --input data\sample\redacted_sample.json --senders HDFCBK,HDFCBN --output data\sample\hdfc_shapes.json
```

Output stays in `data\sample\` (gitignored). Same command for other banks with
their sender cores. Fixtures for parsers: `backend\tests\fixtures\sms\<bank>.json`
(fake values only; checked by `backend\tests\test_sms_fixtures.py`).

### Git: daily loop

```powershell
git config core.hooksPath .githooks              # once per clone: no AI attribution lines (D-109)
git switch main; git pull                         # start from latest main
git switch -c feat/short-name                     # new branch (same as checkout -b)
git add -p                                        # stage piece by piece
git commit -m "feat(scope): what and why"
git switch main; git merge --no-ff feat/short-name
git branch -d feat/short-name
git push                                          # CI + Vercel start; Render waits for CI
git log --oneline --graph -15                     # recent history
git tag -n                                        # phase tags with their messages
git log --oneline phase-1-done..phase-2-done      # what one phase changed
```

### Push and CI

```powershell
gh run list --limit 5                             # recent CI runs
gh run watch                                      # follow the latest run live
gh run view --log-failed                          # only the failing step logs
gh repo view --web                                # open the repo in the browser
```

## Open items

Before Phase 5 (carried from Phase 4):

1. **HDFC alerts the parser cannot read**: done in 5A (`hdfc-1.2.0`, D-127),
   but the approved sample's 44 messages are all the forex markup notice,
   with no amount. So the about Rs 15,700 of October spending that showed
   only on the statement was never stored as SMS (not in the export, or a
   sender code not in the registry). 5C built the counts-only look:
   `sender-survey --contains HDFC --input D:\FlashPrivate\raw` (cheat sheet,
   "Several users", step 6); `statement-import` meanwhile. The owner runs the reparse (cheat
   sheet, "Android app", step 3).
2. **statement-import --apply** and **statement-names --apply** wait for the
   planner's OK, after the owner pastes the new dry runs (cheat sheet,
   "Statement check, transfers and statement names").
3. **September re-check**: `statement-check` on the September file with
   `stmt-hdfc-1.1.0` (it failed on a negative-debit card row under 1.0.0);
   "balance breaks" must be 0.
4. **Your name as banks show it**: the owner adds the variants in the app
   (Speed sheet, "Your name as banks show it") so "Is this you?" and the
   own_or_internal cause can work; then answers the To-do questions.
5. From 4H: `payback-audit --restore` (dry run) and the planner's call on
   `--apply`; delete the cron-job.org job "Flash API warm 07-01 IST" if it is
   still there (D-112); `git config core.hooksPath .githooks` in every clone
   (D-109).

From 5A (Android):

5a. The owner's install and first run (cheat sheet, "Android app"): push,
    Render `CORS_ORIGINS` with `,https://localhost`, reparse, the Supabase
    settings in `frontend\.env`, `npm run android:apk`, `adb install -r`.
    The APK built on 22 Nov used placeholder sign-in settings (the local
    `frontend\.env` has none): it cannot sign in; rebuild it first.
5b. Not run anywhere yet: the app on a real phone (permission and
    restricted settings, receiver, WorkManager, Keystore, battery); the
    on-device tests (`connectedDebugAndroidTest`). Checked: JVM unit tests,
    the server end to end, the cross-origin replay of the WebView's requests.
5c. Done (D-150): a bank SMS with an emoji outside the basic plane, which SMS
    Backup & Restore writes as two U+FFFD, is now one SMS whichever copy comes first.

Ongoing:

6. Not checked on a real phone yet: the person sheet actions, "Moved between
   your accounts?", It's me and Investments, the Your name sheet, 200 % text
   (checked in headless Edge on demo data, `docs/design/screens-4h.html`),
   Speed sheet timings and an offline tap. Not checked at all: real iOS,
   screen readers.
7. Categories from names (D-119) are proven on 154 FAKE names; the redacted
   sample hides real payee names, so the split on real data is unmeasured.
   A shopkeeper's QR named after a person is guessed People.
8. Accepted risk: npm audit, 4 moderate findings, build-time only: glob
   11.1.0 (GHSA-3g3m-2fjr-6pw4) and minimatch 10.2.6 and 5.1.9
   (GHSA-g3hv-75wg-m249), via vite-plugin-pwa 2.0.0 and workbox-build 7.4.1,
   the newest releases. No patched release in the same major, so no
   override. Recheck when Workbox ships a fix; never `npm audit fix --force`.
9. The Supabase free plan has no backups; the owner runs
   `scripts/backup_db.ps1` (D-084).
10. The owner's To-do backlog to work through on the phone.
11. The owner doubts the October People total: verify it person by person
    (the statement check helps).
12. Vercel: `VITE_API_URL` is saved as a Secret. The owner changes it to a
    plain variable and redeploys with the build cache off.
13. The unticked "merged refund" check (one event or two, D-064): settle it
    with a statement month that has a refund.
14. Later list: a friendlier Home, still minimal; revisit with 4D.

Known limits: HDFC and SBI parsers (other banks generic), INR only; the
card bill pair rule waits for credit card SMS; the server sleeps when idle (about a minute to wake; the phone
copy covers it, D-112); import takes about 6 minutes for 917
messages; Starlette's httpx warning is accepted (D-010).

Also on record (NOTES only):

- HDFC H09 word slot: the word is still mapped in the private name map; the
  template accepts any word, so parsing is unaffected.
- Name detection in redaction covers the usual bank positions only; skim new
  samples. Bank vocabulary covers HDFC wording only: each new bank's survey
  adds its fixed phrases to `BANK_VOCABULARY`.
- The logo was not checked against a trademark register (D-083).
- GitHub cannot enforce required checks on a private repo on the free plan;
  Render deploying only after CI passes is the gate (D-050).

## Log

### 2026-11-23: 5F part 1, Insights: Profile, Admin, Export

- A fifth tab, Insights. Profile and Admin gather the existing settings and the member list.
- Export: CSV or Excel (stdlib zipfile and XML) from `GET /api/v1/export`, download on the
  web, the share sheet in the Android app (FileProvider) (D-146).
- Not done yet: Analytics, and "Learn from the owner" (its spec was not in the prompt).

### 2026-11-23: 5B-2 paybacks, masked senders (reconcile-1.7.1)

- Cause of 126 confirmed paybacks with 0 links: masked credit senders ("*ahad@oksbi") never
  met the payee's full UPI ID ("rahad@oksbi"). Fix: one fitting payee in the 90 days (D-145).

### 2026-11-23: Phase 5B-2, the phone just works

- Diagnosis with file:line evidence: docs/design/phase-5b2-phone.md. Main cause: a new SMS
  waited behind a retry in backoff (KEEP), and opening the app or reconnecting never
  started an upload.
- Phone: uploads at once (expedited, REPLACE), hourly catch-up, `_id` cursor, live copy
  after 2 minutes, drop only what the server refused, queue kept while disconnected,
  notifications, status screen, event log, Copy diagnostics (D-142, D-143).
- Server: migration `0017`; the twin rule for the two copies of one SMS (D-139); the data
  version and a 304 in 9 statements (D-140); `new_transactions` in the ingest answer (D-141).
- App: reconnect by itself at sign-in, notification taps open the payment, 401 refreshed
  once then a "Sign in again" banner, Paid back covers every credit and asks first (D-144).

### 2026-11-22: Phase 5B-1, daily-use correctness

- To-do newest first (time, then id) on the server and in the app (D-138).
- Refresh on focus and return, after the outbox flushes, every 60 s while
  visible, never two at once; pull-to-refresh (own code) and a Refresh link on
  desktop; "Updated hh:mm" (D-135). Load: one snapshot is 82 statements and
  about 2 MB of database reads for 704 FAKE transactions.
- `categorise-1.3.0`: People only when clearly personal (D-133); FAKE table of
  46 payees in `tests/test_people_bias.py`.
- `reconcile-1.7.0`: a payback guess needs a payment to the person in the 90
  days before (`CR_no_debit` otherwise); payback links in the snapshot; Paid
  back / Not paid back in the transaction sheet (D-134). The 13 engine
  paybacks never counted in Paid back, Net or Spent.
- Invested and Invested (to confirm) per month, the Investment tag and filter,
  "Count investments in Spent" (migration `0016`, `PUT /profile/settings`,
  default off) (D-136).
- Owner commands `category-diff --out` and `payback-review --out` (D-137).

### 2026-11-22: 5C fix, CI red on 97aa4e2

- Cause: the tests read the local `backend/.env`; its `PING_TOKEN` made
  `/health/db` answer 401 here and 503 on CI, and the isolation test expected
  below 500. Fix: tests never read a `.env` (`FLASH_IGNORE_ENV_FILE`, set in
  `conftest.py`, which also drops app settings from the shell; checked by
  `test_config.py`); the isolation test treats the health routes as unscoped
  but still checks they reveal nothing of the other user.
- Reproduced and verified from a clean clone with CI's env: SQLite 1057
  passed 6 skipped; Postgres 17 1060 passed 3 skipped.

### 2026-11-22: Phase 5C, several users

- Migration `0015`: `app_users`, `invites`, `auth_deletions` (RLS on).
- Login lookup in `app_users`; `AUTH_USERS` seeds the admin on the first
  request (D-129). Invites and `POST /api/v1/signup` through the Supabase Auth
  Admin API (`SUPABASE_SECRET_KEY` on the `apikey` header; urllib), rate
  limits, generic errors (D-128). Device tokens stop for a removed user.
- `tests/test_isolation.py`: all 39 routes as another user (D-130).
- Delete my account (`POST /api/v1/account/delete`, fresh sign-in, every
  table from the models, then the login; `auth-cleanup`) (D-131).
- App: Settings (⋯), People who use Flash, Delete my account, What Flash
  stores, first run, invite sign-up on the login screen (D-132).
- CLI `--owner`, `sender-survey --contains`, `auth-cleanup`.

### 2026-11-22: Phase 5A, Flash on Android

- Server: migration `0014` (`devices`, RLS on); `POST/GET/DELETE
  /api/v1/devices`; `POST /api/v1/ingest/sms` with an ingest-only device
  token, bank senders only, `store.ingest()` as import-sms (source
  `live_sms`), statuses stored / duplicate / refused_not_bank /
  refused_filtered, recompute mark; the sender list moved to
  `app/engine/shared/bank_senders.json` (shared with the APK); snapshot
  `devices` and `sms.newest_utc`; CORS allows `https://localhost` when listed
  (D-122, D-123, D-125).
- Statement rows keep their id when an SMS merges, by reference or by amount
  and day, and after a reparse: proven by a test, no code change (D-126).
- HDFC `hdfc-1.2.0`: H04 forex notice is `other_info` (D-127).
- Android (`mobile/android`): Capacitor 8.6.2, Gradle 9.9.2, AGP 9.5.1,
  compileSdk/targetSdk 36, minSdk 26; Kotlin plugin `FlashSms`, receiver,
  SQLite queue, WorkManager 2.12.0 upload and 6-hourly catch-up, Keystore
  AES-GCM token (D-124, D-125). Gradle downloaded SDK Platform 36.
- Frontend: Bank SMS sheet (`?sms`), Speed sheet Bank SMS block, Home prompt,
  refresh on upload, sign-out revokes the phone, no service worker in the
  app; `npm run android:apk`.
- Cross-origin check replays the WebView's requests from `https://localhost`.

### 2026-11-21: Phase 4Z, closing Phase 4

- Push verified (main and 9 tags equal on GitHub, no attribution lines);
  git backup mirror deleted, reflogs expired, gc run (D-121).
- `stmt-hdfc-1.1.0` (negative and two-sided rows by the balance chain,
  quoted separators, blank or "-" amounts); statement-check causes
  (sms_not_parsed, own_or_internal, fd, investment_or_broking,
  card_bill_payment, verification_or_tiny, likely_spend, likely_income);
  `statement-import`; `redact-sample --unparsed` (D-120).
- It's me and Investments (party kinds self and investment, role
  investment, `reconcile-1.6.0`), To-do suggestions, "Your name as banks
  show it", migration `0013` (D-117, D-118).
- `categorise-1.2.0`: categories from names and UPI IDs (D-119).
- Phase 4 retro: `docs/retro/phase-4.md`.

### 2026-11-21: Phase 4A, money correctness

- `stmt-hdfc-1.0.0` reads the HDFC Delimited statement (from the right, so
  commas in narrations are fine; balance check), `statement-check` per IST
  month with likely causes and Spent/Net with statement-only debits (D-114).
- `reconcile-1.5.0`: SBI accounts learned from SBI messages; a shared
  12-digit reference links an own-account transfer automatically; the same
  amount within 30 minutes is asked in To-do (`PUT /api/v1/transfers/…`,
  `todo.transfers`) (D-115).
- `statement-names`: payer names for bare or masked UPI senders, owner
  approved; migration `0012` `parties.name_source` (D-116).

### 2026-11-21: Phase 4H, people actions, payback rule, polish

- Person sheet (D-110): "Payments to them count as" (chips, the party
  default), "Money from them is" (Friend / Family / Ignore / Income),
  "Recent payments" (last 10, "just this one"); all through the outbox,
  offline too. Opens from ledger rows and "Person" on To-do cards and
  transaction sheets.
- payback-audit (D-111): any Friend, Family or Income answer on record
  (answered_at, newest stored app answer, role decisions on its credits)
  is never silent; `--restore [--apply]` undoes an earlier fix where a
  Friend answer is on record.
- Carry-overs: `new_label` reuses a same-name label so an offline label can
  be picked again (D-110); a refused change shows "Not saved" on its item;
  the API warm job is retired (D-112).
- Polish (D-113): one money formatter (paise only when not zero on a
  transaction), one date set, rows that wrap at 200 % text, 44 px segmented
  control, capped Net/ring/tab names, "Not saved" wording, eight category
  colours nudged (all pairs at least 10 apart), tokens in ui-spec.
  Screens before and after: `docs/design/screens-4h.html`.
- No migration.

### 2026-11-21: history rewrite (no AI attribution)

- 116 of 160 commits lost their `Co-Authored-By: Claude` line
  (`git filter-branch --msg-filter`); trees, authors and dates identical.
  Backup mirror: `D:\Projects\FinancesApp-backup-20261121.git`. Mapping and
  restore: [docs/history-rewrite-20261121.md](docs/history-rewrite-20261121.md).
  SHAs quoted in log entries below are the old ones.
- Prevention: `attribution` in `.claude/settings.json`, `.githooks/commit-msg`
  (tested by `scripts/test_commit_msg_hook.py`), a CLAUDE.md rule.

### 2026-11-21: Phase 4F-B, blocked taps, SBI parser

- Root cause of the phone's stuck tap: `allow_headers` in
  `backend/app/main.py` lacked `Idempotency-Key` and `X-Defer-Recompute`
  (sent by every outbox write since 4B-2): the cross-origin preflight got
  400 and the browser never sent the PUT. Reproduced and fixed with the new
  cross-origin check (D-104).
- Outbox: codes, watchdog, caught errors, versioned entries (D-105);
  "Saved on phone" wording and details (D-107).
- Writes commit with a recompute mark; reads recompute (D-106, migration
  `0010`).
- payback-audit: explicit answers (`parties.answered_at`, stored app
  answers) are never silent.
- SBI parser `sbi-1.0.0` (D-108; `docs/templates/sbi.md`).
- API request log (method, route template, status, duration).

### 2026-11-20: Phase 4F-A, other banks, payback safety, logo C2

- CI fix (Part 0): the 31-character label test accepts Postgres's
  DataError or SQLite's IntegrityError and checks no row was written; two
  test lookups got ORDER BY. Backend now also run locally on Postgres 17.
- D-102: the first read after a deploy recomputes when the stored rows were
  made by other engine versions (trigger `read`, migration `0009`).
- D-099: `payback-audit` (counts), `--fix` (dry run), `--fix --apply`.
- D-100: `bank-survey`; `redact-sample --family` / `--approve` with a leak
  scan.
- D-101: generic parser `generic-1.0.0` for SBI, ICICI, Axis, Kotak, YES and
  India Post; `generic-preview`; To-do "Check these payments".
- D-103: "Not a payment" / "Count it again" on every transaction.
- Logo C2 in the header and every icon; `docs/design/logo-options.html`
  shows C next to C2.

### 2026-11-20: Phase 4E, people, faster To-do, logo options

- People (D-096): a person is an owner party; Name, Same as…, Separate
  (rows kept with `ended_at`), role conflicts asked explicitly, new party
  kind `unsure`, senders grouped by person, `people` in the snapshot.
  Routes `/api/v1/people/{txn}/name|join`. Engine `reconcile-1.4.0`,
  `categorise-1.1.0` (no change for existing data).
- Fixed: "All from" on a person-like text no longer confirms their credits
  as paybacks (the party it makes has no answer).
- To-do: "See payments" (`?who=`), up to 4 category chips, Name and Same
  as… on sender cards; the person sheet (`?person=`).
- Migration `0008`: label limit 30 everywhere with a stop guard (D-097),
  `parties.display_name`, party text history. `HEAD /health` (D-098).
  Sign-out clears `flash-boot`.
- Logo options A, B, C: `docs/design/logo-options/` and
  `docs/design/logo-options.html`.
- Tests: backend 722 on SQLite (3 Postgres-only skipped), scripts 89,
  frontend 76. Demo checked in headless Edge at 390 px. Not pushed.

### 2026-11-20: Phase 4B-3, offline boot

- Cause of the blank screen: `App.tsx` drew nothing while auth was
  "starting", and the start waited for supabase-js's `INITIAL_SESSION`,
  which comes after up to 30 s of refresh retries; then it went to the
  login, hiding the phone copy. Reproduced on a production build: offline
  with an expired session blank for 28 s, then the login.
- Fix (D-095): identity from the stored session before the first render,
  refresh in the background (10 s token wait), "Sign in to sync" keeps the
  data and the outbox, offline login note, 3 s watchdog, error boundary,
  `index.html` "could not start" page, Speed Boot block and column.
- Tests: frontend 70 (10 new boot tests), backend 707 on SQLite, scripts
  89. Precache: all 10 files first paint needs; no other origin. Not pushed.

### 2026-11-19: Phase 4B-2, offline queue for owner actions

- Server: `client_ops` (migration `0007`, RLS on), `Idempotency-Key` on the
  six owner writes in `backend/app/api/ops.py` (replay, 409 in progress,
  422 key reuse, 5xx not stored, key per owner), `X-Defer-Recompute` with
  reads recomputing first, `{"new_label"}` on the label route (D-091,
  D-092, D-094). About 40 ms per write and recompute on the FAKE year.
- Phone: outbox in IndexedDB v2 (`frontend/src/data/outbox.ts`), drain
  rules and backoff, "Waiting to sync" on items, To-do waiting section,
  sync line, Couldn't save sheet, sign-out warning, Speed Sync block,
  `?speed` and `?unsaved` in the URL, merchant card dates (D-093). A lost
  session keeps the phone copy and the outbox.
- Tests: backend 707 on SQLite (3 Postgres-only skipped), frontend 60. Demo
  checked in headless Edge at 390 px. Not pushed.

### 2026-11-19: Phase 4B-1, phone copy and instant open

- `GET /api/v1/sync/snapshot` (D-088): every figure from the same functions
  as the other routes, ETag, 304, gzip. The server now also works out the
  merchant groups, People ledger, ring, changes and To-do merchants that
  the app used to add up. FAKE year: 704 transactions, 230,686 bytes raw,
  11,918 gzipped, 0.13 s to build on SQLite.
- Phone copy in IndexedDB (D-089, `idb` 8.0.4), freshness line, offline
  message for owner actions, Speed sheet (D-090). API test helpers moved to
  `backend/tests/apiclient.py`.
- Tests: backend 696 on SQLite (3 Postgres-only skipped), frontend 46; demo checked in headless Edge
  at 390 px (reload drew Home from the copy in 96 ms, then 304). Not pushed.

### 2026-11-19: Phase 4C, install and update prompt

- Update bar instead of silent updates (D-085): `registerType: "prompt"`,
  Reload and Later, checks on launch, on return to the app and hourly.
  App-shell-only service worker, no runtime caching (D-086). Manifest name,
  `id` and `scope`, light splash colour. Build id on Home (D-087). Config in
  `frontend/src/pwa.ts`, bar in `frontend/src/update.ts`.
- npm audit unchanged: 4 moderate via workbox-build 7.4.1 (newest), no
  patched glob or minimatch in the same major, so no override.
- Docs cleanup: Status ticks, Open items equal to HANDOFF, Architecture
  (env, tables, Flow 1, warm job), HANDOFF stack and workflow, PLAN Phase 4.
- Tests: frontend 32 (8 new), lint, typecheck, build; backend and scripts
  unchanged. Not on a real phone yet.

### 2026-11-18: Phase 3 closed

- docs/OVERVIEW.md (one-page tour, linked from README and HANDOFF); PLAN
  Phase 3 done with the bank statement check carried to Phase 4; HANDOFF
  current state and open items; CHANGELOG entry. Docs only. Not pushed.

### 2026-11-17: Phase 3F-3, real login and data, colours, chart, logo, backup

- API (D-079): `role_basis` and `person_id` on items, `GET
  /transactions/{id}`, `previous` in `/summary`, label totals, ignored
  senders, `DELETE /senders/{id}`, `income_label`, label names 1 to 30
  with 409. No migration.
- App (D-080): `@supabase/supabase-js` 2.119.0 login, HTTP adapter, 401,
  403, 503 and offline states, Sign out; demo only with `VITE_DEMO=1` in dev.
- Design (D-081 to D-083): category colours and tiles, List | Chart ring,
  $ mark and FLA$H wordmark, new PWA icons. Backup script (D-084).
- Tests: 685 backend on SQLite (3 Postgres-only skipped), 688 on Postgres 17
  in Docker; frontend lint clean, 24 tests, typecheck and build. Real
  adapter checked against a local backend on fake data and a stand-in auth
  server, 360 and 390 px, light and dark, in headless Edge. Not pushed.

### 2026-11-17: Phase 3F-2, navigation, fixes and design pass

- The view lives in the URL hash; reload and cold links restore it; Back
  closes sheet, then detail, then reaches the tab root; scroll kept; data
  reused, "Starting up" only for a slow first request (over 3 s).
- Lucide 1.74.0 icons (27 SVGs, ISC licence in `frontend/src/icons/`), Home
  comparison and Recent, people ledger, search, sticky day headers, To-do
  Confirmed, label rules, three logo options on `#/dev/logos`.
- Checked at 360, 390 and 480 px, light and dark, and at 200 % text, in
  headless Edge; Back, scroll and "Starting up" driven over DevTools. Not on a
  real phone. Lint clean, 19 tests, typecheck and build pass. Not pushed.

### 2026-11-17: Phase 3F-1, screens on demo data

- UI spec recorded (docs/ui-spec.md): calm statement look, one teal accent
  (#0e6862 light, #6bb7af dark), system font, tabular figures.
- Screens: login, Home, category detail, Transactions with detail sheet, To-do,
  Labels; demo banner and state switch. Fake adapter behind the `Api` interface.
- Frontend: lint clean, 12 tests (node --test), typecheck and build pass; CI
  frontend job now also runs lint and tests. Not pushed.

### 2026-11-16: Phase 3E, login and API

- `reconcile-1.3.0`: confirmed-only paybacks (D-076), inferred own accounts
  (D-077). `credit-review`. Owner file is a developer tool (D-075).
- Login (Supabase ES256 JWT, `AUTH_USERS`) and `/api/v1` (D-078,
  `docs/api.md`). PyJWT 2.15.1 and cryptography 50.0.2 pinned.
- Tests: 679 backend locally (3 Postgres-only skipped), 682 on Postgres 17
  in Docker, 89 scripts. Not pushed.

### 2026-11-16: Phase 3D, categories and labels

- `categorise-1.0.0`: every transaction has one category of the fixed list;
  owner decision, party default, role and channel, brand, keyword, person,
  else Uncategorised (D-073, D-074). Breakdown adds up to Spent.
- Migration `0006`; `owner-load` takes a party category; export and restore
  cover category decisions and labels.
- `category-stats`, `category-review`, `totals` with the breakdown.
- Redacted sample: 93 of 104 spend transactions Uncategorised (names there
  are pseudonyms); 16 merchants cover half of them.
- Tests: 648 backend, 3 skipped (Postgres only), 89 scripts. Not pushed.

### 2026-11-16: Phase 3C-7 and 3C-8, review, export, totals

- `reconcile-1.2.1` (D-072): a mandate ID next to a payment reference no
  longer counts as two payments. Q9 recorded (D-071). Keep-alive item
  ticked in PLAN.md. "matched by two or more rules" split in two lines.
- `reconcile-review [--list]`, `owner-export <file>`, `totals --month`;
  `owner-load` restores an export by dedupe key.
- Tests: 598 backend, 3 skipped (Postgres only), 89 scripts; ruff clean.
- Not pushed.

### 2026-11-16: Phase 3C-4 and 3C-6, owner tables, storage, recompute

- `reconcile-1.2.0` (D-069): a same-amount pair with two different
  references is two payments; Reconcile and import no longer propose it.
- Migration `0004`: six owner tables, every row with its source. `owner-load`
  checks the private JSON file strictly and replaces only file rows (D-070).
- Migration `0005`: `txn_derived`, `txn_links`, `derive_runs`. `recompute`
  writes only what changed, runs after import, reparse and owner-load, and
  stops when a merchant engine change would lose an owner match.
- `reconcile-stats` reads the owner tables and shows the stored run.
- Tests: 569 backend, 3 skipped (Postgres only), 89 scripts; ruff clean.
  Postgres was not run locally (no Docker); the CI job runs it on push.
- Not pushed: the planner reviews before the migrations reach Supabase.

### 2026-11-16: Phase 3C-3 and 3C-5, duplicates and pair linking in memory

- `reconcile-1.1.0`: `derive(txns, owner, legacy_pairs)` returns roles and
  links. A link has a kind, two ids, a status (linked or candidate), a
  rule, a reason and who decided.
- A rule links only a unique pair; anything else is a candidate, and a
  candidate changes no role and no total. Duplicates: AutoPay + card
  spend (linked inside 10 minutes, candidate up to 24 hours), same-amount
  pairs (candidates), pairs recorded at import (never lost). Pair links:
  second leg of a self-transfer, refund to purchase, FD second credit.
- Owner link decisions ("same", "different") are an input of the engine;
  there is no way to enter them yet (3C-4, 3C-7).
- Not built: the card bill pair rule (no credit card SMS seen).
- On the redacted sample: 0 links and 0 candidates (no pair exists there).
- Tests: 502 backend (67 new: 66 links, 1 CLI), 89 scripts; ruff clean.

### 2026-11-16: Phase 3C-2, decisions, merchant 1.1.1, roles in memory

- Decisions: the backbone design is approved. D-059 to D-067 record the
  planner's answers to Q1-Q11 and C1-C9, with pointers on D-029, D-031,
  D-032, D-047, D-055, D-057 and D-058. Design doc, PLAN.md (new 3C
  bullet), data-model.md and engine.md updated. The role `unknown` is now
  `uncertain`.
- `merchant-1.1.1` (D-068): a name beside a UPI ID is the display name; the
  key stays the UPI ID.
- `app/engine/reconcile.py` (`reconcile-1.0.0`): `derive()` gives every
  transaction one role, the deciding rule and its basis; `totals()` sums
  over roles. Owner data is an in-memory structure for now. No duplicates,
  pair links, owner tables or storage yet.
- `python -m app.cli reconcile-stats`: counts only. On the redacted sample:
  127 transactions, 103 spend, 21 payback, 1 refund, 1 FD move, 1 uncertain
  credit.
- Tests: 435 backend (61 new: 1 merchant, 59 reconcile, 1 CLI), 89 scripts;
  ruff clean.

### 2026-11-15: Phase 3C-1, backbone and Reconcile design

- `docs/design/phase-3-backbone.md`: design only, nothing built. Eleven
  roles and the totals as sums over them; Reconcile rules for duplicates,
  self-transfers, card bills, refunds, FD moves, paybacks and income; six
  owner tables and three derived tables (migrations `0004`, `0005`); one
  `recompute` command; invariants I10 to I21; owner file and commands;
  `reconcile-stats` lines; build steps 3C-2 to 3C-8.
- Waiting for the planner: questions Q1 to Q11 and conflicts C1 to C9 in
  section I of that file.

### 2026-11-15: Phase 3B-2, merchant engine 1.1.0 and merchant-review

- `merchant-1.1.0` (D-058): brand aliases match only at the start of the
  name or UPI local part; every merchant except `none` gets a display
  name that normalises back to its key; handles `okaxis`, `okhdfcbank`,
  `okicici`, `oksbi` are a person signal, `okbiz...` a business signal;
  keywords 69 -> 186.
- `merchant-stats` adds kind by direction, distinct keys by kind and
  confidence, and how many keys cover 50/80/95% of transactions.
- `merchant-review` (owner only): one line per key with real text; refuses
  to run unless stdout is a terminal.
- Redacted sample: 21 person low (was 2), 1 unsure (was 20); 50% of keyed
  transactions sit on 22 keys.

### 2026-11-15: Phase 3B-1, merchant normalisation engine

- `backend/app/engine/merchant.py` (`merchant-1.0.0`, D-057): counterparty
  -> business, person, unsure or none, with confidence, a stable merchant
  key and rule codes. Rules R0-R5; ambiguity always gives unsure.
- `backend/app/engine/brands.json`: 74 national brands, public knowledge
  only. Channel comes from the stored parser channel (`channel_for`); parser
  output and `hdfc-1.1.1` unchanged.
- `python -m app.cli merchant-stats`: read-only, counts only. On the
  redacted sample: 127 transactions, 93 business low (the sample's
  pseudonyms contain digits, so they look like business names), 20 unsure
  (UPI IDs only), 3 dictionary hits.
- PLAN 3A: spec and mockup may be approved any time before 3E.

### 2026-11-15: Phase 3A-1c, stale phase-numbering notes

- `docs/PLAN.md` and `CHANGELOG.md` no longer say PLAN.md numbers Phases 1
  and 2 differently; PLAN.md now states its numbers match the tags.

### 2026-11-15: Phase 3A-1b, docs follow-up

- D-015: garbled duplicate line removed.
- `docs/PLAN.md`: Phase 1 is now the parsing engine and Phase 2 the data
  model and ingestion, matching the tags; Phase 0 keep-alive check points at
  the D-053 job (16 Nov 03:30 IST); Phase 6 revisits D-026.
- D-056 owner labels: one fixed category per transaction plus at most one
  owner label; totals ignore labels; label view in 3F, storage in 3D.

### 2026-11-15: Phase 3A-1, docs alignment

- `docs/PLAN.md`: Phase 3 replaced by steps 3A-3F (normalise, reconcile,
  categorise, auth and read-only API, minimal dashboard); Phases 4-6 are now
  full deploy and PWA, Android and live SMS, statements and insights. Phases
  0-2 marked done with their tags (PLAN's Phase 1/2 labels are swapped
  against the tags; left as is).
- DECISIONS: D-054 Phase 3 scope and order (timing in D-028 superseded),
  D-055 spend definition (Spent, Paid back, Net).
- Fixes: HANDOFF decision range now D-001..D-055; import cheat sheet expects
  head `0003`. D-015's duplicated fragment is still there: it has been there
  since the entry was written, so there is no clean version to restore.

### 2026-11-15: Keep-alive moved off Render (D-053)

- The Render heartbeat failed every night: asleep, Render served its browser
  loading page to cron-job.org ("output too large") and never woke.
- Migration `0003` (Postgres only): schema `keepalive`, function
  `keepalive.ping()` (SECURITY DEFINER, `search_path = public, pg_temp`),
  EXECUTE revoked from PUBLIC and granted to `anon` when that role exists,
  RLS enabled on `heartbeat`.
- Tests (Postgres CI job): `ping()` as `anon` moves `last_seen`; `anon`
  cannot read `heartbeat` or `transactions`, even with Supabase-style SELECT
  grants; downgrade removes the schema; `alembic check` clean.
- `/health/db` and `PING_TOKEN` unchanged, for manual checks.
- Switch-over done and verified by you the same day: security check 8/8
  blocked (public 406, keepalive 404), cron test run 200, `last_seen` moved.
  Open: the first scheduled 03:30 run.
- CLAUDE.md: ask before starting Docker Desktop.

### 2026-11-14: Phase 2 lock-in, real import

- Your real import on Supabase (counts only): migration `0002` (head). Dry
  run equal to the import: read 2,543; skipped mms 451, otp 12, promotional
  61, unregistered_sender 1,102; raw new 917; parsed 720; unknown
  foreign_currency_deferred 44, no_parser_for_bank 153; is_money 679;
  transactions new 678, merged 1; candidates 18. About 6 min.
- Re-import (batch 3): raw new 0, duplicate 917, transactions 0.
  Reparse dry run: reparsed 0.
- Stats: import_batches 2, raw_messages 917, parse_results 917,
  transactions 678, transaction_sources 679, duplicate_candidates 18 (open).
  Active transactions: debit 539, credit 134, refund 5. Parse results:
  credit 134, debit 539, mandate 8, other_info 29, refund 6,
  upcoming_debit 4. Months 2026-01 to 2026-11. Batch ids start at 2 (the dry
  run used id 1; see data-model.md).
- Docs: full redacted file moved to the private folder (D-051); one cron
  heartbeat job with retries (D-052); PLAN phases 0-2 done; CHANGELOG.md;
  docs/HANDOFF.md; CLAUDE.md points to the handoff.
- Tags: `phase-0-done`, `phase-1-done`, `phase-2-done`.

### 2026-11-14: Phase 2 Part A, schema, import pipeline, dedupe

- Migration `0002`: `import_batches`, `raw_messages`, `parse_results`,
  `transactions`, `transaction_sources`, `duplicate_candidates`. BIGINT
  paise, timestamptz UTC, RLS enabled (no policies) on Postgres.
- Dedupe (D-046): raw `content_hash` (no source); transaction key on a
  per-payment reference (no account) or the raw message; fuzzy pairs only
  recorded (D-047). Found and fixed: H08/H13 references are mandate IDs that
  repeat monthly; hint `mandate_reference` (`hdfc-1.1.1`) keeps those
  charges apart.
- Importer: registry senders only, never OTP/promotional/MMS (D-049); batch
  commits; crash-safe re-run; `--dry-run` rolls back. "Never asks for OTP"
  advisories are no longer treated as OTPs (engine and redaction).
- Reparse: new result per stale message, ids stable, nothing deleted.
- CLI `python -m app.cli import-sms | reparse | stats`, counts only.
- Tests: invariants I1-I9; new CI job runs migrations, `alembic check` and
  the backend tests on Postgres 17.
- Docs: `docs/data-model.md`; DECISIONS D-046 to D-050.

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
