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

## D-012 Daily ping, not keep-warm (2026-11-13)

One monitored cron-job.org call per day to `/health/db`, with failure emails.
Render is allowed to sleep; the UI handles cold starts. A wake-up call to
`/health` two minutes earlier keeps the monitored call under cron-job.org's
30-second timeout. Migrations run in the start command because the free plan
has no pre-deploy command.

## D-013 Co-locate in Singapore (2026-11-13)

Render has no India region. Render `singapore` plus Supabase
`ap-southeast-1` keeps app-to-DB latency low and is the closest option to IST
users.

## D-014 Pseudonymise people and references in samples (2026-11-13)

`scripts/redact_sms.py` replaces people's names in P2P messages with stable
tokens (`PERSON_001`) and transaction references with stable fakes of the same
shape. Maps live in gitignored, agent-blocked `data/private/`, so re-runs agree
and deduplication can be tested on the sample without real identifiers.
