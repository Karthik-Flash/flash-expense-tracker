# Infra

Everything runs on free tiers, co-located in Singapore. Do the sections in
order: each one gives you a value that the next one needs.

| Piece    | Host                | Root dir    | Region                     |
| -------- | ------------------- | ----------- | -------------------------- |
| Database | Supabase (Free)     | n/a         | Southeast Asia (Singapore) |
| Backend  | Render (Free web)   | `backend/`  | Singapore                  |
| Frontend | Vercel (Hobby)      | `frontend/` | global CDN                 |
| Pings    | cron-job.org (Free) | n/a         | n/a                        |

Keep these in a password manager, never in git or chat:
`DATABASE_URL`, `PING_TOKEN`, the Supabase database password.

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
   - **Database password**: click **Generate a password**, then copy it.
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
5. Turn off the Data API, because the app talks to Postgres directly. Go to
   **Project Settings > Data API** and switch **Enable Data API** off. Tables
   are then not reachable through the public REST URL.

## 2. Render (backend)

1. Go to https://dashboard.render.com and sign in with GitHub.
2. Click **New > Web Service**.
3. Under **Git Provider**, choose GitHub. Allow access to
   `Karthik-Flash/flash-expense-tracker`, then select it.
4. Fill the form:
   - **Name**: `flash-api` (the URL becomes `https://flash-api.onrender.com`,
     or with a suffix if that name is taken).
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
   **Auto-Deploy** on **On Commit**.
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
  "Server is waking up" during that time.
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
   - **Environment Variables**: `VITE_API_URL` = `https://<your-service>.onrender.com`
     (no trailing slash).
4. Click **Deploy**. Note the production URL, for example
   `https://flash-expense-tracker.vercel.app`.
5. In Render, open the service, then **Environment**. Set `CORS_ORIGINS` to the
   Vercel URL. Add `,http://localhost:5173` if you also want local dev to
   reach the deployed API. Click **Save, rebuild, and deploy**.
6. Open the Vercel URL. It shows "Backend online" (after a possible wake-up).

`VITE_API_URL` is baked in at build time. After you change it in Vercel,
redeploy the frontend.

## 4. cron-job.org (keep Supabase active)

Supabase pauses free projects after 7 days without activity. A daily call to
`/health/db` writes the heartbeat row, which counts as activity.

cron-job.org stops waiting after 30 seconds, and a Render cold start can take
longer. So one job wakes Render first, then the monitored job runs on a warm
service.

1. Go to https://console.cron-job.org/signup and create an account. Confirm
   the email.
2. Open **Settings** and set **Time zone** to `Asia/Kolkata`.
3. Create the wake-up job: **Cronjobs > Create cronjob**.
   - **Title**: `flash wake-up`.
   - **URL**: `https://<your-service>.onrender.com/health`
   - **Execution schedule**: **Custom**. Days: every day. Hours: `3`.
     Minutes: `27` and `28`. (Two calls: the first may time out while Render
     wakes; the second succeeds, so the job never builds up failures.)
   - **Notifications**: all off.
   - Click **Create**.
4. Create the monitored job: **Cronjobs > Create cronjob**.
   - **Title**: `flash db heartbeat`.
   - **URL**: `https://<your-service>.onrender.com/health/db` (no token in the URL).
   - **Execution schedule**: **Every day at** `03:30`.
   - **Notifications**: turn on **execution of the cronjob fails** and
     **the cronjob will be disabled because of too many failures**. Also turn
     on **execution of the cronjob succeeds after it failed before** to get an
     all-clear email.
   - Open the **Advanced** tab. Under **Headers**, add key `X-Ping-Token` with
     your `PING_TOKEN` as the value. Leave **Request method** on `GET`.
   - Click **Create**.
5. Open the heartbeat job and click **Test run**. Expect HTTP 200 with
   `{"db":"ok",...}`. Run it again if the first one times out during a cold
   start. A 401 means the header is missing or wrong.

There are no scheduled GitHub workflows, on purpose.
