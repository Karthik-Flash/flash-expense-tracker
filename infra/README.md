# Infra

All hosting is on free tiers. Nothing here is deployed yet. Do these steps
when Phase 1 needs a live backend.

| Piece    | Host                  | Root dir    | Config                    |
| -------- | --------------------- | ----------- | ------------------------- |
| Frontend | Vercel (Hobby)        | `frontend/` | Vercel dashboard          |
| Backend  | Render (Free web)     | `backend/`  | [render.yaml](render.yaml) |
| Database | Supabase (Free)       | n/a         | Supabase dashboard        |
| Pings    | cron-job.org (Free)   | n/a         | cron-job.org dashboard    |

Pick close regions: Render `singapore` and Supabase `ap-southeast-1` (Singapore).

## Supabase (Postgres)

1. Create a project in region `ap-southeast-1`. Save the DB password in your
   password manager.
2. Open **Connect**. Copy the **Session pooler** connection string. Render free
   instances have no IPv6, and the direct connection host is IPv6-only.
3. Change the scheme to `postgresql+psycopg://`. This is the `DATABASE_URL`.

## Render (backend)

1. Render dashboard: **New > Blueprint**. Connect the GitHub repo.
2. Set **Blueprint Path** to `infra/render.yaml`.
3. Fill the env vars that the Blueprint marks as unset:
   - `CORS_ORIGINS`: the Vercel production URL, for example
     `https://flash-expense-tracker.vercel.app`. Comma-separate extra origins.
     Vercel preview URLs are not allowed unless you add them.
   - `DATABASE_URL`: from the Supabase step.
4. Deploy. Check `https://<service>.onrender.com/health`.
5. Run migrations once a schema exists: Render Shell, then `alembic upgrade head`.

Free web services sleep after 15 minutes without traffic. The first request
after that takes about 30 to 60 seconds. The frontend shows "Server is waking
up" during that time.

## Vercel (frontend)

1. Vercel dashboard: **Add New > Project**. Import the GitHub repo.
2. Set **Root Directory** to `frontend`. Framework preset: **Vite**.
3. Add env var `VITE_API_URL` = the Render URL, without a trailing slash.
4. Deploy. Put the resulting URL into Render `CORS_ORIGINS`.

## cron-job.org keep-alive

Create a free account at https://cron-job.org and add these jobs:

1. **Render keep-warm**: `GET https://<service>.onrender.com/health` every
   10 minutes. This stops the cold start. One always-on free service uses
   about 744 of the 750 free instance hours per month, so keep only one free
   service on this account.
2. **Supabase keep-alive**: free projects pause after 7 days without activity.
   `/health` does not touch the database. Until a DB-backed health route exists
   (planned for Phase 1, for example `/health/db` that runs `SELECT 1`), ping
   the Supabase REST API once a day:
   - URL: `https://<project-ref>.supabase.co/rest/v1/`
   - Header: `apikey: <anon public key>`
   When `/health/db` exists, point this job at it and remove the header.

There are no scheduled GitHub workflows on purpose.
