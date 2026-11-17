# Infra

Everything runs on free tiers, co-located in Singapore. Do the sections in
order: each one gives you a value that the next one needs.

| Piece    | Host                | Root dir    | Region                     |
| -------- | ------------------- | ----------- | -------------------------- |
| Database | Supabase (Free)     | n/a         | Southeast Asia (Singapore) |
| Backend  | Render (Free web)   | `backend/`  | Singapore                  |
| Frontend | Vercel (Hobby)      | `frontend/` | global CDN                 |
| Pings    | cron-job.org (Free) | n/a         | n/a                        |

**Deployed 13 Nov 2026.** Live: app https://flash-expense-tracker.vercel.app,
API https://flash-expense-tracker.onrender.com. The Render service
`flash-expense-tracker` was created by hand in the dashboard (section 2), not
from the Blueprint. [render.yaml](render.yaml) is the reference copy of its
settings; keep it in sync when you change the service. How the pieces connect:
[NOTES.md, Architecture](../NOTES.md#architecture).

Keep these in a password manager, never in git or chat:
`DATABASE_URL`, `PING_TOKEN`, the Supabase database password, the Supabase
publishable key.

## 0. Generate PING_TOKEN

In PowerShell:

```powershell
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString('x2') })
```

This prints 64 hex characters. Save it as `PING_TOKEN`. It is sent in the
`X-Ping-Token` header, never in a URL.

## 1. Supabase (database)

1. Go to https://supabase.com/dashboard and sign in with GitHub.
2. Click **New project**.
   - **Organization**: your personal org.
   - **Project name**: `flash`.
   - **Database password**: letters and digits only (no `#`, `%`, `@` and so
     on; they break `DATABASE_URL` parsing). Make it long, then copy it.
   - **Region**: **Southeast Asia (Singapore)**.
   - Click **Create new project** and wait until it is ready (about 2 minutes).
3. Find the connection string:
   - Click **Connect** in the top bar of the project.
   - Open the **Connection String** tab. Set **Type** to `URI`.
   - Under **Session pooler**, copy the string. It looks like
     `postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres`.
   - Use the Session pooler, not "Direct connection". The direct host is
     IPv6-only and Render free cannot reach it.
4. Build `DATABASE_URL` from it:
   - Replace `[YOUR-PASSWORD]` with the password. If the password has
     characters such as `@ : / ? # %`, percent-encode them.
   - Add `?sslmode=require` at the end.
   - The `postgresql://` scheme is fine as is; the app switches it to the
     pinned psycopg driver.
   - Result: `postgresql://postgres.<ref>:<password>@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require`
5. The app talks to Postgres directly and does not need the Data API. It is
   on only for the keep-alive and exposes only the `keepalive` schema; set it
   up in section 4 (D-053). Until then, leave **Enable Data API** off.

## 2. Render (backend)

1. Go to https://dashboard.render.com and sign in with GitHub.
2. Click **New > Web Service**.
3. Under **Git Provider**, choose GitHub. Allow access to
   `Karthik-Flash/flash-expense-tracker`, then select it.
4. Fill the form:
   - **Name**: `flash-expense-tracker` (the URL becomes
     `https://flash-expense-tracker.onrender.com`).
   - **Language**: `Python 3`.
   - **Branch**: `main`.
   - **Region**: `Singapore (Southeast Asia)`.
   - **Root Directory**: `backend`.
   - **Build Command**: `pip install -r requirements.txt && alembic upgrade head`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: `Free`.
5. Under **Environment Variables**, add all of these **before** the first
   deploy (the build runs the migration, so it needs `DATABASE_URL`):
   - `PYTHON_VERSION` = `3.12.12`
   - `DATABASE_URL` = the value from step 1.4
   - `PING_TOKEN` = the value from step 0
   - `CORS_ORIGINS` = `http://localhost:5173` for now. You replace it in step 3.5.
6. Open **Advanced**. Set **Health Check Path** to `/health`. Leave
   **Auto-Deploy** on **After CI Checks Pass** (D-050).
7. Click **Deploy Web Service**. In the build log, look for
   `Running upgrade  -> 0001, heartbeat table` (first deploy only), then wait
   for "Live".
8. Check from PowerShell (replace the service name; paste the token when asked):
   ```powershell
   Invoke-RestMethod https://<your-service>.onrender.com/health
   $t = Read-Host "PING_TOKEN"
   Invoke-RestMethod https://<your-service>.onrender.com/health/db -Headers @{ "X-Ping-Token" = $t }
   ```
   Expect `status: ok`, then `db: ok` with a `latency_ms` value.

Notes:

- Migrations run once per deploy, in the build. If a migration or the
  database fails, the deploy fails and the previous version keeps serving.
- A free service sleeps after 15 minutes without traffic. The next request
  waits for a cold start (often 30 to 60 seconds). The frontend shows
  "Starting up, this can take about a minute" during that time.
- `/health/db` answers 401 for a missing or wrong `X-Ping-Token`, 503
  "ping token not configured" if `PING_TOKEN` is unset, and 503 "database
  unavailable" if Postgres is unreachable.
- `infra/render.yaml` describes the same service as a Blueprint. Use either the
  dashboard steps or the Blueprint, not both.

## 3. Vercel (frontend)

1. Go to https://vercel.com/new and sign in with GitHub.
2. Under **Import Git Repository**, find `flash-expense-tracker` and click
   **Import**. If it is not listed, click **Adjust GitHub App Permissions** and
   allow the repo.
3. Configure the project:
   - **Root Directory**: click **Edit**, select `frontend`, then **Continue**.
   - **Framework Preset**: `Vite` (detected automatically).
   - Leave the build and output settings at their defaults.
   - **Environment Variables** (all three are public; they end up in the
     browser bundle):
     - `VITE_API_URL` = `https://<your-service>.onrender.com` (no trailing slash)
     - `VITE_SUPABASE_URL` = `https://<project-ref>.supabase.co`
     - `VITE_SUPABASE_PUBLISHABLE_KEY` = the project's publishable key
       (`sb_publishable_...`, Project Settings > API Keys)
     Never set `VITE_DEMO` on Vercel; a production build ignores it anyway.
4. Click **Deploy**. Note the production URL, for example
   `https://flash-expense-tracker.vercel.app`.
5. In Render, open the service, then **Environment**. Set `CORS_ORIGINS` to the
   Vercel URL. Add `,http://localhost:5173` if you also want local dev to
   reach the deployed API. Click **Save, rebuild, and deploy**.
6. Open the Vercel URL. It shows the login screen; sign in after section 5.

The `VITE_` variables are baked in at build time. After you change one in
Vercel, redeploy the frontend.

## 4. cron-job.org (keep Supabase active)

Supabase pauses free projects after 7 days without activity. Once a day,
cron-job.org calls `keepalive.ping()` through the Supabase Data API. The
function writes the heartbeat row, which counts as activity (D-053). Render
is not involved.

Do this after migration `0003` reached Supabase: the Render deploy log shows
`Running upgrade 0002 -> 0003`.

1. **Supabase Data API, one schema only.** Supabase > **Project Settings >
   Data API**:
   - Switch **Enable Data API** on.
   - **Exposed schemas**: remove every entry (`public`, `graphql_public`) and
     add `keepalive`. It must be the only one. Save.
   - Never expose `public`. Supabase grants `anon` access to public tables
     by default, and `alembic_version` has no RLS.
2. **Publishable key.** Supabase > **Project Settings > API Keys**: copy the
   publishable key (`sb_publishable_...`). It goes only into your password
   manager and the cron-job.org header, never into git or chat. Note the
   project ref: the `<ref>` in `https://<ref>.supabase.co`.
3. **cron-job.org account** (once): sign up at
   https://console.cron-job.org/signup, confirm the email, and set
   **Settings > Time zone** to `Asia/Kolkata`.
4. **The job.** Edit "Flash DB heartbeat" (or **Cronjobs > Create cronjob**):
   - **Title**: `Flash DB heartbeat`.
   - **URL**: `https://<ref>.supabase.co/rest/v1/rpc/ping`
   - **Execution schedule**: every day at `03:30`.
   - **Notifications**: **execution of the cronjob fails** ON, **the cronjob
     will be disabled because of too many failures** ON.
   - **Advanced**: **Request method** `POST`. **Headers**: `apikey` = the
     publishable key; `Content-Profile` = `keepalive`; `Content-Type` =
     `application/json`. Remove the old `X-Ping-Token` header. **Request
     body**: `{}`.
   - Save.
5. Click **Test run**. Expect HTTP 200 with `{"ok" : true}`.
   - 401: the `apikey` header is missing or wrong.
   - 404 `PGRST202`: stale schema cache. In the SQL editor run
     `NOTIFY pgrst, 'reload schema';` and test again.
   - 406 `PGRST106`: `keepalive` is not in the exposed schemas, or the
     `Content-Profile` header is missing.
6. **Security check.** Run it from PowerShell and keep the output:

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

7. Backstop: Supabase emails a warning before it pauses an idle project.

History: until 15 Nov 2026 the job called Render's `/health/db` (D-023,
D-052). Asleep, Render served its browser loading page to cron-job.org,
which failed with "output too large", and Render never woke. `/health/db`
and `PING_TOKEN` stay for manual checks.

There are no scheduled GitHub workflows, on purpose.

## 5. Login (Supabase Auth)

The app signs in with Supabase Auth (email and password, one user); the API
checks the token (D-078).

1. Supabase > **Authentication > Sign In / Providers**: keep **Email**
   enabled; turn **Allow new users to sign up** off; **Confirm email** may
   stay on (you confirm your own user in step 2).
2. **Authentication > Users > Add user > Create new user**: your email and
   a strong password (password manager), **Auto Confirm User** on. Copy the
   user's **UID**.
3. **Authentication > URL Configuration**: **Site URL** =
   `https://flash-expense-tracker.vercel.app`.
4. **Project Settings > JWT Keys**: the current signing key must be an
   asymmetric **ECC (P-256)** key (ES256). The API accepts no other kind. If
   the project still signs with the legacy HS256 secret, create an ECC key
   and rotate to it.
5. Render > service > **Environment**: `SUPABASE_URL` =
   `https://<project-ref>.supabase.co` and `AUTH_USERS` =
   `<UID from step 2>:<OWNER_ID>` (the owner id the data was imported with).
   Save, rebuild and deploy.
6. Open the Vercel URL and sign in. A login that is not in `AUTH_USERS`
   sees "This account has no access".

## Runbook

Test commands used below (PowerShell):

```powershell
$u = "https://flash-expense-tracker.onrender.com"
Invoke-RestMethod "$u/health"
$t = Read-Host "PING_TOKEN"
Invoke-RestMethod "$u/health/db" -Headers @{ "X-Ping-Token" = $t }
```

### Email: Supabase "project will be paused"

1. Open https://supabase.com/dashboard and the project.
2. Open cron-job.org, job "Flash DB heartbeat", and check its history. Find
   when it last returned 200.
3. If the project already shows **Paused**, click **Resume** and wait until it
   is active.
4. In cron-job.org click **Test run**. Expect `{"ok" : true}`.
5. Fix whatever stopped the heartbeat (see the next entry).

### Email: cron-job.org "job failed" or "job disabled"

1. In cron-job.org, open the job's history and the failed run's response.
   - 401: the `apikey` header is missing or the key was rotated. Copy the
     current publishable key from Supabase (password manager too).
   - 404 `PGRST202` or 406 `PGRST106`: check section 4, steps 1 and 5.
   - 5xx or timeout: Supabase may be paused or down. Check the dashboard;
     click **Resume** if it is paused.
2. Click **Test run**, expect 200 and `{"ok" : true}`.
3. If the job was disabled, switch it back to **Enabled**.
4. After any change to the Data API settings, run the security check
   (section 4, step 6).

### Rotate PING_TOKEN

1. Generate a new token (section 0). Save it in the password manager.
2. Render > service > **Environment**: set `PING_TOKEN` to the new value, then
   **Save, rebuild, and deploy**. Wait for **Live**.
3. Run the `/health/db` test with the new token (expect 200). The cron job
   does not use `PING_TOKEN`.

### Rotate the Supabase publishable key

1. Supabase > **Project Settings > API Keys**: create a new publishable key.
   Save it in the password manager.
2. cron-job.org > "Flash DB heartbeat" > **Advanced** > **Headers**: set
   `apikey` to the new key. **Test run**, expect 200.
3. Delete the old publishable key in Supabase.

### Rotate the database password

1. Supabase > **Project Settings > Database** > **Reset database password**.
   Letters and digits only. Save it in the password manager.
2. Update `DATABASE_URL` in `backend/.env` (local) with the new password.
3. Render > service > **Environment**: update `DATABASE_URL`, then
   **Save, rebuild, and deploy**. Wait for **Live**.
4. Run the `/health/db` test. Expect `db: ok`.

### Render free hours or suspension email

1. Keep only one free web service on this Render account. Free instance hours
   are shared by every free service in the workspace.
2. Render > **Billing**: check free instance hours used this month.
3. If the service is suspended, wait for the monthly reset or remove other
   free services; then check it shows **Live** and run the `/health` test.
