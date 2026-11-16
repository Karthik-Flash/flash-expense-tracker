# Changelog

What shipped in each phase. Decision numbers refer to
[docs/DECISIONS.md](docs/DECISIONS.md). Phases follow the prompt labels:
Phase 1 is parsing, Phase 2 is the database and import.

## Phase 3A: groundwork (15 Nov 2026, in progress, tag `phase-3a-done` when done)

- Plan aligned with Phase 3 steps 3A-3F (D-054) and the spend definition
  (D-055); doc fixes in HANDOFF and NOTES. No code.
- D-015 garbled line removed; PLAN.md Phases 1 and 2 renumbered to match the
  tags; owner labels next to categories (D-056). No code.

## Phase 3B: merchant normalisation (15 Nov 2026, in progress, tag `phase-3b-done` when done)

- Pure merchant engine `merchant-1.0.0`: business, person, unsure or none,
  a stable merchant key, and a dictionary of 74 national brands (D-057).
- `python -m app.cli merchant-stats`: counts only, read-only.
- `merchant-1.1.0` (D-058): brand aliases anchored at the start, a display
  name for every merchant, UPI handle signals, 186 business keywords.
  `merchant-stats` adds kind by direction, keys by kind and key coverage;
  owner-only `merchant-review` (terminal only).
- `merchant-1.1.1` (D-068): a name beside a UPI ID is the display name;
  the UPI ID stays the key.

## Phase 3C: Reconcile and the derived-data backbone (15 Nov 2026, in progress, tag `phase-3c-done` when done)

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
