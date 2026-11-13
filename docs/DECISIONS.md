# Decisions

Short decision log. Newest at the bottom. Add an entry when a choice would be
expensive to reverse or would surprise a new contributor.

## D-001 Money as integer paise (2026-11-12)

Store and compute all money as integers in paise (1 INR = 100 paise). Floats
cause rounding errors. Format to rupees only at the display edge.

## D-002 UTC storage, IST display (2026-11-12)

Store timestamps as UTC. Convert to Asia/Kolkata for display and for day and
month bucketing, so a 23:30 IST spend lands on the correct day.

## D-003 Idempotent ingestion with dedupe keys (2026-11-12)

Each ingested message gets a deterministic dedupe key, enforced by a unique
constraint. Re-importing the same backup must not create duplicates.

## D-004 Keep raw message and parser version (2026-11-12)

Every parsed transaction links to its raw message and records the parser
version. Parser fixes can then re-parse old data instead of losing it.

## D-005 Monorepo with independent roots (2026-11-12)

`backend/` and `frontend/` each deploy from their own root (Render, Vercel).
Each one stays self-contained: own deps, own config, no cross imports.

## D-006 Free-tier hosting and external keep-alive (2026-11-12)

Vercel, Render free web service, Supabase free Postgres. cron-job.org keeps
Supabase active. No scheduled GitHub workflows. (Ping cadence: see D-012.)

## D-007 Pinned direct dependencies (2026-11-12)

`requirements.txt` pins direct runtime deps with `==`; `requirements-dev.txt`
adds tools. Upgrade on purpose, in a dedicated `chore/deps` branch.

## D-008 Raw SMS stays local (2026-11-12)

Raw SMS exports stay in gitignored `data/raw/`. Tools and agents never read
them. Development uses the redacted sample from `scripts/redact_sms.py`.

Superseded by D-015: real data now lives outside the repo.

## D-009 LF line endings everywhere (2026-11-12)

`.gitattributes` forces LF in the repo, so Windows and Linux (CI) checkouts do
not produce whitespace-only diffs.

## D-010 Keep httpx; never install unverified packages (2026-11-13)

Starlette warns that `httpx` with `TestClient` is deprecated and suggests
`httpx2`. The name could not be verified as the official successor, and
installing it was blocked as a supply-chain risk. We keep `httpx` (tests pass)
and only add a package after checking its PyPI owner and source repository.

## D-011 Supabase keep-alive is a real DB write (2026-11-13)

`GET /health/db?token=...` upserts a single `heartbeat` row, so Supabase sees
genuine database activity. A shared `PING_TOKEN` protects it; it returns 401
when the token is missing or unset and 503 when the DB is unavailable.
`/health` stays DB-free so liveness never depends on Supabase.

Auth details superseded by D-017 (header token, 503 when unset).

## D-012 Daily ping, not keep-warm (2026-11-13)

One monitored cron-job.org call per day to `/health/db`, with failure emails.
Render is allowed to sleep; the UI handles cold starts. A wake-up call to
`/health` two minutes earlier keeps the monitored call under cron-job.org's
30-second timeout. (Where migrations run: see D-018.)

## D-013 Co-locate in Singapore (2026-11-13)

Render has no India region. Render `singapore` plus Supabase
`ap-southeast-1` keeps app-to-DB latency low and is the closest option to IST
users.

## D-014 Pseudonymise people and references in samples (2026-11-13)

`scripts/redact_sms.py` replaces people's names in P2P messages with stable
tokens (`PERSON_001`) and transaction references with stable fakes of the same
shape. Maps live in gitignored, agent-blocked `data/private/`, so re-runs agree
and deduplication can be tested on the sample without real identifiers.

Superseded by D-016: default-deny, no person-vs-merchant guessing.

## D-015 Real data lives outside the repo (2026-11-13)

SMS exports live in `D:\FlashPrivate\raw\`; the name map, redaction key and
aw`; the name map, redaction key and
private keep-list live in `D:\FlashPrivate\private\`. `redact_sms.py` has no
default paths: `--input`, `--private-dir` and `--output` are explicit. Agents
are denied that folder and run the script only on synthetic test files.

## D-016 Default-deny redaction with a keep-list (2026-11-13)

Every counterparty name and UPI ID local part is pseudonymised unless it is
on `scripts/keep_names.txt` (public brands, committed) or the private
keep-list. No guessing person vs merchant. Masked values keep their shape.
Consistent fakes come from `name_map.json` or HMAC-SHA256 with a random key
created on first run, never a bare hash, so fakes cannot be reversed by
hashing guesses.

## D-017 /health/db token in a header (2026-11-13)

The token travels in `X-Ping-Token`, compared with `secrets.compare_digest`,
so it never lands in URLs or access logs. Missing or wrong: 401. `PING_TOKEN`
unset: 503 "ping token not configured". The heartbeat time comes from the
database clock.

## D-018 Migrations in the build step (2026-11-13)

Render's free plan has no pre-deploy command. `alembic upgrade head` runs in
the build command after `pip install`, so it runs once per deploy, and a
failed migration fails the deploy while the previous version keeps serving.
The start command only starts uvicorn.

## D-019 No agent access to .env files (2026-11-13)

`.claude/settings.json` denies reads of `.env` and its variants anywhere on
disk; `.env.example` stays readable. Agents never print environment variable
values.

## D-020 UI direction (2026-11-13)

Minimalist and professional; it must not look AI-generated. The detailed
design spec comes in Phase 3.

## D-021 CORS_ORIGINS format (2026-11-13)

One comma-separated string of exact origins, no spaces needed, no trailing
slashes: `http://localhost:5173,https://flash-expense-tracker.vercel.app`.
Vercel preview URLs are not allowed unless added.

## D-022 Database password: letters and digits only (2026-11-13)

Characters such as `#` and `%` broke `DATABASE_URL` parsing on first deploy.
Rather than relying on percent-encoding, the Supabase password uses letters
and digits only, made long for strength.

## D-023 Cron schedule (2026-11-13)

cron-job.org, time zone Asia/Kolkata. "Flash wake-up": `GET /health` at 03:27
and 03:28, failure alerts off. "Flash DB heartbeat": `GET /health/db` with the
`X-Ping-Token` header at 03:30, alerts on for failure and for auto-disable.

## D-024 Render service created by hand; render.yaml is the reference (2026-11-13)

The live service `flash-expense-tracker` was created in the Render dashboard,
not from the Blueprint. `infra/render.yaml` mirrors its settings and must be
updated whenever the dashboard settings change.
