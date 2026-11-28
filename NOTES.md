# Notes

Status, open items and where things are. Updated after every task. The commands are in
[docs/operations.md](docs/operations.md); how the system works is in
[Flashexpensetracker_Explained.md](Flashexpensetracker_Explained.md).

## Status

**Phase 5 is done and deployed** (28 Nov 2026): Flash on Android with bank SMS read on the
phone, several users with invites, Insights (analytics, export, profile, admin), rules and
per-credit answers, the back button, categorise-1.4.0, To-do clean-up and weekly backups.
Tags: `phase-5-done`, `phase-5-final`, `phase-5-wrapped`. The project pauses for about a
month; then **Phase 6: the Play Store** (below).

Engine versions: `hdfc-1.2.0`, `sbi-1.0.0`, `generic-1.0.0`, `stmt-hdfc-1.1.0`,
`merchant-1.1.1`, `reconcile-1.7.1`, `categorise-1.4.0`. Alembic head: `0019`. Decisions:
D-001 to D-158 ([docs/DECISIONS.md](docs/DECISIONS.md)). What changed when:
[CHANGELOG.md](CHANGELOG.md). The per-task log of Phases 0 to 5 is in git history (tag
`phase-5-final`).

## Where things are

| What | Where |
| --- | --- |
| How it all works, file by file | [Flashexpensetracker_Explained.md](Flashexpensetracker_Explained.md) |
| Owner and developer commands, deploy steps, test plan | [docs/operations.md](docs/operations.md) |
| Why each choice was made | [docs/DECISIONS.md](docs/DECISIONS.md) |
| API, data model, engine | [docs/api.md](docs/api.md), [docs/data-model.md](docs/data-model.md), [docs/engine.md](docs/engine.md) |
| What Flash stores (privacy) | [docs/privacy.md](docs/privacy.md) |
| The To-do screen's logic | [docs/todo-screen.md](docs/todo-screen.md) |
| UI rules | [docs/ui-spec.md](docs/ui-spec.md) |
| Rules for Claude Code | [CLAUDE.md](CLAUDE.md) |

## Architecture

See [Flashexpensetracker_Explained.md](Flashexpensetracker_Explained.md), "System
overview" and "Infrastructure and cost".

## Back up and restore

See [docs/operations.md](docs/operations.md), "Back up and restore": the weekly task, the
manual run and a restore into a throwaway database first.

## Phase 6: the Play Store (next)

- Release signing (Play App Signing) and an Android App Bundle instead of the debug APK.
- The SMS permissions (READ_SMS, RECEIVE_SMS) need Google's approval through the
  Permissions Declaration as the app's core feature: plan for review time.
- A new personal developer account must run a closed test with at least 12 testers for 14
  days in a row before it can publish to production.
- The privacy policy (from [docs/privacy.md](docs/privacy.md)) and the store listing.

Later (Phase 7): statements, Gmail, budget cycles, roommate splits, subscriptions, a
first-salary mode, investment senders (D-026).

## Open items

Owner to-dos (some may already be done):

1. Vercel: `VITE_API_URL` is saved as a Secret; change it to a plain variable and redeploy
   with the build cache off.
2. Delete the cron-job.org job "Flash API warm 07-01 IST" if it is still there (D-112);
   `git config core.hooksPath .githooks` in every clone (D-109).
3. Register the weekly backup task once (docs/operations.md, "Back up and restore").
4. Add the name variants under Insights > Profile > "Your name as banks show it", so "Is
   this you?" can work; work through the To-do backlog.
5. `statement-import --apply` and `statement-names --apply` wait for the planner's OK
   after fresh dry runs; re-check September with `stmt-hdfc-1.1.0` ("balance breaks" 0).
6. `payback-audit --restore` (dry run) and the planner's call on `--apply` (D-111).
7. Verify the October People total person by person.

Not yet seen on a real phone (checked in headless Edge and by tests): the notification's
instant sheet, the back button with predictive back, Leave as is, This is income, Getting
started, About's versionCode, per-credit answers, Your rules, Analytics, the export share
sheet, the person sheet actions, "Moved between your accounts?", 200 % text. Not checked
at all: iOS, screen readers.

Engine and data:

- categorise-1.4.0's effect on the real data is unmeasured until `category-diff` runs on
  it; the dictionary is curated by hand (640 entries) and will need additions.
- The HDFC alerts that only showed on the October statement (about Rs 15,700) were never
  stored as SMS; `sender-survey --contains HDFC` looks for a missing sender code.
- "Leave as is" flags, display names and answered times are not in the owner export; a
  restore from an owner export asks those questions again.
- The unticked "merged refund" check (D-064): settle it with a statement month that has a
  refund.
- A shopkeeper's QR named after a person is guessed People (D-119, D-133).

Platform and tooling:

- Render's docs do not say whether its proxy appends or replaces X-Forwarded-For; the
  sign-up limit uses the last hop (D-150). Behind a proxied custom domain, check the hops.
- The cross-origin check can fail on the first run after heavy work (a cold headless
  Edge); it logs and reloads once after 45 s.
- Not run: the backup script's branch that starts Docker Desktop; the scheduled task
  itself (agents never register it).
- Accepted risk: npm audit, 4 moderate findings, build-time only (glob and minimatch via
  vite-plugin-pwa and workbox-build, the newest releases). Never `npm audit fix --force`.
- GitHub cannot enforce required checks on a private repo on the free plan; Render
  deploying only after CI passes is the gate (D-050).
- The logo was not checked against a trademark register (D-083).
- `frontend/vite.config.ts` still names `docs/HANDOFF.md` for the live URLs in a comment;
  they are in [docs/operations.md](docs/operations.md), "Links" (a code comment, left for
  Phase 6 because the wrap-up changed no code).

Known limits: HDFC and SBI parsers (other banks generic), INR only; the card bill pair rule
waits for credit card SMS; the server sleeps when idle (about a minute to wake; the phone
copy covers it, D-112); Starlette's httpx warning is accepted (D-010).
