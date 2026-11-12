# Infra

Everything runs on free tiers, co-located in Singapore. Do the sections in
order: each one gives you a value that the next one needs.

| Piece    | Host                | Root dir    | Region                        |
| -------- | ------------------- | ----------- | ----------------------------- |
| Database | Supabase (Free)     | n/a         | Southeast Asia (Singapore)    |
| Backend  | Render (Free web)   | `backend/`  | Singapore                     |
| Frontend | Vercel (Hobby)      | `frontend/` | global CDN                    |
| Pings    | cron-job.org (Free) | n/a         | n/a                           |

Keep these somewhere safe (a password manager), never in git:
`DATABASE_URL`, `PING_TOKEN`, the Supabase database password.

## 0. Generate PING_TOKEN

In PowerShell:

```powershell
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString('x2') })
```

This prints 64 hex characters. Hex is safe inside a URL. Save it as `PING_TOKEN`.

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
   - Change `postgresql://` to `postgresql+psycopg://`.
   - Replace `[YOUR-PASSWORD]` with the password. If the password has
     characters such as `@ : / ? # %`, percent-encode them.
   - Add `?sslmode=require` at the end.
   - Result: `postgresql+psycopg://postgres.<ref>:<password>@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require`
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
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**:
     `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
     (the free plan has no pre-deploy command, so migrations run at start).
   - **Instance Type**: `Free`.
5. Under **Environment Variables**, add:
   - `PYTHON_VERSION` = `3.12.12`
   - `DATABASE_URL` = the value from step 1.4
   - `PING_TOKEN` = the value from step 0
   - `CORS_ORIGINS` = `http://localhost:5173` for now. You replace it in step 3.5.
6. Open **Advanced**. Set **Health Check Path** to `/health`. Leave
   **Auto-Deploy** on **On Commit**.
7. Click **Deploy Web Service**. Wait for "Live" in the log.
8. Check in a browser:
   - `https://<your-service>.onrender.com/health` returns `{"status":"ok",...}`.
   - `https://<your-service>.onrender.com/health/db?token=<PING_TOKEN>` returns
     `{"db":"ok","latency_ms":...}`. This proves the migration ran and the
     database is reachable.

Notes:

- A free service sleeps after 15 minutes without traffic. The next request
  waits for a cold start (often 30 to 60 seconds). The frontend shows
  "Server is waking up" during that time.
- Every start runs `alembic upgrade head`. With no new migration it is a quick
  no-op. If the database is down, the service fails to start; that is
  intended, so a broken schema never serves traffic.
- The `token` query value appears in Render request logs. Those logs are
  private to your account. Rotate `PING_TOKEN` if you ever share logs.
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
   - **URL**: `https://<your-service>.onrender.com/health/db?token=<PING_TOKEN>`
   - **Execution schedule**: **Every day at** `03:30`.
   - **Notifications**: turn on **execution of the cronjob fails** and
     **the cronjob will be disabled because of too many failures**. Also turn
     on **execution of the cronjob succeeds after it failed before** to get an
     all-clear email.
   - Click **Create**.
5. Open the heartbeat job and click **Test run**. Expect HTTP 200 with
   `{"db":"ok",...}`. Run it twice if the first one times out during a cold
   start.

There are no scheduled GitHub workflows, on purpose.
