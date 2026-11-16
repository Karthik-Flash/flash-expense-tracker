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

Wake-up call superseded by D-052 (14 Nov 2026): one job with retries.

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

Superseded by D-052 (14 Nov 2026).

## D-024 Render service created by hand; render.yaml is the reference (2026-11-13)

The live service `flash-expense-tracker` was created in the Render dashboard,
not from the Blueprint. `infra/render.yaml` mirrors its settings and must be
updated whenever the dashboard settings change.

## D-025 Sender ID normalisation (2026-11-14)

Real exports show operator prefixes without hyphens, so one bank appears
under many IDs (`SBIBNK`, `VKSBIBNK`, `CPSBIBNK`, `JXSBIINBS`, ...).
`redact_sms.py` reduces every ID to its core before matching, counting and
promo detection: uppercase, drop hyphens; 9 chars ending S/T/P/G drop the
2-letter prefix and the suffix; 8 chars drop the prefix; 7 chars ending
S/T/P/G drop the suffix; numeric short codes drop a 2-letter prefix
(`CP388558` -> `388558`); anything else (RCS IDs like `...@RBM.GOOG`, phone
numbers) stays unchanged and is never allowlisted. Suffix P (promotional) is
dropped in both forms.

## D-026 Sender allowlist as data minimisation (2026-11-14)

The default allowlist is banks and UPI only: HDFCBK, HDFCBN, SBIBNK, CBSSBI,
SBIUPI, SBIINB, SBYONO, SBIPSG, ICICIT, AXISBK, KOTAKM, YESBNK, DOPBNK,
PHONPE. Investment, broker and exchange senders are deliberately excluded
until Phase 6, so the sample holds only what spending analysis needs.

## D-027 Template surveys and parser fixtures (2026-11-14)

Parsers are designed from template shapes, not from message text. Rules:

- `scripts/shape_survey.py` output stays in `data/sample/` (gitignored).
  Committed template docs (`docs/templates/<bank>.md`) contain shapes with
  placeholders and fixed bank wording only.
- Fixtures (`backend/tests/fixtures/sms/<bank>.json`) use obviously fake
  values: `TEST ...` names, `PERSON_900`+, `test.user@...` VPAs, accounts
  `XX0001`, refs `000000000001`, repeated-digit amounts. No amount may equal
  any amount in the sample (round numbers collided, so repeated digits are
  used instead).
- Fixture conventions: `account_last4` holds the card's last 4 for card
  transactions; foreign-currency fixtures carry only
  `{"type": "foreign_currency"}`. (Time convention: superseded by D-034.)
- Before committing, every new file is scanned against the sample: shared
  digit runs, VPAs, amounts, pseudonym tokens below 900, words that occur only
  in value slots of the sample, and 6-word windows that are not template text.

## D-028 Parser scope: one message only (2026-11-14)

The parser reports only what a single message says. Anything that needs
other messages or the user's own accounts (transfers, card bill payments,
refund linking, cross-message duplicates) is decided in the Reconcile stage,
Phase 2-3.

Timing superseded by D-054 (15 Nov 2026): Reconcile is step 3C.

## D-029 Self-transfers are transfers (2026-11-14)

Money moved between the user's own accounts or wallets is a transfer, not
spending. Reconcile decides, using a user-maintained "my accounts and UPI IDs"
list. The parser just reports the debit or credit.

Wallets updated by D-063 (15 Nov 2026): a top-up is a transfer only when the
owner lists the wallet as an own account.

## D-030 Card bill payments are transfers (2026-11-14)

Paying a credit card bill is a transfer, so card spends are not counted
twice. Reconcile decides; the parser sets a hint when the wording says it is
a card payment.

## D-031 Reversals link to the original spend (2026-11-14)

A reversal becomes a refund linked to the original spend: same card last 4,
same amount, within a few days. With no match it stays a standalone refund.
Reconcile.

Window superseded by D-064 (15 Nov 2026): 30 days, same card or same account.

## D-032 AutoPay success plus card "Spent" (2026-11-14)

Both messages are parsed. They are possible duplicates, merged in Phase 2.

Updated by D-047: Phase 2 only records them as duplicate candidates; merging
moves to Reconcile (Phase 3).

"Merged" superseded by D-062 (15 Nov 2026): duplicates are linked, never
merged.

## D-033 Pre-debit notices are upcoming_debit (2026-11-14)

A notice that money will be debited later has type `upcoming_debit`. It is not
money. It is stored later for month-end forecasts (Phase 6).

## D-034 Date without time (2026-11-14)

For money types (debit, credit, refund) `txn_time_utc` is always set. If the
message has no time, it is `received_at` and `time_inferred` is true;
otherwise `time_inferred` is false. Non-money types have both null.

## D-035 International card spends deferred (2026-11-14)

International card spends and forex notices are handled with
`foreign_currency`, which is deferred. Fixtures carry only the type.

## D-036 FD premature closure (2026-11-14)

Parsed as `credit` with channel `fd`. Reconcile treats it as the user's own
money moving (transfer in), not income.

## D-037 Masked UPI ID as the only counterparty (2026-11-14)

Acceptable for now. Quick-tagging will let the user name such counterparties
later.

## D-038 Hyphenated sender IDs split on hyphens (2026-11-14)

Fixes D-025: removing hyphens before the length rules turned `AB-ABCDE-P`
into core `ABCDEP` and lost the promo suffix. IDs with hyphens are now split:
optional 2-letter prefix, core, optional S/T/P/G suffix. Length rules apply
only to IDs without hyphens.

## D-039 Bank wording is never redacted; link paths are (2026-11-14)

`BANK_VOCABULARY` in `scripts/redact_sms.py` lists fixed template phrases
("HDFC Bank Card", "authentication", ...). They are skipped at the start of a
name, end a name, are never replaced, and stale name-map entries made of them
are ignored. It is separate from `keep_names.txt`, which lists brands that are
counterparties. Links keep scheme and host; the path and query (possibly a
personal tracking link) get a same-length HMAC fake.

## D-040 Always-redact list and automatic leak check (2026-11-14)

Manual checks cover only a few names, and one real first name reached the
sample. `scripts/redact_sms.py` therefore:

- reads an optional `always_redact.txt` in the private folder (own and family
  names, own phone) and replaces every whole-word occurrence in a final pass,
  using the same name map and tokens; entries are never printed;
- with `--verify`, scans the written sample for those entries (as
  substrings), 2+ word mapped names, and real UPI IDs and references. UPI IDs
  and references are matched by keyed digest (`seen_ids.json`), so no real
  value is stored for the check. Output is tokens and message numbers only;
  the exit code is 1 if any leak is found;
- one standard sample command: `--limit 100 --seed 42 --verify`.

Counterparty listings show real values and are never pasted into chats.

## D-041 Parser rules (2026-11-14)

The engine (`backend/app/engine/`) parses one message at a time and reports
only what that message literally says. Each bank parser is a list of
templates matched against the whole (whitespace-normalised) body. Exactly one
template may match: none gives `Unknown("no_template")`, two or more give
`Unknown("ambiguous")`; the engine never picks one. A match whose values fail
validation (invalid date, ambiguous amount, differing card numbers) is also
`ambiguous`. Foreign-currency messages return
`Unknown("foreign_currency_deferred")` (D-035). Details: `docs/engine.md`.

## D-042 Parser versioning (2026-11-14)

Every result stores its bank's `PARSER_VERSION` (`hdfc-1.0.0`). Any change
that can alter a result bumps it in the same commit: major for a change in
field meaning, minor for a new template, patch for a value fix. Stored
messages with an older version can then be re-parsed.

## D-043 Engine stays stdlib and framework-free (2026-11-14)

The engine uses only the standard library (re, decimal, datetime,
dataclasses) and imports no FastAPI, SQLAlchemy or app config; a test
enforces this. IST is a fixed UTC+05:30 offset instead of zoneinfo, which
needs extra tz data on Windows. Sender normalisation exists in the engine and
in standalone `scripts/redact_sms.py`; one shared case table
(`backend/tests/fixtures/sender_ids.json`) keeps them identical.

## D-044 Amount-free notice fallback (2026-11-14)

A bank parser may name an info fallback (HDFC: `H_INFO`). A message from that
bank that matches no template and contains no amount (Rs, INR, the rupee
sign, or a foreign currency code followed by a number) becomes `other_info`
with no fields, never `is_money`. A message that contains an amount and
matches no template stays `Unknown("no_template")`: amounts are never
guessed. This covers the long tail of bank notices (UPI activated, card
limits, KYC, login alerts) without one template per notice. HDFC moves to
`hdfc-1.1.0` with templates H16-H21 from the full-data coverage run.

## D-045 Mandate IDs and payee names are redacted (2026-11-14)

`scripts/redact_sms.py` fakes the value after `Mandate ID:` and `SI Hub ID:`
whatever its digit count (other references need 6+ digits), keeping length
and character classes, and treats the name after "added a payee" as a
counterparty position. Both were gaps found in the full-data run.

## D-046 Dedupe rules (2026-11-14)

Raw messages dedupe on `content_hash = sha256(sender_core, body,
received_at epoch ms)`, unique per owner. The source is excluded, so the same
SMS arriving later by live SMS is still a duplicate. Money results become
transactions keyed by `sha256("ref", bank, direction, amount_paise,
reference)` when they carry a per-payment reference (account excluded, so
email and statements can merge later), else by `sha256("raw",
content_hash)`. A mandate ID is not a per-payment reference: it repeats on
every monthly charge, so results with the engine hint `mandate_reference`
(HDFC H08, H13; `hdfc-1.1.1`) use the raw key, or two same-amount
subscription charges would collapse into one. There is no fuzzy merging.
Different directions never merge. Details: `docs/data-model.md`.

## D-047 Fuzzy duplicates are recorded, merged in Reconcile (2026-11-14)

Same owner, bank, `account_last4`, direction and amount within 10 minutes,
without a shared reference, gives a `duplicate_candidates` row (status
`open`). Phase 2 never merges these. The common case is an AutoPay success
SMS plus the card "Spent" SMS for one charge; merging them, and every other
cross-message judgement, moves to Reconcile (Phase 3).

Superseded in part by D-062 (15 Nov 2026): nothing merges, and the `status`
of a `duplicate_candidates` row is never written.

Narrowed by D-069 (16 Nov 2026): two different references are two payments,
not a candidate.

## D-048 Real data lives in Supabase; AI tools never connect to it (2026-11-14)

Supabase Postgres holds the real imported data. It is protected by the Data
API being off, row level security enabled on every pipeline table with no
policies (the app connects as table owner, so RLS is defence in depth), and
the database password, which lives only in `backend/.env` and Render.
AI tools never connect to it and never run the importer on real data; they
work from synthetic fixtures and the redacted sample only. Tests force a
throwaway SQLite URL, and CI uses a disposable Postgres container.

## D-049 Never-stored messages and the OTP rule (2026-11-14)

The importer stores only senders in the engine's bank registry, including
banks without a parser yet (a new parser then needs only `reparse`). OTP,
promotional (TRAI suffix P) and MMS messages are never stored. The OTP rule
lives in `app/engine/filters.py` and in standalone `scripts/redact_sms.py`;
one shared case table (`backend/tests/fixtures/otp_cases.json`) keeps them
identical. Advisories like "never asks for OTP" are not OTPs.

## D-050 Render deploys only after CI passes (2026-11-14)

Render Auto-Deploy is set to "After CI Checks Pass" (set by hand in the
dashboard), so a red CI never reaches production. Every deploy runs
`alembic upgrade head` in the build (D-018), so migration 0002 reaches
Supabase on the first deploy after the merge.

## D-051 The full redacted export stays in the private folder (2026-11-14)

Only the 288-message sample (`data/sample/redacted_sample.json`) is shared
with agents and the planner. The full redacted export, which holds every
message, is written to `D:\FlashPrivate\private\redacted_full.json` and read
from there by `scripts/parse_coverage.py`. It never goes in the repo folder,
not even in gitignored `data/`. Extends D-015.

## D-052 One heartbeat job with retries (2026-11-14)

Supersedes D-023 and the wake-up call in D-012. The "Flash wake-up" job is
deleted. One cron-job.org job, "Flash DB heartbeat", calls `GET /health/db`
with the `X-Ping-Token` header at 03:30, 03:32, 03:34, 03:36 and 03:38 IST.
The first run each night is expected to fail ("output too large": Render's
wake-up page while it spins up); a later run succeeds and resets the failure
count. Notifications: "execution fails" off, "job disabled" on. Supabase's
pause warning email is the backstop.

Superseded by D-053 (15 Nov 2026): Render never woke for cron-job.org.

## D-053 Keep-alive through the Supabase Data API, one schema only (2026-11-15)

Supersedes D-052. The keep-alive no longer goes through Render: asleep, Render
served its browser loading page to cron-job.org ("output too large") and
never woke, so every run failed. Now cron-job.org job "Flash DB heartbeat"
sends `POST https://<ref>.supabase.co/rest/v1/rpc/ping` daily at 03:30 IST
with headers `apikey` (publishable key), `Content-Profile: keepalive` and
`Content-Type: application/json`, body `{}`. Alerts on failure and on
disable.

Narrow exception to "the Data API is off": it is on, and its exposed schemas
are `keepalive` only. Migration `0003` creates that schema and one function,
`keepalive.ping()`: SECURITY DEFINER with `search_path = public, pg_temp`,
it upserts the heartbeat row and returns `{"ok": true}`, nothing else.
EXECUTE is revoked from PUBLIC and granted to `anon` only. `heartbeat` gets
RLS with no policies, like the pipeline tables. The publishable key lives
only in the cron-job.org header and the password manager, never in git.
`/health/db` and `PING_TOKEN` stay for manual checks. A PowerShell check
(infra/README.md, section 4) proves the public tables are unreachable.

## D-054 Phase 3 scope and order (2026-11-15)

Phase 3 runs in steps 3A to 3F as in `docs/PLAN.md`: 3A groundwork (docs, UI
design spec, clickable mockup), 3B merchant normalisation, 3C reconcile, 3D
categorise, 3E auth and read-only API, 3F minimal dashboard. Each step ends
with tests green, a counts-only check on real data run by the owner, and a
tag (`phase-3a-done` ... `phase-3f-done`). Engine work (3B-3D) comes before
auth and the API, so the API is built once on the final data shape and no
real data is reachable from the internet before a screen needs it.
Supersedes the timing in D-028 ("Phase 2-3"): Reconcile is step 3C.

## D-055 Spend definition for Phase 3 (2026-11-15)

- Spent = debits that count, minus refunds.
- Not spend: self-transfers between own accounts; FD movements;
  `upcoming_debit` notices; a card bill payment when that card's purchases
  are tracked in the data.
- Spend: a card bill payment when that card's purchases are not tracked
  (category "Card bill"); payments to people (category "People"); ATM
  withdrawals (category "Cash"). The exact "tracked" test is defined in 3C.
- Paybacks: a credit from a person is a payback unless that person is marked
  as an income source (pocket money, stipend, salary). A payback is not
  income.
- The dashboard shows Spent, Paid back, and Net = Spent - Paid back. Net is
  the headline.
- A payback counts in the month it arrives. It reduces the month total only.
  Linking it to one purchase or category is Phase 6 (splits).
- If the engine is unsure whether a credit is from a person, it goes to the
  unknown queue and spend is not reduced.
- Income (non-payback credits) is shown separately and never reduces spend.

Updated by D-061 (15 Nov 2026): the "unknown queue" in this entry means
uncertain credits (role `uncertain`); unknown messages are unparsed messages.
The "tracked" test is in D-059.

## D-056 Owner labels next to categories (2026-11-15)

- Every transaction has exactly one category from a fixed list. The list is
  set in the UI design spec.
- A transaction may also carry one label the owner creates, for example a
  trip or an event. At most one label per transaction in Phase 3.
- A label never replaces the category. Month and category totals ignore
  labels, so a labelled spend still counts in its category and nothing is
  counted twice.
- A payback credit can carry a label too.
- The label view shows that label's Spent, Paid back and Net, and its
  breakdown by category, across all dates (a label can span months).
- Labels are owner data: stored only in the database, kept apart from engine
  output, and they survive reparse, like category corrections.
- Not in Phase 3: owner-made categories, budgets per label, automatic
  labelling.

## D-057 Merchant normalisation engine (2026-11-15)

`app/engine/merchant.py`, version `merchant-1.0.0`, pure and stdlib only
(details in `docs/engine.md`, "Merchant normalisation").

- **Output**: one frozen `Merchant`: `kind` (business, person, unsure,
  none), `confidence` (high, low), `merchant_key` (None for none),
  `display_name` and `brand_id` (None unless the dictionary matched),
  `reasons` (rule codes in order), `version`.
- **Rules, in order**: R0 no text or ATM gives none; R1 clean (NFKC,
  casefold, whitespace, outer punctuation) and split a UPI ID; R2 strip a
  gateway prefix (`PAYTM*`, `RAZ*`, `PYU*`, `CCA*`), never a city; R3 brand
  dictionary on whole tokens, longest alias wins, a tie between brands is no
  match; R4 card or AutoPay channel gives business; R5 business and person
  signals. **Ambiguity always gives unsure**: both kinds of signal or none,
  and a dictionary tie never picks a brand.
- **Merchant key**: `brand:<id>`, else `vpa:<casefolded upi id>`, else
  `name:<casefolded words, leading honorifics and punctuation removed>`. The
  same counterparty in another case, spacing or punctuation gets the same
  key. Corrections will be keyed on it, so the key rules are part of the
  version.
- **Dictionary**: `app/engine/brands.json`, well-known national brands only,
  from public knowledge, never from the owner's data. No category yet.
- **Channel**: from the transaction's stored parser channel and hints
  (`channel_for`); parser output and the parser version are unchanged.
- Any change to rules, word lists, the dictionary or the key format bumps
  `MERCHANT_VERSION`.

Key wording ("Corrections will be keyed on it") superseded by D-065
(15 Nov 2026): owner data stores text, not merchant keys.

## D-058 Merchant engine 1.1.0: anchored brands, display names, handles (2026-11-15)

Changes to D-057, version `merchant-1.1.0`:

- **Brand matching is anchored.** An alias matches only at the start of the
  cleaned name (after a gateway prefix and a leading `www` word) or at the
  start of the UPI local part. An alias later in the text is no match.
  Longest alias and the tie rule are unchanged.
- **Display name for every result except kind none**: the brand's name on a
  dictionary match; the cleaned name in title case (gateway prefix removed)
  for name text; the UPI ID in lower case when there is one. Normalising a
  display name again gives the same key.
- **UPI handle signals.** Handles `okaxis`, `okhdfcbank`, `okicici`, `oksbi`
  are a person signal (`R5_consumer_vpa`); a handle starting `okbiz` is a
  business signal (`R5_business_handle`), weighted like a merchant-style
  local part. Confidence rules are unchanged: a consumer handle alone gives
  person, low.
- **Business keywords** extended to 186 common Indian shop and business
  words, whole tokens only, none of one or two letters, none that is also a
  common Indian given name or surname.
- `merchant_key` rules may still change until merchant storage ships. After
  that, any change to them needs a migration plan for stored keys and
  corrections.
- Step 3C decides which reason codes are enough to treat a credit as a
  payback (D-055); the engine only reports them.
- New owner-only command `merchant-review` shows real counterparty text, so
  it runs only when stdout is a terminal; `merchant-stats` stays counts only.

Migration-plan wording superseded by D-065 (15 Nov 2026): owner data stores
text, so a key change needs a recompute check, not a data migration.
Display name beside a UPI ID superseded by D-068 (15 Nov 2026).

## D-059 Derived-data backbone (2026-11-15)

Design: `docs/design/phase-3-backbone.md`, approved 15 Nov 2026 with the
answers recorded in D-060 to D-067.

- Derived data (merchant, role, links, later category) is one pure function
  of the active transactions, the owner data and the engine versions. One
  command recomputes all of it and writes only what changed. It can be
  dropped and rebuilt at any time.
- Owner data lives in its own tables. The engine never writes them; they
  survive reparse and recompute, and they always win.
- Ambiguity never merges, links or nets anything. It becomes a candidate for
  the owner and changes no role until the owner decides.
- Nine new tables: six owner tables (migration `0004`) and three derived
  tables (`0005`), all with row level security and no policies. Nothing is
  added to the `keepalive` schema (D-053).
- The card bill "tracked" test that D-055 left to 3C: a card's purchases are
  tracked when the data holds at least one active `credit_card` debit on
  that card in the 60 days up to the payment.
- Built as steps 3C-2 to 3C-8 (`docs/PLAN.md`). Merchant storage is part of
  step 3C-6.

## D-060 One role for every transaction (2026-11-15)

- Every active transaction gets exactly one role on every run, with the rule
  code that decided it and its basis (`engine` or `owner`). Roles: `spend`,
  `card_bill_counted`, `refund`, `payback`, `income`, `self_transfer`,
  `card_bill_excluded`, `fd_move`, `duplicate`, `ignored`, `uncertain`.
- Totals are sums over roles: Spent = spend + card_bill_counted - refund;
  Paid back = payback; Net = Spent - Paid back; Income = income. Every other
  role is in no total.
- A refund and a payback count in the month they arrive. A link to a
  purchase never moves an amount to another month.
- A guess never lowers Net: an unexplained debit is `spend`; an unexplained
  credit is `uncertain` and reduces nothing.
- A transfer with no payee (HDFC H06, H16) and no identified partner is
  `spend`, and is listed for the owner's review.
- Investment debits (for example a mutual fund SIP) stay `spend` until
  Phase 6 (D-026).
- The role `ignored` stays. It means "not a real movement", and only the
  owner can set it.

## D-061 Paybacks, income and uncertain credits (2026-11-15)

- A credit is a `payback` when its text belongs to an owner party of kind
  person (basis `owner`), or when the merchant engine says person with
  `R5_honorific`, `R5_mobile_vpa` or `R5_consumer_vpa` (basis `engine`). A
  consumer handle alone is enough; a person-shaped name alone is not. Every
  payback records its basis.
- Income parties are checked first: a credit from a party the owner marked
  as an income source is `income`, never a payback.
- `reconcile-stats` counts engine-basis paybacks separately. Recompute and
  `reconcile-stats` print a warning line when the owner data lists no income
  party, because pocket money or a salary would then count as a payback.
- A credit from a business that is not worded as a refund is uncertain, not
  income.
- Terms. **Unknown messages** are messages the parser could not read (the
  unknown queue in `parse_results`). **Uncertain credits** are credits with
  no role evidence; their role is `uncertain` (the design draft called it
  `unknown`). D-055's "goes to the unknown queue" means an uncertain credit.

## D-062 Duplicates are linked, never merged (2026-11-15)

Supersedes the "merged" wording in D-032 and D-047, and D-047's plan to
decide candidates in `duplicate_candidates.status`.

- Nothing merges and nothing is deleted. Both transactions stay; one keeps
  its role, the other gets role `duplicate` and points at the first.
- A unique AutoPay success and card spend pair (same bank, card and amount)
  inside 10 minutes is linked without asking. Every other same-amount pair
  is a candidate for the owner.
- `duplicate_candidates` is frozen: import keeps recording into it, its
  `status` is never written, and Reconcile does not read it for decisions.
  Reconcile finds its pairs from the transactions and must find every
  existing candidate again, as a link or a candidate; a test and a
  `reconcile-stats` line check that. Owner decisions live in their own
  table.
- The primary of a duplicate group is the earliest transaction, then the
  lowest id, for now. Step 3C-3 reports whether that choice changes the
  merchant shown for an AutoPay and card pair; the planner decides then.

Narrowed by D-069 (16 Nov 2026): a same-amount pair with two different
references is no longer proposed; recorded ones are kept.

## D-063 Wallet top-ups (2026-11-15)

Updates D-029. A wallet top-up is a self-transfer only when the owner lists
that wallet as an own account. Otherwise it is spend at the wallet. Wallet
spends do not appear in bank SMS, so listing a wallet takes that money out
of the totals; the owner chooses.

## D-064 Refund linking: 30 days, same card or account (2026-11-15)

Supersedes "within a few days" in D-031.

- A refund always has role `refund` and reduces Spent in the month it
  arrives, linked or not. The link only says which purchase it belongs to.
- A refund links to a purchase on the same card or, for a refund to a bank
  account, on the same account (same bank and last 4), at most 30 days
  earlier. The link is automatic only for a unique purchase of the same
  amount from the same merchant; anything else is a candidate.
- The refund that Phase 2 merged on its dedupe key (two messages, one
  transaction) stays as it is for now. Reparse cannot split a transaction
  that has two sources; that gets a pipeline fix only if the owner's
  private check finds two real refunds.

## D-065 Owner data holds text and transaction ids (2026-11-15)

Supersedes the key wording in D-057 ("Corrections will be keyed on it") and
D-058 ("a migration plan for stored keys and corrections").

- Owner tables store the owner's own words (account and party texts, last 4
  digits, labels) and transaction ids, never merchant keys. Every run works
  out each text's key with the current engine.
- So a change to the key rules needs no data migration. Recompute stops
  without writing when a merchant version change would make a transaction
  lose or change its owner match, unless the owner accepts it
  (`--accept-key-changes`).
- Owner data enters through one private JSON file kept in `D:\FlashPrivate`
  (`owner-load`), and later through the app. `owner-export` writes it back
  out, decisions included. Both are built in 3C: the free Supabase plan has
  no backups, so the export is the backup.
- Owner data never appears in git, fixtures or logs.

## D-066 The owner runs recompute (2026-11-15)

Recompute runs as the last step of `import-sms`, `reparse` and the owner
commands, and by hand. It is never scheduled and never runs in Render's
build. After a deploy that bumps an engine version, derived data is stale
until the owner runs `recompute`; `stats` and the API show a stale flag.
Revisit in Phase 5, when the server takes in SMS itself.

## D-067 Closing mandates waits for Phase 6 (2026-11-15)

Reconcile in 3C does not close mandates on cancellation (hint
`mandate_cancelled`). Mandates are not transactions and touch no total; they
belong with subscriptions in Phase 6. `docs/data-model.md` is corrected.

## D-068 Display name prefers the name (2026-11-15)

Changes D-058, version `merchant-1.1.1`. When a counterparty has both name
text and a UPI ID, `display_name` is the cleaned name in title case, not the
UPI ID. The key stays the UPI ID, and kinds and keys do not change. The
round-trip rule (normalising a display name gives the same key) holds only
when the display name comes from the same text as the key.

## D-069 Two different references are two payments (2026-11-16)

Narrows D-047 and D-062. A same-amount pair where both transactions carry a
reference and the references differ is two payments, not a possible
duplicate.

- Reconcile (`reconcile-1.2.0`) no longer proposes such a pair. It keeps one
  only when the pair is already recorded in `duplicate_candidates` (rule
  `DUP_legacy`, reason `different_references`), so no existing candidate is
  lost.
- Import's `is_candidate` has the same exclusion, so the recorded list stops
  growing with such pairs.
- A pair where one side has no reference is still a candidate. Two messages
  with the same mandate ID are still a candidate in Reconcile.
- Why: nearly every UPI transaction carries a reference (116 of 127 in the
  redacted sample), so every pair of equal payments close in time would
  have become a review item.

## D-070 Owner rows carry their source; a file load touches only file rows (2026-11-16)

Refines D-065 and the design (section C had `source` on the decision tables
only; section F let a file add decisions).

- Every row in the six owner tables has a `source`: `file`, `terminal` or
  `app`.
- `owner-load` makes the file-sourced accounts, identifiers, parties and
  texts equal to the file: it adds, updates and removes them. It never
  changes or removes a row written by the review or the app, and never a
  decision. The file may not claim a label or text that such a row holds.
- The file is checked strictly. A problem is reported by its field path,
  never by its value, and then nothing is loaded.
- Decisions are not in the owner file yet. A decision must name its
  transactions by dedupe key as well as id, so that a rebuilt database can
  take the file back; that format arrives with the review and the export
  (3C-7, 3C-8).
