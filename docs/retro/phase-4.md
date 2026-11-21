# Phase 4 retro (19 to 21 Nov 2026)

Phase 4 turned the working web app of Phase 3 into an installable,
offline-first app the owner can trust with money, and closed the gaps a real
bank statement showed. Decisions D-085 to D-121.

## What shipped

| Step | What |
| --- | --- |
| 4C | Installable PWA: manifest and icons, an update bar instead of silent updates, an app-shell-only service worker, the build id on Home (D-085 to D-087). |
| 4B | Offline-first: one snapshot of every figure the server worked out, kept on the phone with "Updated X ago" (4B-1); every owner action through an outbox with an Idempotency-Key (4B-2); an offline launch that never shows a blank screen (4B-3) (D-088 to D-095). |
| 4E | People: name a person, "Same as…" and Separate, "See payments", one-tap category chips, HEAD /health (D-096 to D-098). |
| 4F | Other banks: a careful generic parser, payback-audit for silent paybacks, refresh after a deploy, bank survey and redacted samples (4F-A); the CORS fix, an outbox that cannot get stuck, writes before the recompute, a dedicated SBI parser (4F-B) (D-099 to D-108). |
| 4H | History without AI attribution lines, actions from the person sheet, payback-audit by any answer on record with `--restore`, the API warm job retired, a polish pass with written UI tokens (D-109 to D-113). |
| 4A | The HDFC statement reader and `statement-check`, own-account transfers by shared reference or the owner's answer, statement names (D-114 to D-116). |
| 4Z | Statement reader 1.1.0, more statement causes and `statement-import`, It's me and Investments with suggestions, categories guessed from names, the git backup deleted after a verified push (D-117 to D-121). |

## What broke, and why

- **Every tap from the phone was blocked (4B-2 to 4F-B).** The outbox sent an
  `Idempotency-Key` header the API did not list in `allow_headers`; the
  browser's preflight got 400 and the write was never sent. Tests ran the app
  and the API on one origin, so nothing caught it until the owner's tap
  stayed "waiting" for a day.
- **A Postgres-only CI failure (4F-A).** A test expected SQLite's error class;
  CI runs Postgres too and failed after the push. Local runs had used SQLite
  only.
- **The Render warm pings never warmed anything.** A sleeping free service
  answered cron-job.org's pings with 503 and did not wake; the job spent free
  hours for nothing until it was retired (D-112).
- **A manual deploy while CI was red.** A deploy went out by hand while the
  pipeline was failing, so code that CI had not passed reached the live API.
- **"All from" made silent paybacks.** Before 4E, a default category on a
  person-like text created a party of kind person, which counted that
  person's credits as owner-confirmed paybacks and lowered Net without any
  answer (D-099). The first repair also flagged real Friend answers; it was
  corrected twice (4F-B, D-111) and can be undone (`--restore`).
- **The statement showed what SMS missed.** October had 17 rows only the
  statement holds: about Rs 15,708 of real spending (UPI alerts in a template
  the HDFC parser does not know, and one foreign card charge), plus an FD, an
  own-account transfer and small credits that are not spending. September's
  file did not read at all: a card reversal row had a negative debit and a
  credit on one line.

## The rules that came out of them

1. **One shared header list, and a cross-origin check in the routine.** The
   API allows exactly the headers and methods the app sends (`headers.ts` and
   `main.py`, compared by a test), and `node scripts/cross-origin-check.mjs`
   runs a real browser against a second origin before every report (D-104).
2. **Postgres 17 locally before reporting.** The backend suite runs on SQLite
   and on a throwaway Postgres 17 container; the migration goes up, checks,
   down and up again.
3. **No warm pings; the phone copy covers a cold start.** Only the Supabase
   heartbeat stays (D-112).
4. **Deploys follow green CI.** Render waits for CI; nothing is deployed by
   hand while CI is red, and the owner pushes only after the planner's
   review.
5. **A guess never lowers Net.** Anything that takes money out of Spent or
   counts a credit as Paid back needs the owner's answer on record; the engine
   only suggests (D-076, D-111, D-115, D-117, D-120).
6. **Reconcile against the bank, not only the SMS.** The statement is the
   check on the parsers: counts and rupee sums are safe to paste, rows are
   private, and a missing template is added only from an approved redacted
   sample, never guessed (D-114, D-120).
7. **Every write through the outbox, safe to send twice.** The phone never
   loses a tap, and the server applies each action once (D-091, D-105).
8. **Owner data and derived data never mix; nothing is deleted.** Repairs are
   owner commands with a dry run first and a way back.
