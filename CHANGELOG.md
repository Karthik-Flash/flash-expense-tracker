# Changelog

What shipped in each phase. Decision numbers refer to
[docs/DECISIONS.md](docs/DECISIONS.md). Phases follow the prompt labels:
Phase 1 is parsing, Phase 2 is the database and import.

## Premium run: Analytics, rules, robustness, polish (23 Nov 2026)

- Analytics at the top of Insights: Spent per month with Invested, Paid back and Net,
  categories over time, the biggest changes, top places and people, and a few numbers; a
  bar or a row opens its payments (D-148).
- "All payments to <name>" is a rule you can see and undo in Profile; Paid back on one
  credit can be "Just this one" (D-149).
- Profile shows your account, your phones and their last upload; About shows the app's
  and server's versions; Home shows "Getting started" until the phone is set up (D-147,
  D-152).
- Safer before the push: the admin never sees amounts, names or SMS; large ids and bodies
  get clear errors; `doctor` checks the data read-only; an emoji no longer makes a second
  copy of one SMS; the snapshot reads its rows once (D-147, D-150).
- Text wraps at large sizes and every tap target is at least 44 px (D-151).

## Phase 5F, part 1: Insights (23 Nov 2026)

- A new Insights tab. Export a month or any dates as Excel or CSV, built on the server;
  on the phone it opens the share sheet (D-146).
- Profile and Admin gather your settings and People who use Flash in one place.

## Phase 5B-2: the phone just works (23 Nov 2026)

- A new bank SMS is sent at once, also when an earlier try is waiting; every app start and
  resume and an hourly check catch up (D-142).
- Nothing is lost: the queue is kept while the phone is disconnected or signed out, and the
  same login reconnects by itself without a new setup (D-143).
- Payment notifications, with "Paid back?" for money from a person; a tap opens the payment
  (D-141, D-142).
- A Bank SMS status screen in plain words, with Samsung battery help, an event log and Copy
  diagnostics (D-142).
- The two copies of one SMS are one payment; two real payments stay two (D-139).
- An unchanged snapshot answers 304 without being built (D-140); a lost session says so
  (D-144).

## Phase 5B-1: daily-use correctness (22 Nov 2026)

- To-do lists are newest first (D-138).
- The app refreshes when it comes back to the screen, after a change syncs and
  every minute while open; pull down to refresh; "Updated 14:05" (D-135).
- People only for clearly personal payees; shops with a person's name, QR and
  gateway UPI IDs and anything unclear are Uncategorised (`categorise-1.3.0`,
  D-133).
- A payback guess needs an earlier payment to that person; a payment shows
  which paybacks are for it; a credit's sheet answers Paid back / Not paid
  back (`reconcile-1.7.0`, D-134).
- Invested and Invested (to confirm) per month, an Investment tag and filter,
  and the setting "Count investments in Spent", off by default (migration
  `0016`, D-136).
- Owner review commands `category-diff` and `payback-review` (D-137).

## Phase 5C: several users (22 Nov 2026)

- Testers join with an invite code the owner makes in the app (People who use
  Flash): one-time, 7 days, shown once; public sign-up stays off (D-128).
- Logins live in the database (`app_users`): the owner becomes the admin on
  the first request; `AUTH_USERS` is only a fallback now (D-129).
- Every route is tested against another user's ids: nothing is read or
  changed across accounts (D-130).
- Delete my account deletes everything of that account, then the login, then
  the phone's copy; the admin cannot delete their own (D-131).
- A first-run sheet for a new account, Settings, and "What Flash stores"
  (`docs/privacy.md`) (D-132).
- `sender-survey --contains HDFC`: sender codes, stored and skipped, counts
  only.

## Phase 5A: Flash on Android (22 Nov 2026)

- An Android app (`app.flashexpense.android`, "Flash"): the web app bundled
  in a Capacitor 8.6.2 shell, so it opens offline from the first launch; a
  new version is a new APK, installed over USB (D-125).
- Bank SMS read on the phone: the history from a chosen start (the newest
  message the server has, or 3, 6 or 12 months), every new message within a
  minute, and a check every 6 hours. Only bank messages leave the phone; the
  server checks again and stores them exactly as a laptop import, so nothing
  is counted twice (D-123, D-124).
- Phones and device tokens: a phone uploads with its own token, which can do
  nothing else; Revoke from any device; sign-out revokes and wipes it
  (D-122).
- A "Bank SMS" sheet: permission (with the steps for Android's restricted
  settings), connect, the period, the status and the phones; the same status
  at the top of the Speed sheet, with a battery hint (D-124).
- An SMS that merges into a row from the bank statement keeps that row and
  your answers on it (D-126).
- HDFC `hdfc-1.2.0`: the forex markup notice is read as a notice, so 44
  messages leave "not counted yet"; it carries no amount (D-127).

## Phase 4Z: closing Phase 4 (21 Nov 2026)

- History: the push was verified and the temporary git backup deleted
  (D-121).
- Statements: September's card reversal row (a negative debit with a credit)
  is read by the balance chain; more likely causes (an unread HDFC alert, own
  transfers, FD, investments, card bills, tiny credits); `statement-import`
  adds the rows the app misses, safely (D-120); `redact-sample --unparsed` for
  the missing HDFC template.
- "It's me" and Investments on sender cards and the person sheet, with "Is
  this you?" and "Is this an investment?" in To-do and "Your name as banks show
  it" in a settings sheet (D-117, D-118).
- Categories guessed from payee names and UPI IDs; "guessed from the name" in
  the sheet; totals unchanged (D-119).

## Phase 4A: money correctness (21 Nov 2026)

- `statement-check`: the HDFC NetBanking statement against the app, per
  month: what matches, what only one side has, likely causes (no SMS for
  this kind, month edge, foreign currency, reversed, a second alert, a card
  or another account), and Spent and Net with the missing rows counted.
  Counts and rupee sums only, safe to paste (D-114).
- Money moved between your HDFC and SBI accounts: a shared UPI/IMPS
  reference makes both legs a transfer at once; the same amount within 30
  minutes without one is asked in To-do, "Moved between your accounts?"
  (D-115).
- `statement-names`: names from the statement for senders shown only as a
  UPI ID or a masked one, after the owner approves; never over the owner's
  own names, never joins people (D-116).

## Phase 4H: people actions, payback rule, polish (21 Nov 2026)

- History: the AI attribution lines were removed from every commit message
  (history rewritten; old to new SHAs in
  [docs/history-rewrite-20261121.md](docs/history-rewrite-20261121.md)) and
  are kept out by a commit hook and the project settings (D-109).
- The person sheet changes how a person's payments count (a category for
  all of them), what money from them is (Friend, Family, Ignore, Income) and
  any of their last 10 payments, without opening each one; offline too
  (D-110).
- payback-audit never calls a party silent when any Friend, Family or
  Income answer is on record; `--restore` undoes an earlier fix where a
  Friend answer is now on record (D-111).
- A label made offline can be picked on another payment before it syncs; a
  change the server refused says "Not saved" on its item, with Try again
  and Discard (D-110).
- The API warm job is retired; the phone copy covers a cold start (D-112).
- Polish: transaction amounts show paise only when not zero; one date
  format set; every screen fits 360 px at 200 % text; 44 px targets; eight
  category colours nudged so no two are close; "Not saved" wording; UI
  tokens written down (D-113).

## Phase 4F-B: taps that always sync, SBI parser (21 Nov 2026)

- Fixed: since 4B-2 the browser blocked every change sent from the phone
  (the API did not allow the Idempotency-Key header across origins), so
  changes waited forever with "Could not reach the server". The API now
  allows exactly the app's headers, from one shared list (D-104). Changes
  already waiting on a phone are sent after the update.
- The queue cannot get stuck: it restarts after a crash, tries every 30 s
  while the app is open, and records why each try failed (D-105).
- A tap is saved on the server at once; totals update on the next read
  (D-106).
- "Saved on phone · syncing"; after 2 minutes the reason, with details and
  "Try now"; "Synced" when done; the Sync block leads the Speed sheet
  (D-107).
- SBI messages have their own parser: 53 of the 110 sample messages are read
  (24 before), including amounts without "Rs" and outgoing NEFT (D-108).
- payback-audit never calls an explicit Friend or Family answer silent.
- The API logs one line per request (method, route, status, time).

## Phase 4F-A: other banks, payback safety, logo C2 (20 Nov 2026)

- A careful generic parser reads the money messages of SBI, ICICI, Axis,
  Kotak, YES and India Post until each has its own parser: only with an INR
  amount, a completed action and an account, card, reference or UPI ID; OTPs,
  requests, offers, failed or scheduled payments, mandate notices, bill
  reminders and balance alerts are left out. HDFC results do not change.
  Its rows say "Read automatically" and ask "Looks right?" in To-do (D-101).
- "Not a payment" on any transaction, undone with "Count it again" (D-103).
- After a deploy, the first read brings the totals up to date by itself
  (D-102, migration `0009`).
- Owner commands, counts only: `payback-audit` (paybacks no answer
  confirmed; repair with `--fix --apply` after a dry run, D-099),
  `bank-survey`, `generic-preview`, and `redact-sample` with a leak scan
  (D-100).
- Logo C2: the slanted bolt with the $ cut through it, in the header and
  every icon.
- Tests run on local Postgres 17 as well as SQLite; one test fixed for
  Postgres.

## Phase 4E: people, faster To-do, logo options (20 Nov 2026)

- Name a person and join identifiers on the phone, offline too: "Same as…"
  joins a masked UPI ID to the friend's name, "Separate" undoes it (history
  kept), a name shows everywhere with the identifier under it (D-096). One
  People ledger row, one To-do card and one To confirm sender per person.
  When the two have different answers, the app asks which one stays.
- A category default no longer answers who someone is: "All from" on a
  person-like text keeps their credits to confirm.
- To-do: "See payments" on every card, up to four one-tap category chips.
- One label limit of 30 characters in the app, API and database (D-097,
  migration `0008`). `HEAD /health` (D-098). Sign-out clears the boot
  record.
- Three logo options (A, B, C) for the owner to pick:
  `docs/design/logo-options.html`.

## Phase 4B-3: offline boot (20 Nov 2026)

- The app never opens blank. Signed in on this phone, the phone copy shows
  at once (about 0.1 s in the boot checks), offline too and with an expired
  session; the token refresh runs in the background (D-095).
- A refused session or a 401 keeps the data and the waiting changes and
  shows "Not synced" and "Sign in to sync"; the same login keeps them.
- Offline login says "You're offline. Connect to sign in."
- An error boundary ("Something went wrong", Reload, Copy details), a 3 s
  boot watchdog, and a "Flash could not start" page in `index.html` when
  the app's code fails to load.
- The Speed sheet shows the boot path, the time to the first screen, the
  last 5 boot errors, and a Boot column.

## Phase 4B-2: offline queue for owner actions (19 Nov 2026)

- Every owner action goes through an outbox on the phone (IndexedDB v2):
  saved first, shown on its item as "Waiting to sync", sent in order with
  an `Idempotency-Key`, retried with backoff (5 s, 15 s, 60 s, 5 min); a
  401 keeps it and asks to sign in; a refused one waits in "Couldn't save"
  with Retry and Discard (D-091, D-093).
- Server: `client_ops` (migration `0007`) stores each keyed write's final
  answer, so a resend is applied once (D-092). `X-Defer-Recompute` lets a
  queue of taps run one recompute; every read runs a deferred one first
  (D-094). The label route also takes `{"new_label"}`.
- Sign-out with unsynced changes asks first. A lost session keeps the phone
  copy and the outbox for the same login.
- The Speed sheet is in the URL (`?speed`) and has a Sync block. To-do
  merchant cards show their payment date.

## Phase 4B-1: phone copy and instant open (19 Nov 2026)

- `GET /api/v1/sync/snapshot`: one document with every figure the app
  shows, built from the same functions as the other routes; ETag (SHA-256
  of the canonical JSON without `generated_at`), 304 on If-None-Match,
  gzip (D-088). 704 FAKE transactions over 11 months: 230,686 bytes raw,
  11,918 gzipped, built in 0.13 s on SQLite.
- The server now works out what the app used to add up itself: merchants
  per category, the People ledger, the ring, the changes against last
  month, the To-do merchants (D-088).
- The phone keeps the snapshot in IndexedDB (`idb` 8.0.4) and opens from
  it at once, then refreshes in the background: on launch, on return to
  the app, after an owner action, every 5 minutes while open, when the
  network comes back. "Updated 5 min ago" or "Offline · showing data
  from …" under the month. Wiped on sign-out, another login or another
  schema (D-089).
- Owner actions offline say "You're offline. Try again when connected.";
  nothing is queued yet (4B-2).
- The version line opens a Speed sheet: the last launches measured on the
  phone, kept only there (D-090).

## Phase 4C: install and update prompt (19 Nov 2026)

- Updates wait for the owner: "New version available" with Reload and
  Later; checks on launch, on return to the app and hourly; the app never
  reloads by itself (D-085).
- The service worker precaches the app shell only; no API or auth response
  is cached (D-086).
- Manifest: name "Flash Expense Tracker", `id` and `scope` `/`, splash and
  theme colours equal to the light page colour. Icons unchanged.
- Home shows "Version 0.1.0 · build <commit>" next to Sign out (D-087).
- Docs: NOTES, HANDOFF and PLAN brought up to date; Phase 4 steps in PLAN;
  the Render warm job recorded. npm audit unchanged (4 moderate, build-time
  only, no fix in the same major).

## Phase 3A: groundwork (15 Nov 2026)

- Plan aligned with Phase 3 steps 3A-3F (D-054) and the spend definition
  (D-055); doc fixes in HANDOFF and NOTES. No code.
- D-015 garbled line removed; PLAN.md Phases 1 and 2 renumbered to match the
  tags; owner labels next to categories (D-056). No code.

## Phase 3B: merchant normalisation (15 Nov 2026, tag `phase-3b-done`)

- Pure merchant engine `merchant-1.0.0`: business, person, unsure or none,
  a stable merchant key, and a dictionary of 74 national brands (D-057).
- `python -m app.cli merchant-stats`: counts only, read-only.
- `merchant-1.1.0` (D-058): brand aliases anchored at the start, a display
  name for every merchant, UPI handle signals, 186 business keywords.
  `merchant-stats` adds kind by direction, keys by kind and key coverage;
  owner-only `merchant-review` (terminal only).
- `merchant-1.1.1` (D-068): a name beside a UPI ID is the display name;
  the UPI ID stays the key.

## Phase 3C: Reconcile and the derived-data backbone (15-16 Nov 2026)

- Design of the derived-data backbone and Reconcile
  ([docs/design/phase-3-backbone.md](docs/design/phase-3-backbone.md)),
  approved with D-059 to D-067: one role per transaction, owner data kept
  apart from derived data, duplicates linked and never merged.
- 3C-2: pure engine `reconcile-1.0.0`. Exactly one role per transaction
  with the deciding rule and its basis (engine or owner), every rule that
  reads one transaction, owner data in memory, and `totals()` (Spent, Paid
  back, Net, Income as sums over roles).
- `python -m app.cli reconcile-stats`: counts only, read-only.
- 3C-3 and 3C-5: `reconcile-1.1.0`. `derive()` also returns links.
  Duplicates: a unique AutoPay + card spend pair inside 10 minutes is
  linked and counts once; every other same-amount pair is a candidate;
  no existing candidate is lost. Pair linking: the second leg of a
  self-transfer, refund to purchase (30 days, same card or account), the
  FD second credit (candidate only). A link is made only for a unique
  pair; owner "same" and "different" decisions are an input.
  `reconcile-stats` adds links, candidates by reason, AutoPay + card time
  gaps and the fate of the existing candidates.
- `reconcile-1.2.0` (D-069): a same-amount pair with two different
  references is two payments. Reconcile no longer proposes it and import
  no longer records it; pairs already recorded are kept.
- 3C-4: migration `0004`, six owner tables (own accounts and their
  identifiers, parties and their texts, link and role decisions), RLS on.
  `python -m app.cli owner-load <file>` loads the owner's private JSON
  file: strict checks, errors by field path, only file rows replaced
  (D-070). Example: `docs/owner.example.json`.
- 3C-6: migration `0005`, three derived tables (`txn_derived` with the
  merchant and role of every transaction, `txn_links`, `derive_runs`), RLS
  on. `python -m app.cli recompute` writes only what changed, in one
  transaction; it runs after import, reparse and owner-load; it stops when
  a merchant engine change would lose an owner match. `reconcile-stats`
  reads the owner tables and shows the stored run. Invariants I10 to I21
  tested.
- 3C-7 and 3C-8: `reconcile-review` (owner only: same, different or skip
  for candidates; a role for uncertain credits and debits with no payee),
  `owner-export` (every owner row, decisions by dedupe key; `owner-load`
  restores it into empty tables), `totals --month` (owner only: Spent,
  Paid back by basis, Net, Income for an IST month). `reconcile-1.2.1`
  (D-072): a mandate ID and a payment reference are different kinds.
  Duplicate primary confirmed (D-071).

## Phase 3 complete (18 Nov 2026)

- Steps 3A to 3F done: merchant engine, Reconcile and the derived-data
  backbone, categories and labels, login and the data API, and the app on
  real data. Verified by the owner: login and saving on the phone, owner
  corrections kept through reparse and recompute, a backup.
- Open, carried to Phase 4 as its first item: the bank statement check.
- [docs/OVERVIEW.md](docs/OVERVIEW.md): a one-page tour for new readers.

## Phase 3F: screens (17 Nov 2026)

- 3F-1: every screen on demo data ([docs/ui-spec.md](docs/ui-spec.md)): login, Home
  (Net, Spent, Paid back, To confirm, Spent by category), category detail,
  Transactions with a detail sheet and corrections, To-do (senders, uncategorised
  merchants), Labels. A demo adapter behind one `Api` interface returns the shapes
  of docs/api.md; a banner and a state switch (waking, empty, error, stale).
- Money and IST date helpers tested with Node's built-in test runner (no new
  package); the frontend CI job also runs lint and tests.
- 3F-2: the whole view lives in the URL hash (tab, month, detail, person,
  label, open sheet, filters, search); reload and cold links restore it, Back
  closes the sheet, then the detail, then reaches the tab root; lists keep
  their scroll; loaded data is reused, and "Starting up" shows only when the
  session's first request takes over 3 s.
- 3F-2 design pass: Lucide line icons (27 SVGs copied, ISC, no package), tab
  icons, Home comparison with last month and Recent, people ledger and
  person view, Transactions search with sticky day headers, To-do Confirmed
  section and leaving rows, label totals, label-name rules (1 to 30, no
  duplicates in any case). Fixes: banner in the page flow, bars as share of
  Spent, To-do buttons on one line. Three logo options on `#/dev/logos`.
  API gaps for 3F-3 listed in docs/ui-spec.md.
- 3F-3 API (D-079): `role_basis` and `person_id` on transaction items,
  `GET /transactions/{id}`, `previous` in `/summary`, totals on `/labels`,
  ignored senders, `DELETE /senders/{id}`, `income_label`, label names 1 to
  30 characters with 409 for a duplicate.
- 3F-3 app (D-080): real login with `@supabase/supabase-js` 2.119.0 and the
  HTTP adapter; 401 to login, 403 "no access", 503 and offline with retry;
  Sign out; demo only in dev with `VITE_DEMO=1`. Client workarounds removed.
- 3F-3 design (D-081 to D-083): 20 muted category colours on tiles, bars and
  a hand-drawn ring chart (List | Chart); the $ mark and FLA$H wordmark; PWA
  icons, favicon and apple-touch-icon from the mark.
- 3F-3 backup (D-084): `scripts/backup_db.ps1` (pg_dump from `postgres:17`
  in Docker, custom format, to `D:\FlashPrivate\backups`); restore note in
  NOTES.md.

## Phase 3E: login and API (16 Nov 2026)

- Login: Supabase Auth ES256 tokens checked against the project's JWKS;
  `AUTH_USERS` maps users to owners (D-078). PyJWT 2.15.1, cryptography 50.0.2.
- Data API under `/api/v1` (`docs/api.md`): summary, transactions, categories,
  labels, senders; corrections with source `app`, each with one recompute.
- `reconcile-1.3.0`: only owner-confirmed paybacks lower Net, the rest is To
  confirm (D-076); own accounts inferred from the messages (D-077).
- `credit-review` (owner only). No feature needs the owner file (D-075).

## Phase 3D: categorise (16 Nov 2026)

- Pure engine `categorise-1.0.0` (D-073, D-074): one category per
  transaction from a fixed list of 20; owner decision, party default, role
  and channel, brand, keyword, person, else Uncategorised. Linked refunds
  take their purchase's category. The breakdown adds up exactly to Spent.
- Migration `0006`: `parties.category`, `owner_categories`, `labels`,
  `txn_labels`, category columns on `txn_derived`. Export and restore cover
  them.
- `category-stats` (counts only), `category-review` (owner only),
  `totals --month` with the category breakdown. Invariants I22 to I27.

## Phase 2: database, SMS import, dedupe (14 Nov 2026, tag `phase-2-done`)

- Migration `0002`: `import_batches`, `raw_messages`, `parse_results`,
  `transactions`, `transaction_sources`, `duplicate_candidates`. BIGINT paise,
  timestamptz UTC, row level security enabled on Postgres
  ([docs/data-model.md](docs/data-model.md)).
- Dedupe: raw `content_hash` without the source; transaction keys on a
  per-payment reference (account excluded) or the raw message; mandate IDs
  never merge monthly charges (`mandate_reference`, `hdfc-1.1.1`) (D-046).
- Fuzzy duplicate candidates recorded, never merged; merging moves to
  Reconcile (D-047).
- Importer for SMS Backup & Restore XML: registry senders only, never OTP,
  promotional or MMS; OTP rule shared with the redaction script (D-049).
  Batched commits, crash-safe re-runs, dry run.
- Reparse to the current parser version per bank, ids stable, nothing
  deleted.
- CLI `python -m app.cli import-sms | reparse | stats`, counts only.
- Tests: invariants I1-I9; a CI job on Postgres 17 runs migrations,
  `alembic check` and the backend tests.
- Real data lives in Supabase; AI tools never connect to it (D-048). Render
  deploys only after CI passes (D-050).
- Real import: 917 messages stored, 678 transactions, 18 duplicate
  candidates; re-import added nothing.
- Lock-in: the full redacted export stays in the private folder (D-051); one
  cron heartbeat job with retries replaces the wake-up job (D-052).

## Phase 1: redaction and the HDFC parser (14 Nov 2026, tag `phase-1-done`)

- Redaction hardening: sender ID normalisation and a 14-core allowlist
  (D-025, D-026, D-038), bank wording never redacted and link paths faked
  (D-039), always-redact list and `--verify` leak check (D-040), mandate IDs
  and payee names redacted (D-045).
- HDFC template survey on the redacted sample: 15 shapes, fake fixtures only
  (D-027, [docs/templates/hdfc.md](docs/templates/hdfc.md)). Parsing
  questions resolved (D-028 to D-037), including foreign currency deferred
  (D-035).
- Stdlib-only parser engine `backend/app/engine/` (D-041, D-043): literal
  whole-body templates, exactly one may match, strict fields, versioned per
  bank (D-042). `hdfc-1.0.0`, then `hdfc-1.1.0` with H16-H21 and the
  amount-free notice fallback `H_INFO` (D-044).
- `scripts/parse_coverage.py`: counts and Unknown shapes only. Full data: 764
  HDFC messages, 0 left without a template.

## Phase 0: scaffold and deploy (12-13 Nov 2026, tag `phase-0-done`)

- Monorepo: FastAPI backend, Vite React PWA, scripts, infra, docs (D-005);
  paise and UTC rules (D-001, D-002); idempotent ingestion and raw messages
  kept with parser versions as principles (D-003, D-004).
- Exact dependency pins and lockfiles (D-007), LF endings (D-009), httpx kept
  and no unverified packages (D-010).
- `/health` and `/health/db` keep-alive with a header token and a real DB
  write (D-011, D-017); migration `0001` heartbeat; migrations in the Render
  build (D-018).
- Default-deny redaction script; raw SMS outside the repo; agents denied
  `.env` and private data (D-008, D-014, D-015, D-016, D-019).
- Free-tier hosting in Singapore: Vercel, Render, Supabase, cron-job.org
  (D-006, D-012, D-013, D-021 to D-024).
