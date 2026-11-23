# Handoff

For a fresh Claude Code session with no memory of earlier work. Read this
first, then [OVERVIEW.md](OVERVIEW.md) (the one-page tour),
[NOTES.md](../NOTES.md) (status, cheat sheet, log) and the phase in
[PLAN.md](PLAN.md).

## Current state (premium run done, 23 Nov 2026)

- **Premium run is done, not pushed** (D-147 to D-152): pre-push safety (admin privacy,
  Profile facts, duplicate and export checks, a steadier cross-origin check), Analytics in
  Insights (`GET /api/v1/analytics`), rules ("All payments to <name>", Your rules with Undo)
  and per-credit Paid back answers (`owner_roles.scope`, migration `0018`), robustness (last
  X-Forwarded-For hop, input limits, `app.cli doctor`, emoji copies of one SMS, the snapshot
  reads once: 47 statements), the visual audit at 360 and 1280 px, the first-run checklist
  and About. Alembic head `0018`. Owner steps: NOTES, "After the premium deploy".
- **5F part 1 is done, not pushed** (D-146): the Insights tab (Export as CSV or Excel from
  `GET /api/v1/export`, Profile, Admin).

- **Phase 5B-2 is done, not pushed** (D-139 to D-144,
  [design/phase-5b2-phone.md](design/phase-5b2-phone.md)): the phone uploads a new bank
  SMS at once (expedited, replacing a backoff), hourly catch-up, an inbox `_id` cursor, a live
  copy after 2 minutes joined to its inbox copy on the server (`raw_messages.origin`), the
  queue kept while disconnected and across sign-out (same login reconnects by itself),
  payment notifications from the ingest answer's `new_transactions`, a status screen with an
  event log; the snapshot's ETag from a per-owner data version (`data_versions`), so a 304
  never builds it. Alembic head `0017`. Owner steps: NOTES, "After the 5B-2 deploy".
- **Phase 5B-1 is done, not pushed** (D-133 to D-138): To-do newest first;
  refresh on focus, after the outbox, every 60 s while visible, pull-to-refresh
  (`src/pull.ts`); People only when clearly personal (`categorise-1.3.0`); a
  payback guess needs a payment to the person in the 90 days before, and
  payback links in the snapshot (`reconcile-1.7.0`, `credits.payback_links`);
  Paid back / Not paid back in the transaction sheet (the To-do sender
  answer); Invested totals, the Investment tag and "Count investments in
  Spent" (`owner_settings`, migration `0016`); owner commands `category-diff`
  and `payback-review` (PRIVATE CSV outside the repo). Owner steps: NOTES
  cheat sheet, "After the 5B-1 deploy". Next: 5B-2 (the phone, Kotlin).
- **Phase 5C is done, not pushed** (D-128 to D-132): several users. Logins
  live in `app_users` (migration `0015`; `AUTH_USERS` seeds the admin on the
  first request, then is only a fallback); testers join with an invite code
  the admin makes in the app; `POST /api/v1/signup` creates the Supabase login
  through the Auth Admin API (`SUPABASE_SECRET_KEY`, Render only); Delete my
  account deletes every row of that owner, then the login
  (`app/pipeline/account.py`, the one deletion allowed); first-run sheet,
  Settings, "What Flash stores" (`docs/privacy.md`). Isolation test over every
  route: `tests/test_isolation.py`. Owner commands take `--owner <owner_id>`
  (default: the admin). New owner commands: `sender-survey`, `auth-cleanup`.
  5A is pushed but not yet verified on the phone. Next: 5B on the phone, 5D
  testers.

- **Phase 5A is done, not pushed**: Flash on Android, the owner's phone
  first ([design/phase-5a-android.md](design/phase-5a-android.md), D-122 to
  D-127). Devices and ingest-only device tokens (migration `0014`), bank-only
  `POST /api/v1/ingest/sms` stored exactly as import-sms, a Capacitor 8.6.2
  shell in `mobile/android` (appId `app.flashexpense.android`), a Kotlin SMS
  plugin (history from a cursor, live receiver, SQLite queue, WorkManager,
  6-hourly catch-up, Keystore-sealed token), the Bank SMS sheet, HDFC
  `hdfc-1.2.0`. The owner's steps (push, Render `CORS_ORIGINS`, reparse,
  build with the Supabase settings, `adb install -r`, first run): NOTES
  cheat sheet, "Android app". Next ([PLAN.md](PLAN.md)): 5B reliability on
  the real phone, 5C several users, 5D 2-3 testers; Phase 6 the Play Store.
  Still waiting for the planner: `statement-import --apply`,
  `statement-names --apply`, the September re-check.
- Android build: Gradle 9.9.2, Android Gradle Plugin 9.5.1 (JDK 25 at
  `D:\Applications2\AndroidStudio\jbr`; the template's Gradle 8.14.3 cannot
  run on it), compileSdk and targetSdk 36, minSdk 26; `npm run android:apk`
  from `frontend\` builds the debug APK. Agents never run adb against a
  device.
- **Phases 0 to 4 are done.** Phase 4 in one page:
  [retro/phase-4.md](retro/phase-4.md) (what shipped, what broke, the rules).
- **Phase 4 by step:** 4C install and update (D-085 to D-087); 4B offline
  first: phone copy, outbox, offline launch (D-088 to D-095); 4E people
  (D-096 to D-098); 4F other banks, the CORS fix, the stuck-queue fix,
  writes before the recompute, SBI parser (D-099 to D-108); 4H history
  without AI attribution, person sheet actions, payback-audit by any answer,
  warm job retired, UI tokens (D-109 to D-113); 4A statement check,
  own-account transfers, statement names (D-114 to D-116); 4Z statement
  reader 1.1.0 and import, It's me and Investments, categories from names,
  git backup deleted after the verified push (D-117 to D-121).
- **History** was rewritten on 21 Nov to drop AI attribution lines (D-109;
  old to new SHAs in [history-rewrite-20261121.md](history-rewrite-20261121.md));
  the push was verified and the git backup deleted (D-121). Enable the hook
  once per clone: `git config core.hooksPath .githooks`.
- Engine versions: parsers `hdfc-1.2.0`, `sbi-1.0.0` and `generic-1.0.0`
  (other banks), `merchant-1.1.1`, `reconcile-1.7.1`, `categorise-1.3.0`;
  statement reader `stmt-hdfc-1.1.0`.
- Alembic head: `0018` (0017 raw_messages.origin, data_versions; 0018 owner_roles.scope; `0011` was not used).
- Decisions: D-001 to D-152 ([DECISIONS.md](DECISIONS.md)).
- Test routine: backend on SQLite and Postgres 17, scripts, ruff, frontend
  lint/typecheck/tests/build, the cross-origin check
  (`node scripts/cross-origin-check.mjs` from `frontend\`, which covers the
  Android origin `https://localhost` since 5A), and the Kotlin unit tests
  (`.\gradlew.bat testDebugUnitTest` from `mobile\android\`).
- Cron: only the 03:30 IST Supabase heartbeat. The API warm job is
  retired (D-112: its pings got 503 and never woke Render; the phone copy
  covers cold starts).
- Live: app https://flash-expense-tracker.vercel.app, API
  https://flash-expense-tracker.onrender.com (more under "Live URLs").
- The app: real login (Supabase Auth) and data (`/api/v1`), every screen,
  category colours, the ring chart and the FLA$H logo
  ([ui-spec.md](ui-spec.md), [api.md](api.md)). Installable; a new deploy
  shows "New version available" and Home shows the build id (D-085 to
  D-087). Screens read one snapshot (`/api/v1/sync/snapshot`) kept on the
  phone in IndexedDB and open from it at once; every money figure comes
  from the server (D-088 to D-090). Every owner action goes through an
  outbox on the phone with an Idempotency-Key, shown as "Saved on phone · syncing"
  (D-091 to D-094; [design/phase-4b2-outbox.md](design/phase-4b2-outbox.md)).
  Launch never waits on the network: identity from the stored session, the
  phone copy at once, an error boundary, a 3 s watchdog, never a blank
  screen (D-095). The owner names people and joins a name and a UPI ID into
  one person, offline too (D-096;
  [design/phase-4e-people.md](design/phase-4e-people.md)).

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
| `payback-audit`, `--fix`, `--fix --apply` | Paybacks no owner answer confirmed (D-099): counts, dry run, repair |
| `category-diff --out <csv>`, `payback-review --out <csv>` | 5B-1 reviews (D-137): counts on screen, rows to a PRIVATE CSV outside the repo |
| `bank-survey`, `generic-preview` | Messages by bank, kind and parse status; what the generic parser would read (counts) |
| `redact-sample --family <bank>`, `--approve <bank>` | A redacted sample of one bank to `D:\FlashPrivate\review\`, then into `data\sample\` (D-100) |
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
| Keep-alive | cron-job.org calls `keepalive.ping()` via the Data API (D-053); no job keeps Render warm (D-112) | |

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
  app/api/ops.py      every owner write: Idempotency-Key (client_ops), deferred recompute (D-091 to D-094)
  app/api/users.py    5C: signup, invites, members, account/delete (D-128 to D-131); supabase_admin.py: the Auth Admin API
  app/api/devices.py  5A: /api/v1/devices (login) and /api/v1/ingest/sms (device token only, D-122, D-123)
  app/engine/shared/  bank_senders.json: the sender list, read by senders.py and packed into the APK
  app/config.py       settings from env / backend/.env (DATABASE_URL, PING_TOKEN, CORS_ORIGINS, OWNER_ID)
  app/db.py           engine, SessionLocal, Base
  app/models.py       ORM models; UtcDateTime column type
  app/engine/         stdlib-only parser: senders, money, timeparse, filters (OTP), models, parsers/{base,hdfc}, merchant (+ brands.json), reconcile (roles and links), categorise
  app/pipeline/       dedupe.py (pure rules), store.py (per-message ingest), reparse.py, owner_load.py (owner file -> owner tables), recompute.py (derive -> derived tables)
  app/importers/      sms_backup.py (streaming XML importer)
  app/cli.py          python -m app.cli import-sms | reparse | stats | merchant-stats | merchant-review | reconcile-stats | owner-load | recompute | reconcile-review | owner-export | totals | category-stats | category-review | credit-review
  alembic/versions/   0001 heartbeat, 0002 import pipeline tables, 0003 keepalive.ping(), 0004 owner tables, 0005 derived tables, 0006 categories and labels, 0007 client_ops, 0008 people and the label limit, 0009 owner checks, 0010 recompute marks
  tests/              pytest; conftest forces a throwaway SQLite DATABASE_URL
frontend/           Vercel root (docs/ui-spec.md): src/api (Api interface; http.ts real adapter, fake.ts demo adapter for VITE_DEMO=1 in dev), src/auth.ts (Supabase login; identity from the stored session at boot), src/boot.ts (boot path, first-screen time, boot errors, watchdog), src/crash.ts (error boundary), src/screens (Ring.tsx chart), src/brand.tsx ($ mark, FLA$H wordmark), src/lib (money, IST dates), src/view.ts (URL state), src/icons (Lucide SVGs), src/pwa.ts (manifest and service worker options, build id), src/update.ts (update bar), src/data (local.ts: the IndexedDB phone copy; store.ts: snapshot, refresh, freshness, timings; outbox.ts: owner actions, drain, markers), src/screens/Speed.tsx (Speed sheet), src/screens/People.tsx (person sheet)
scripts/            standalone, stdlib: redact_sms.py, shape_survey.py, parse_coverage.py (+ tests); backup_db.ps1 (owner: pg_dump via Docker)
infra/              render.yaml (reference copy), README.md (setup and runbook)
docs/               PLAN, DECISIONS (D-001..D-108), design/phase-4e-people.md, design/logo-options.html, engine.md, data-model.md, api.md, design/phase-3-backbone.md, templates/hdfc.md, this file
mobile/             the Android app (5A): android/ Gradle project, Kotlin SMS plugin (mobile/README.md)
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

The API warm job ("Flash API warm 07-01 IST") is retired (D-112): its pings
got 503 from the sleeping free service and never woke it; the phone copy
covers a cold start. The daily 03:30 IST Supabase keepalive job stays.

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
   HDFC `hdfc-1.2.0`, SBI `sbi-1.0.0`, other banks `generic-1.0.0`.
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
2. After the 4F-A deploy the owner runs the counts in the NOTES cheat sheet
   ("Other banks and paybacks"): `payback-audit`, `bank-survey`,
   `generic-preview`, `redact-sample`. The planner decides on
   `payback-audit --fix --apply`, a reparse and 4F-B. (Logo: C picked, C2
   applied in 4F-A.)
3. November data ends at the 14 Nov 2026 export; live SMS is Phase 5.
4. Not counted: 153 messages from banks without a parser (SBI, ICICI, India
   Post, Kotak, PhonePe) and 44 foreign-currency messages (D-035). Since
   4F-A the generic parser reads the banks among them after a reparse (not
   PhonePe, an app); `generic-preview` counts what it would read first.
5. Close category colour pairs (OKLab distance about 4 to 5, such as card
   bill and uncategorised); icons and names carry identity (D-081).
6. Not checked: real iOS, screen readers, 200 % text on the 3F-3 screens.
   The 4C update bar and version line were checked at 360 px, light, dark
   and 200 % in headless Edge only; the 4B-1 screens in headless Edge at
   390 px on demo data; the 4B-2 outbox on demo data in headless Edge (taps
   with the demo server failing, drain once it answers). Speed sheet timings
   and an offline tap on a real phone are still to come.
7. Accepted risk: npm audit, 4 moderate findings, build-time only: glob
   11.1.0 (GHSA-3g3m-2fjr-6pw4) and minimatch 10.2.6 and 5.1.9
   (GHSA-g3hv-75wg-m249), via vite-plugin-pwa 2.0.0 and workbox-build 7.4.1,
   the newest releases. No patched release in the same major, so no
   override. Recheck when Workbox ships a fix; never `npm audit fix --force`.
8. After the 4E deploy: Render runs migration `0008` (it stops if a label is
   longer than 30 characters; the live table has none). The first owner
   write, or `python -m app.cli recompute`, rewrites the derived rows for
   `reconcile-1.4.0` and `categorise-1.1.0`; until then Home says "Totals
   are being updated".
9. The Supabase free plan has no backups; the owner runs
   `scripts/backup_db.ps1` (D-084).
10. The owner's To-do backlog (about 100 items) to work through on the
    phone, now with chips, "See payments", Name and Same as… (4E).
11. The owner doubts the October People total: verify it person by person.
12. Vercel: `VITE_API_URL` is saved as a Secret. The owner changes it to a
    plain variable and redeploys with the build cache off.
13. HDFC UPI credit SMS carry only a VPA, sometimes masked with "*" by the
    bank (22 of 22 in the redacted sample; 6 masked). Since 4E the owner
    names the person and joins the VPA to their name on the phone (D-096);
    the statement (4A) can confirm who sent what.
14. Later list: a friendlier Home, still minimal; revisit with 4D.

Known limits: HDFC and INR only; the card bill pair rule waits for credit
card SMS; the server sleeps when idle (about a minute to wake; the phone
copy covers it, D-112); import takes about 6 minutes for 917
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
