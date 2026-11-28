# Operations

Every command the owner (and a developer) runs, in one place: the live system, local runs and
checks, the Android build, owner commands, backups, and the test plan after a deploy. Why
things work the way they do: [Flashexpensetracker_Explained.md](../Flashexpensetracker_Explained.md)
and [DECISIONS.md](DECISIONS.md). What each owner command prints is counts only unless a
step says PRIVATE; never paste a PRIVATE file.

All commands run from the repo root in PowerShell unless a step says `backend\` or
`frontend\`.

## Live system

### Links

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

### Gotchas

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


## Develop and check

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

### Database migrations (from `backend\`)

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head                               # apply all migrations
.\.venv\Scripts\python.exe -m alembic current                                    # show applied revision
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "what changed"  # after a model change
```

Render's build runs `alembic upgrade head` once per deploy.

### Dependencies

```powershell
cd frontend; npm ci; cd ..                      # install exactly what package-lock.json says
cd frontend; npm install some-pkg; cd ..        # .npmrc save-exact pins it automatically
```

Python: edit the `==` pin in `backend\requirements*.txt`, then
`backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt`.

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

### Speed check (5G, D-153)

```powershell
cd frontend; node scripts/perf-check.mjs     # about 10 minutes: FAKE data (900 payments), Edge, CPU 4x, slow 3G
```

Prints, in ms from the tap to the frame that shows it: a row to its sheet and Change
category to the list (warm), the same after a cold start from a deep link, a just-notified
payment without and with the notification's basics, and each snapshot answer's size on the
wire and unpacked. The list should open in under 300 ms in every case.

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


## Android

### Android app: build, install, update (D-122 to D-127)

Steps 1 and 2 once per setup; step 3 onwards for every new version.

1. **Render env** (dashboard, service, Environment): `CORS_ORIGINS` ends with
   `,https://localhost` (exactly, no port: the Android WebView's origin), so the line reads
   `http://localhost:5173,https://flash-expense-tracker.vercel.app,https://localhost`.
2. **Sign-in settings for the build**: `VITE_SUPABASE_URL` and
   `VITE_SUPABASE_PUBLISHABLE_KEY` in `frontend\.env` (the same values as on Vercel).
3. **Build the APK** (from `frontend\`). It needs the Supabase sign-in
   settings: put `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` (the
   same values as on Vercel) in `frontend\.env`; the build stops without
   them. The API address is built in (the Render URL).
   ```powershell
   cd frontend; npm ci; npm run android:apk      # prints APK: ...\mobile\android\app\build\outputs\apk\debug\app-debug.apk
   ```
4. **Install over USB** (phone: Settings > About phone > tap Build number 7
   times; Developer options > USB debugging on; plug in, allow this computer):
   ```powershell
   adb devices                                   # the phone listed as "device"
   adb install -r D:\Projects\FinancesApp\mobile\android\app\build\outputs\apk\debug\app-debug.apk
   ```
   The same command installs a newer APK over the old one (data kept). The
   APK is signed with this laptop's debug key
   (`%USERPROFILE%\.android\debug.keystore`): keep it; another key means
   uninstall and install again (the phone's queue and token go).
5. **First run on the phone**: open Flash, sign in. Home shows "Getting
   started" (D-152): tap Set up next to "Set up Bank SMS", then "Allow SMS
   access". The list ticks itself and goes away once all four lines are done.
   - If Android says "Restricted setting" (or nothing happens): "Open App
     info", ⋮ (top right) > Allow restricted settings, then Permissions >
     SMS > Allow; back in Flash, "Check again".
   - The phone connects by itself (needs a connection). Pick the period:
     "From your newest message on the server" (the default), or 3, 6 or 12
     months; "Start reading".
   - Battery: when the sheet shows the battery card, "Open App info" >
     Battery > Unrestricted (Samsung).
6. **Pass looks like**: in Bank SMS (or the Speed sheet's Bank SMS block)
   "SMS permission allowed", "This phone connected", "Waiting on phone 0"
   within a few minutes, "Last upload <time>, N new", "Last error –". Then pay
   something small by UPI with the app open: it shows within a minute. Paste to the
   planner only the Bank SMS rows (codes, counts, times); never names or amounts.

Revoke a lost phone: Bank SMS sheet (any device, also the laptop browser),
Phones, Revoke. Signing out on the phone revokes it and wipes its token and
queue. Kotlin checks (from `mobile\android\`): `.\gradlew.bat
testDebugUnitTest`; on a connected phone only: `.\gradlew.bat
connectedDebugAndroidTest`.

### Android Studio: what it is for here

Android Studio is installed for its parts, not as the build tool:
- **Its JDK** (`D:\Applications2\AndroidStudio\jbr`, Java 25) runs Gradle. Set
  `$env:JAVA_HOME = 'D:\Applications2\AndroidStudio\jbr'` before running `gradlew.bat` by hand.
- **The Android SDK** at `D:\Android\Sdk` (platform 36, build tools, and `platform-tools\adb.exe`).
  `mobile\android\local.properties` (git-ignored) points Gradle at it: `sdk.dir=D:\\Android\\Sdk`.
  Keep these up to date with Studio's SDK Manager.
- **Builds** go through `npm run android:apk` from `frontend\` (web app, `cap sync`, Gradle
  with the versionCode), never Studio's Run button, so the version and the bundled web app are
  always right. Install with `adb install -r ...` (this file, "Android app").
- **Logcat** (optional, for a problem on the phone): File > Open > `mobile\android`, wait for the
  Gradle sync, plug in the phone, View > Tool Windows > Logcat, filter
  `package:app.flashexpense.android`. Bank SMS > "Copy diagnostics" in the app is usually
  enough and safe to paste; Logcat lines can hold SMS text, so never paste them.
- **When Studio offers to upgrade** the Android Gradle Plugin or Gradle: say no. The versions
  are pinned (AGP 9.5.1, Gradle 9.9.2, Capacitor 8.6.2); an upgrade is a planned change.
- **Kotlin tests** without Studio: from `mobile\android\`, `.\gradlew.bat testDebugUnitTest`.
  Stop the background Gradle process afterwards with `.\gradlew.bat --stop`.
- **Unplugging the phone**: safe whenever no `adb install` is running. `adb kill-server`
  stops the idle adb background process if you want it gone.

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

### Phone copy and speed (D-089, D-090)

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


## Accounts, data and backups

### Several users: invites, testers, deleting an account (D-128 to D-132)

1. **Render env**: `SUPABASE_SECRET_KEY` = the project's secret key (Supabase dashboard,
   Project Settings > API Keys, "Secret keys", `sb_secret_...`). Server only: never in
   Vercel, `frontend\.env`, a chat or a file in git. `AUTH_USERS` is only a fallback for
   the admin's first sign-in (D-129).
2. **The admin**: the login in `AUTH_USERS` becomes the admin row of `app_users` the
   first time it opens the app. Insights > Admin shows "People who use Flash".
3. **Invite a tester**: Insights > Admin > People who use Flash > New invite; send the
   code (shown once) privately. On the sign-in screen the tester taps "Have an invite
   code?", enters email, password (8 or more) and the code. Revoke an unused code in the
   same sheet.
4. **Delete my account**: Insights > Profile > Delete my account (the admin's own account
   cannot be deleted from the app).
5. **Survey of HDFC sender codes** (from `backend\`, SAFE TO PASTE: codes and
   counts only):
   ```powershell
   .\.venv\Scripts\python.exe -m app.cli sender-survey --contains HDFC --input D:\FlashPrivate\raw
   ```
   A row with `registered NO` and debit or credit counts is a missing HDFC
   sender; paste it to the planner (nothing is added without the planner).
6. If a deleted account's login could not be removed (the server log says
   "login deletion pending"):
   `.\.venv\Scripts\python.exe -m app.cli auth-cleanup` (counts only).

Owner commands now work on one owner's data: `--owner <owner_id>` before the
command, else the admin, else `OWNER_ID`. For your own data nothing changes.

### Back up and restore (you run these; agents never do)

Back up (reads `DATABASE_URL` from `backend\.env`, prints only the file name and size;
since 5G it starts Docker Desktop itself and waits up to 3 minutes, keeps the newest 12
dumps and deletes only older `flash-YYYYMMDD-HHmm.dump` files, and adds one line per run to
`D:\FlashPrivate\backups\backup.log`; exit code 1 when no dump was made, D-157):

```powershell
cd D:\Projects\FinancesApp
powershell -ExecutionPolicy Bypass -File scripts\backup_db.ps1
# flash-20261117-2210.dump  0.4 MB   -> D:\FlashPrivate\backups\
```

Weekly, by itself (once; every Sunday 21:00 while you are logged in; a missed run starts
when the laptop is next awake):

```powershell
cd D:\Projects\FinancesApp
powershell -ExecutionPolicy Bypass -File scripts\register_backup_task.ps1
Start-ScheduledTask -TaskName 'Flash weekly backup'                         # test it now
Get-ScheduledTask -TaskName 'Flash weekly backup' | Get-ScheduledTaskInfo   # LastTaskResult 0 = OK
Get-Content D:\FlashPrivate\backups\backup.log -Tail 5
Unregister-ScheduledTask -TaskName 'Flash weekly backup' -Confirm:$false    # to remove it
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

### Owner data and recompute (you run these; counts and field paths only)

The owner file is a **developer tool** (D-075): import and backup. Nothing
in the product needs it; the app answers through the API.

Your owner file lives at `D:\FlashPrivate\private\owner.json`. Copy the
shape of `docs\owner.example.json`; the keys are explained in
[docs/data-model.md](data-model.md), "Owner file". Never paste the file.

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

### Import pipeline (you run these; agents never touch Supabase or real data)

From `backend\`. `DATABASE_URL` comes from `backend\.env` (Supabase). The
input is a backup file or a folder of `*.xml` files (not searched
recursively). Every command prints counts only.

```powershell
cd backend
# 1. Migrate (Render also runs this on deploy; repeating is safe). Expect the newest (head)
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

### Statement check, transfers and statement names (from `backend\`)

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

### Other banks and paybacks (from `backend\`)

After an engine change the first read recomputes once by itself (D-102). Run these in
order; each prints counts only unless marked.

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

### Template survey (reads only the redacted sample)

```powershell
backend\.venv\Scripts\python.exe scripts\shape_survey.py --input data\sample\redacted_sample.json --senders HDFCBK,HDFCBN --output data\sample\hdfc_shapes.json
```

Output stays in `data\sample\` (gitignored). Same command for other banks with
their sender cores. Fixtures for parsers: `backend\tests\fixtures\sms\<bank>.json`
(fake values only; checked by `backend\tests\test_sms_fixtures.py`).

### PING_TOKEN

```powershell
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString('x2') })
```

Rotation steps: [infra/README.md](../infra/README.md), Runbook.


## After a deploy

### The owner's steps, in this order

The same every time; a release note in [CHANGELOG.md](../CHANGELOG.md) says which apply (a
migration, a recompute or a reparse).

1. **Backup** (from the repo root): `powershell -ExecutionPolicy Bypass -File scripts\backup_db.ps1`
   (it starts Docker Desktop itself).
2. **Push**: `git push`. Render waits for CI, then runs `alembic upgrade head` in its build.
3. **Deploy check**: `curl.exe -s https://flash-expense-tracker.onrender.com/health` shows
   `"status":"ok"` (wait about a minute if it is waking). Insights > About shows the same
   server version.
4. **Alembic** (from `backend\`): `.\.venv\Scripts\alembic.exe current` shows the newest
   migration with `(head)` (`0019` after Phase 5).
5. **Recompute** after an engine change: `.\.venv\Scripts\python.exe -m app.cli recompute`;
   **reparse** only after a parser change: `.\.venv\Scripts\python.exe -m app.cli reparse`.
6. **Review** (counts here; the CSV files are PRIVATE):
   - `.\.venv\Scripts\python.exe -m app.cli category-diff --out D:\FlashPrivate\review\category-diff.csv`
     (categorise-1.3.0 against the current rules);
   - `.\.venv\Scripts\python.exe -m app.cli payback-review --out D:\FlashPrivate\review\payback-review.csv`.
7. **Doctor**: `.\.venv\Scripts\python.exe -m app.cli doctor`. Pass: "problems 0".
8. **Banks with no parser yet**: `.\.venv\Scripts\python.exe -m app.cli no-parser`.
9. **APK** (from `frontend\`, the real Supabase values in `frontend\.env`): `npm run android:apk`,
   then `adb install -r D:\Projects\FinancesApp\mobile\android\app\build\outputs\apk\debug\app-debug.apk`.
10. **Weekly backup task** (once): `powershell -ExecutionPolicy Bypass -File scripts\register_backup_task.ps1`.

### Phone and web test plan (what "pass" looks like)

Phone (the APK from step 9):

1. **First run**: Home shows "Getting started" until Bank SMS is set up, notifications are
   allowed, battery is Unrestricted and the first SMS has synced; each line ticks itself
   and the card goes away when all are done.
2. **App open**: pay Rs 1 by UPI. Pass: a notification "Paid ₹1 to ..." within a minute, the
   payment in Transactions without touching anything; tapping the notification opens its
   sheet at once.
3. **Notification to category**: tap a notification's "Change category". Pass: the
   category list is on screen at once, even with mobile data off; the choice syncs later.
4. **App closed** (swiped away, screen off 5 minutes): pay Rs 1 again. Pass: the
   notification comes, and the payment is on the laptop within a few minutes.
5. **Same payee twice** within a minute: two notifications, two payments.
6. **Sign out and in** with the same login: no new Bank SMS setup; Bank SMS shows "This
   phone connected"; nothing paid meanwhile is missing.
7. **Airplane mode**, change a category, airplane mode off: "waiting to sync" shows, then
   clears; the change is on the laptop after a refresh.
8. **Back button**: a sheet closes first; on another tab Back goes to Home; on Home the app
   goes away with Android's animation.
9. **Insights > About** shows the versionCode the build printed; five tabs fit at normal
   and large text.
10. Anything wrong: Bank SMS > **Copy diagnostics** and paste it (codes and counts only).

Web (laptop):

1. **Analytics**: 6 months loads; a month's Spent in the table equals Home's Spent for that
   month; tapping its bar opens that month's Transactions.
2. **Rules**: a payment's category with "All payments to <name>" changes every payment to
   them; Insights > Profile > Your rules lists it; Undo restores the old category.
3. **Paid back, just this one** on a friend's credit: Net drops by that credit only.
   **This is income, just this one**: Income goes up, Net does not move.
4. **Leave as is** in To-do: the question leaves at once; the payment's sheet offers Ask
   again.
5. **Export** Excel for last month: it opens in Excel with Transactions and Summary sheets;
   Summary's Spent equals Home's Spent.
6. **Profile**: email, role, member since, payments, data range, last sync, phones and their
   last upload; About shows the app and server versions.
