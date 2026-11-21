# History rewrite, 21 Nov 2026

## Why

The owner does not want AI attribution lines in this project's commits
(D-109). 116 of the 160 commits on `main` carried a `Co-Authored-By: Claude …
<noreply@anthropic.com>` trailer. They were removed with built-in git:

```sh
git filter-branch --msg-filter 'python strip_attr.py' --tag-name-filter cat -- --branches --tags
```

The filter drops lines matching `Co-Authored-By: …Claude|Anthropic…`,
`Claude-Session: …` and `Generated with [Claude Code]`, and the blank lines
they leave at the end. Nothing else in any message changed. Authors, author
and committer dates, parents and trees are identical; every old ref and its
new ref have an empty `git diff`. Annotated tags keep their tagger, date and
message. Commit and tag counts are unchanged (160 commits, 9 tags).

`refs/remotes/origin/main` was not rewritten: it still shows what GitHub
holds (old `076ee9f`) until the owner force-pushes, so
`git push --force-with-lease` can check it.

New commits are kept clean by `.githooks/commit-msg` (enable per clone with
`git config core.hooksPath .githooks`) and by `attribution` in
`.claude/settings.json`.

## Refs, old -> new

| Ref | Old commit | New commit | New tag object |
| --- | --- | --- | --- |
| `main` | `076ee9f6eb7d` | `c216442cd433` | (branch) |
| `phase-0-done` | `ac00d862a249` | `c2dcbdc32616` | `ebb05dfd50f8` |
| `phase-1-done` | `dc49cc31c065` | `089b5cb5c69e` | `99dccff0af0d` |
| `phase-2-done` | `18532c6f4bab` | `da8afc5bc086` | `e4af595bc14e` |
| `phase-3-done` | `f0a81306c6fe` | `b22208df7ab1` | (lightweight) |
| `phase-3b-done` | `94ef8c407aac` | `c357dd97be7b` | (lightweight) |
| `phase-4b-done` | `514c515ef45e` | `e2655d8ccffd` | `931e83307985` |
| `phase-4b1-done` | `bccb9744e380` | `322e4a4e2267` | `904b651523d7` |
| `phase-4c-done` | `a1b82066ef96` | `65684d99d5a6` | `383f94d90745` |
| `phase-4e-done` | `076ee9f6eb7d` | `c216442cd433` | `104fbedd19c7` |

`main` before 4H was `076ee9f`; it is now `c216442`. Older notes, reports
and log entries that quote an old SHA can be read through the table below.

## Restore from the backup

A full mirror of the repo before the rewrite is at
`D:\Projects\FinancesApp-backup-20261121.git` (outside the repo; every branch
and tag, checked ref by ref). To go back:

```sh
git fetch D:/Projects/FinancesApp-backup-20261121.git "+refs/heads/*:refs/heads/*" "+refs/tags/*:refs/tags/*"
# or start over from it:
git clone D:/Projects/FinancesApp-backup-20261121.git FinancesApp-restored
```

Before the owner force-pushes, GitHub still holds the old history too.

## Every commit on main, old -> new

| Old | New | Date | Subject |
| --- | --- | --- | --- |
| `076ee9f` | `c216442` | 2026-11-21 | Merge branch 'phase-4f-b' |
| `664356b` | `91ede25` | 2026-11-21 | docs: CORS, stuck queue, writes before recompute, SBI (4F-B) |
| `ed78daf` | `a2d08da` | 2026-11-21 | feat(frontend): an outbox that cannot get stuck, "Saved on phone" (4F-B) |
| `282d107` | `4a8b3a6` | 2026-11-21 | feat(backend): writes before recompute, explicit answers, SBI parser (4F-B) |
| `b281e03` | `a56e009` | 2026-11-21 | fix(api): allow the app's write headers across origins (4F-B) |
| `2a1e460` | `056771d` | 2026-11-20 | Merge branch 'phase-4f-a' |
| `516c824` | `edaf2be` | 2026-11-20 | docs: generic parser, checks, owner commands, D-099 to D-103 (4F-A) |
| `8276699` | `f50b3f2` | 2026-11-20 | feat(frontend): check these payments, not a payment, logo C2 (4F-A) |
| `bcccb58` | `a0b21f8` | 2026-11-20 | feat(backend): generic parser, checks, payback audit, bank survey (4F-A) |
| `3555c9b` | `44f55d0` | 2026-11-20 | test(backend): label limit test passes on Postgres too (4F-A) |
| `57a3b48` | `0849a1d` | 2026-11-20 | Merge branch 'phase-4e-people' |
| `cfec500` | `576d46c` | 2026-11-20 | docs: people design, logo options, D-096 to D-098, new order (4E) |
| `c7b334e` | `d2e8040` | 2026-11-20 | feat(frontend): people sheet, same as, see payments, chips (4E) |
| `a31d857` | `3639ea8` | 2026-11-20 | fix(backend): a join keeps the name the person is shown by (4E) |
| `2731680` | `e291cc1` | 2026-11-20 | feat(backend): name and join people, label limit 30, HEAD /health (4E) |
| `514c515` | `e2655d8` | 2026-11-20 | Merge branch 'phase-4b3-offline-boot' |
| `ffd6bd4` | `42fed4d` | 2026-11-20 | docs: offline boot and D-095 (4B-3) |
| `d12b9fc` | `e1585d1` | 2026-11-20 | fix(frontend): boot never waits on the network, never blank (4B-3) |
| `d48717d` | `1802f16` | 2026-11-19 | Merge branch 'phase-4b2-outbox' |
| `1f20678` | `3de9f54` | 2026-11-19 | docs: outbox, idempotency and deferred recompute (4B-2) |
| `8707cf2` | `018bdcc` | 2026-11-19 | feat(frontend): outbox for owner actions, waiting markers, sync line (4B-2) |
| `b4ffc17` | `0c764bc` | 2026-11-19 | feat(backend): Idempotency-Key on owner writes, deferred recompute (4B-2) |
| `bccb974` | `322e4a4` | 2026-11-19 | Merge branch 'phase-4b1-local-copy' |
| `79ed57f` | `e8f994d` | 2026-11-19 | docs: snapshot, phone copy and Speed sheet (4B-1) |
| `2612c55` | `0211eb0` | 2026-11-19 | feat(frontend): phone copy in IndexedDB, read path from the snapshot (4B-1) |
| `f23f035` | `2f35d90` | 2026-11-19 | feat(backend): GET /api/v1/sync/snapshot, ETag and gzip (4B-1) |
| `a1b8206` | `65684d9` | 2026-11-19 | Merge branch 'phase-4c-install' |
| `8733072` | `e274dc0` | 2026-11-19 | docs: Phase 4 plan, 4C decisions and docs cleanup |
| `1c78f1b` | `a371f73` | 2026-11-19 | feat(frontend): update prompt, app-shell cache, manifest and build id (4C) |
| `f0a8130` | `b22208d` | 2026-11-18 | Merge branch 'docs/close-phase-3' |
| `500eba4` | `e91c070` | 2026-11-18 | docs: close Phase 3 (overview, plan, handoff) |
| `fa37e42` | `133f08c` | 2026-11-17 | Merge branch 'feat/3f-3-close-phase-3' |
| `bc16486` | `c33aac9` | 2026-11-17 | docs: backup script and Phase 3 docs (3F-3 D) |
| `02f50aa` | `c9dfdde` | 2026-11-17 | feat(frontend): category colours, ring chart and the FLA$H logo (3F-3 C) |
| `68cd7fa` | `23aa5f1` | 2026-11-17 | feat(frontend): real login and data adapter (3F-3 B) |
| `f65d071` | `2b920a5` | 2026-11-17 | feat(backend): close the 3F-2 API gaps (3F-3 A) |
| `8c52cac` | `412ce17` | 2026-11-17 | Merge branch 'feat/3f-2-nav-design' |
| `bbac079` | `7c7f671` | 2026-11-17 | feat(frontend): URL state, Back by layers, icons and design pass (3F-2) |
| `fca9e3b` | `c7b1aa4` | 2026-11-17 | Merge branch 'feat/3f-1-screens' |
| `9daf263` | `12c6a7c` | 2026-11-17 | feat(frontend): every screen on demo data, UI spec (3F-1) |
| `ae42c87` | `a3ba5ef` | 2026-11-16 | Merge branch 'feat/3e-api' |
| `1077cf4` | `4cc89b6` | 2026-11-16 | feat(backend): login, data API, confirmed-only paybacks, inferred own accounts (3E) |
| `41d5a98` | `adf6363` | 2026-11-16 | Merge branch 'feat/3d-categorise' |
| `a43c7a6` | `d532a0f` | 2026-11-16 | feat(backend): category storage, owner corrections, labels, commands (3D, migration 0006) |
| `01e7aa0` | `cb8ea1a` | 2026-11-16 | feat(backend): categorise-1.0.0, one category per transaction in memory (3D) |
| `7a5b114` | `689c3ae` | 2026-11-16 | Merge branch 'feat/3c-7-8-review' |
| `4f57abd` | `bedac6c` | 2026-11-16 | feat(backend): reconcile-review, owner-export, totals (3C-7, 3C-8) |
| `33c41fc` | `80dc3d4` | 2026-11-16 | Merge branch 'feat/3c-4-6-storage' |
| `40b19e0` | `86cc474` | 2026-11-16 | feat(backend): derived storage and recompute (3C-6, migration 0005) |
| `615b9be` | `8698e6f` | 2026-11-16 | feat(backend): owner tables and owner-load (3C-4, migration 0004) |
| `488a86c` | `1a193ed` | 2026-11-16 | feat(backend): reconcile-1.2.0, two different references are two payments (D-069) |
| `c2c6600` | `0257a59` | 2026-11-16 | Merge branch 'feat/3c-3-links' |
| `cee169f` | `93590a7` | 2026-11-16 | feat(backend): reconcile-1.1.0, duplicates and pair linking in memory (3C-3, 3C-5) |
| `94ef8c4` | `c357dd9` | 2026-11-16 | Merge branch 'feat/3c-2-roles' |
| `e6144aa` | `d3a8ccf` | 2026-11-16 | feat(backend): reconcile-1.0.0, one role per transaction in memory (3C-2) |
| `c2f3705` | `e6e8386` | 2026-11-16 | fix(backend): merchant-1.1.1 shows the name when a UPI ID sits beside it |
| `0354747` | `5be5687` | 2026-11-16 | docs: record the planner's decisions on the Phase 3 backbone (D-059 to D-067) |
| `c8a7b97` | `4fca72e` | 2026-11-15 | Merge branch 'docs/phase-3-backbone' |
| `2bf7cc4` | `4e92d3d` | 2026-11-15 | docs: design the derived-data backbone and Reconcile (3C-1) |
| `f36ac96` | `88d84b0` | 2026-11-15 | Merge branch 'feat/merchant-1.1' |
| `ce788e6` | `afc79e7` | 2026-11-15 | feat(backend): merchant engine 1.1.0, wider survey, owner-only review |
| `459e669` | `2f0106f` | 2026-11-15 | Merge branch 'feat/merchant-engine' |
| `3fca5cd` | `b8ef331` | 2026-11-15 | feat(backend): merchant normalisation engine and merchant-stats survey |
| `4c5f257` | `8f2a6f8` | 2026-11-15 | Merge branch 'docs/stale-phase-notes' |
| `8de43de` | `194ef1c` | 2026-11-15 | docs: remove stale phase-numbering notes |
| `c9cd540` | `616145d` | 2026-11-15 | Merge branch 'docs/phase-3-labels' |
| `ecf5fa6` | `0c607c6` | 2026-11-15 | docs: fix D-015, align Phase 1/2 with tags, add owner labels |
| `08e7759` | `38d36b0` | 2026-11-15 | Merge branch 'docs/phase-3-plan' |
| `c99eecc` | `203ba96` | 2026-11-15 | docs: align plan with Phase 3, record spend definition, fix doc errors |
| `24c123d` | `126f2d0` | 2026-11-15 | Merge branch 'docs/keepalive-verified' |
| `6606624` | `49b8b59` | 2026-11-15 | docs: keep-alive switch-over verified; ask before starting Docker |
| `f41fc9c` | `7bfa378` | 2026-11-15 | Merge branch 'feat/keepalive-data-api' |
| `5fb7573` | `21c42b3` | 2026-11-15 | docs: keep-alive through the Supabase Data API (D-053) |
| `64e3392` | `75a01e4` | 2026-11-15 | feat(backend): keepalive schema with ping() for the Data API heartbeat |
| `18532c6` | `da8afc5` | 2026-11-14 | Merge branch 'docs/lock-in' |
| `7b52ca5` | `a0281bd` | 2026-11-14 | docs(notes): tag commands in the git cheat sheet |
| `176f79d` | `4c9d71b` | 2026-11-14 | docs: CHANGELOG, HANDOFF for fresh sessions; CLAUDE.md points to it |
| `99eb2b3` | `0781bd6` | 2026-11-14 | docs: Phases 0-2 done in PLAN; real import in NOTES; dry-run id note |
| `9f0a4e1` | `ca2994a` | 2026-11-14 | docs: one cron heartbeat job with retries (D-052); deploy after CI; import flow |
| `4d1fd95` | `39520a7` | 2026-11-14 | docs: full redacted export lives in the private folder (D-051) |
| `d1b2df0` | `0ff5e9c` | 2026-11-14 | Merge branch 'feat/phase2-import' |
| `f2cb355` | `6df8e36` | 2026-11-14 | docs: data model, dedupe and import decisions D-046 to D-050, NOTES |
| `46c673a` | `0a4aa67` | 2026-11-14 | fix(pipeline): reparse prints progress every 5,000 messages, not each one |
| `ce94894` | `90459c3` | 2026-11-14 | ci: backend job on a Postgres 17 service container |
| `763b15c` | `6a31fec` | 2026-11-14 | fix(pipeline): never merge charges on a mandate reference |
| `72d50a9` | `3704b28` | 2026-11-14 | feat(engine): mark AutoPay mandate references (hdfc-1.1.1) |
| `51b4150` | `8491032` | 2026-11-14 | fix(backend): store references as TEXT |
| `cdbebc6` | `15b843c` | 2026-11-14 | feat(backend): app.cli import-sms, reparse and stats; invariant tests |
| `0d5d4fc` | `d420439` | 2026-11-14 | feat(pipeline): reparse stale results without deleting anything |
| `94bc8cc` | `9113443` | 2026-11-14 | feat(pipeline): SMS Backup & Restore importer and per-message store |
| `3f3bf2e` | `af534d1` | 2026-11-14 | feat(pipeline): dedupe rules as pure functions |
| `80009b6` | `cc6beef` | 2026-11-14 | fix(engine): keep "never asks for OTP" advisories (engine and redaction) |
| `4bcb35e` | `39015d5` | 2026-11-14 | feat(backend): import pipeline schema and migration 0002 |
| `396b85f` | `021ed1e` | 2026-11-14 | feat(engine): OTP and promotional filters with a shared OTP case table |
| `dc49cc3` | `089b5cb` | 2026-11-14 | Merge branch 'feat/hdfc-gaps' |
| `36a23ba` | `e1652af` | 2026-11-14 | docs: HDFC H16-H21, H_INFO fallback, decisions D-044 and D-045, NOTES |
| `88211ef` | `bf01afa` | 2026-11-14 | fix(scripts): redact Mandate/SI Hub IDs and names after "added a payee" |
| `25b3b9c` | `1b45d78` | 2026-11-14 | feat(engine): HDFC templates H16-H21 and amount-free notice fallback (hdfc-1.1.0) |
| `b10e931` | `56884de` | 2026-11-14 | Merge branch 'feat/hdfc-parser-engine' |
| `97fb164` | `54cf472` | 2026-11-14 | docs: engine guide, parser decisions D-041 to D-043, NOTES |
| `57eb854` | `dd4b0a4` | 2026-11-14 | feat(scripts): parse_coverage prints engine counts and Unknown shapes |
| `fe1ea4e` | `0e44fa6` | 2026-11-14 | feat(engine): template parser base and HDFC parser (hdfc-1.0.0) |
| `fedc087` | `bb39ba9` | 2026-11-14 | feat(engine): sender IDs, money, time and result models |
| `4547060` | `c7bdb3b` | 2026-11-14 | docs(templates): HDFC re-survey on the refreshed sample |
| `e8cfd3b` | `393a040` | 2026-11-14 | Merge branch 'feat/always-redact-verify' |
| `7ee0b0b` | `208a07b` | 2026-11-14 | docs: standard sample command with --verify; always-redact setup; D-040 |
| `55a7564` | `ca72ffc` | 2026-11-14 | feat(scripts): always-redact list and --verify leak check |
| `7ab71e4` | `396dd83` | 2026-11-14 | Merge branch 'fix/redaction-1b' |
| `d513e7e` | `ee84fa5` | 2026-11-14 | docs: resolved HDFC questions; decisions D-028 to D-039; NOTES |
| `55ed896` | `6858bd8` | 2026-11-14 | test(backend): fixtures gain time_inferred, upcoming_debit and fd |
| `705b008` | `11c2b06` | 2026-11-14 | fix(scripts): hyphen-aware sender IDs; never redact bank wording; fake link paths |
| `d449c4e` | `ab16c00` | 2026-11-14 | Merge branch 'feat/hdfc-template-survey' |
| `bab36aa` | `7935441` | 2026-11-14 | docs: NOTES for HDFC survey; D-027 survey and fixture rules |
| `e353bb1` | `c20fdb4` | 2026-11-14 | test(backend): fake HDFC SMS fixtures with structural checks |
| `1cee7c5` | `8066940` | 2026-11-14 | docs(templates): HDFC shapes, proposed types, open questions |
| `d58b1a5` | `24c1869` | 2026-11-14 | feat(scripts): shape_survey groups redacted SMS into template shapes |
| `60a54be` | `46755bf` | 2026-11-14 | Merge branch 'fix/sender-normalisation' |
| `c90b2de` | `c2f0d68` | 2026-11-14 | docs: sender normalisation rules and allowlist decisions (D-025, D-026) |
| `465744c` | `3e9f4f6` | 2026-11-14 | fix(scripts): normalise sender IDs to their core; bank/UPI allowlist |
| `ac00d86` | `c2dcbdc` | 2026-11-13 | Merge branch 'docs/phase-0-deploy' |
| `2ffad59` | `86c0257` | 2026-11-13 | docs: decisions D-021 to D-024 |
| `f09df21` | `766a45f` | 2026-11-13 | docs: Phase 0 deploy done in PLAN; two items left |
| `08a9807` | `fc49e27` | 2026-11-13 | docs(infra): runbook; render.yaml renamed to the live service |
| `96f1f61` | `e90188c` | 2026-11-13 | docs: NOTES.md deploy log, architecture flows and gotchas |
| `aa0c070` | `b0930ca` | 2026-11-13 | Merge branch 'docs/closeout-addendum' |
| `a2a1ee7` | `70f8617` | 2026-11-13 | docs: NOTES.md for closeout addendum |
| `b43c21e` | `22acdb6` | 2026-11-13 | docs: /health/db done in Phase 0; decisions D-015 to D-020 |
| `d0a6653` | `e60f3d3` | 2026-11-13 | docs: real data outside repo; default-deny redaction; secrets rules |
| `3903cac` | `cd37909` | 2026-11-13 | chore(infra): migrate in build step; X-Ping-Token in cron and docs |
| `92ab323` | `370f625` | 2026-11-13 | Merge branch 'chore/pins-and-secrets' |
| `9e56798` | `2b138f1` | 2026-11-13 | chore(frontend): exact dependency pins and save-exact |
| `7914a7e` | `0af085b` | 2026-11-13 | Merge branch 'feat/health-db-hardening' |
| `8bd1ac9` | `3f0786a` | 2026-11-13 | chore: deny agent reads of .env files and D:/FlashPrivate |
| `d41a723` | `07038e7` | 2026-11-13 | Merge branch 'feat/redaction-default-deny' |
| `a345962` | `843f58b` | 2026-11-13 | feat(backend): X-Ping-Token header auth for /health/db; DB-side time |
| `c75be35` | `0919561` | 2026-11-13 | feat(scripts): default-deny redaction with keep-list and required paths |
| `d41292f` | `a63c693` | 2026-11-13 | feat(backend): normalise DATABASE_URL to psycopg; small engine pool |
| `a2e5162` | `ed4b1f0` | 2026-11-13 | Merge branch 'docs/phase-0-closeout' |
| `5a7ef9b` | `089c2c7` | 2026-11-13 | docs: NOTES.md as cheat sheet; Phase 0 closeout log |
| `1e9d55d` | `dbe69c6` | 2026-11-13 | docs: agent rules for data/private and redaction workflow |
| `cb459ed` | `ebe56bf` | 2026-11-13 | docs: record decisions D-010 to D-014 |
| `68a64af` | `c455f7d` | 2026-11-13 | docs(infra): click-by-click deploy guide; migrations in start command |
| `7c29104` | `53dcd14` | 2026-11-13 | Merge branch 'feat/health-db' |
| `d203db8` | `096db36` | 2026-11-13 | feat(backend): token-protected /health/db keep-alive endpoint |
| `b5906c6` | `38578a2` | 2026-11-13 | feat(backend): heartbeat table and first Alembic migration |
| `0ff102b` | `ac3c3ad` | 2026-11-13 | Merge branch 'feat/redact-sms-hardening' |
| `1a1be38` | `8e4fcf5` | 2026-11-13 | feat(scripts): harden redact_sms for large real backups |
| `191aaf3` | `76767e3` | 2026-11-13 | Merge branch 'chore/agent-deny-rules' |
| `58cf5b4` | `4a2ba61` | 2026-11-13 | chore: block agent reads of data/private and XML outside mobile/ |
| `96e8e5b` | `d5b4f8d` | 2026-11-12 | docs: add NOTES.md progress log for session 1 |
| `a24774c` | `d71a76f` | 2026-11-12 | Merge branch 'chore/ci-and-infra' |
| `e86a690` | `c056ece` | 2026-11-12 | Merge branch 'feat/redact-sms-script' |
| `8823713` | `ca71f72` | 2026-11-12 | chore(infra): Render blueprint and hosting guide |
| `e7eeeb1` | `cb0c249` | 2026-11-12 | Merge branch 'feat/frontend-skeleton' |
| `fa1a720` | `37054e3` | 2026-11-12 | feat(scripts): stdlib SMS redaction tool for sample data |
| `0be5c88` | `fff8453` | 2026-11-12 | ci: ruff and pytest for backend, typecheck and build for frontend |
| `c9d6698` | `10ed5db` | 2026-11-12 | Merge branch 'feat/backend-skeleton' |
| `5836acf` | `db73399` | 2026-11-12 | feat(frontend): Vite React PWA shell showing backend status |
| `807abd6` | `dc2673f` | 2026-11-12 | chore: repo hygiene, editor config and project docs |
| `637f7d4` | `10fbb53` | 2026-11-12 | feat(backend): FastAPI walking skeleton with /health and CORS |
