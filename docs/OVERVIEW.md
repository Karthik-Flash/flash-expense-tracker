# Overview

A one-page tour of Flash Expense Tracker for someone new to the project. It
links to the detailed documents instead of repeating them. State: Phase 4
done, Phase 5 next (21 Nov 2026; [retro/phase-4.md](retro/phase-4.md)).

## What it does and for whom

Flash is a personal expense tracker for one person in India: the owner.
Indian banks send an SMS for every card payment, UPI transfer and
ATM withdrawal. Flash reads those messages and turns them into a monthly
picture on the phone: how much was spent, how much friends paid back, what
it went on, and what still needs a decision. There is no manual entry and no
bank login. Today it reads HDFC and SBI messages in rupees (other banks
carefully, through a generic parser), and checks itself against the HDFC
statement.

## Where things live

| Place | What it holds or does | What it never sees |
| ----- | --------------------- | ------------------ |
| Phone | The app (an installable web app). Shows numbers; sends the owner's answers. | The database password; other people's data |
| Laptop | Code, tests, and `D:\FlashPrivate\` (SMS exports, the redaction key, private lists, backups). The owner runs imports and backups here. | Nothing leaves `D:\FlashPrivate\` except through the owner's own commands |
| Supabase Postgres | The real data: messages, transactions, owner answers, derived results | Only the server and the owner's import connect to it |
| Supabase Auth | The owner's login (email and password, sign-ups off) | Transactions |
| Render | The API (FastAPI). Checks the login token, reads and writes the database | SMS exports; the redaction key |
| Vercel | The app's static files | Any data: the browser calls the API directly |
| cron-job.org | Calls one tiny database function daily so Supabase does not pause (D-053) | Any table with data |

Git and AI tools never see real data: they work from fake fixtures and a
redacted sample (D-008, D-015, D-048). Setup and runbook:
[infra/README.md](../infra/README.md).

## From one SMS to a number on the phone

1. **Import.** The owner exports SMS from the phone to the laptop and runs
   `python -m app.cli import-sms`. Only known bank senders are kept; OTPs and
   promotions are dropped (D-026, D-049).
2. **Raw message.** Each message is stored once, with a dedupe key, so
   importing the same export twice adds nothing (D-003).
3. **Parse.** A bank template reads the amount, direction, account, time and
   counterparty. Amounts are never guessed; the parser version is stored
   with the result (D-004, D-041). [engine.md](engine.md)
4. **Transaction.** One row per money movement, in integer paise and UTC
   (D-001, D-002, D-046). [data-model.md](data-model.md)
5. **Merchant.** The counterparty text becomes a merchant key and a display
   name, marked person, business or unsure (D-057, D-058).
6. **Role.** Reconcile gives every transaction one role: spend, refund,
   payback, income, self-transfer, card bill, FD move, duplicate, ignored or
   uncertain. Duplicates are linked, never deleted (D-059 to D-062).
7. **Category.** One of a fixed list of 20 (D-073, D-074).
8. **Stored result.** `recompute` writes roles, links and categories to the
   derived tables in one go (D-066).
   [design/phase-3-backbone.md](design/phase-3-backbone.md)
9. **API.** `/api/v1` sums the stored results for each IST month and
   sends everything the app shows as one snapshot ([api.md](api.md),
   D-078, D-088).
10. **Screen.** The phone keeps the snapshot and opens from it at once,
    then refreshes; it shows the server's figures and never adds up
    money itself. Answers are saved on the phone first and sent with an
    Idempotency-Key, so a resend is applied once (D-089, D-091).

## Derived data and owner data

- **Derived data** (roles, links, categories) is a pure function of the
  transactions, the owner's answers and the engine versions. It can be
  deleted and rebuilt at any time with `recompute`.
- **Owner data** is what the owner said: "this sender is a friend", "this
  merchant is Groceries", labels, own accounts. The engine never writes it.
  Every row records where it came from: app, terminal or file (D-070).

Corrections survive a reparse because owner rows point at stable
transaction ids and at counterparty texts, not at derived rows (D-065).
Reparse keeps transaction ids; recompute then applies the same answers to
the new parse.

## The money rules

- **Spent**: spending debits, minus refunds. Self-transfers, FD moves and
  card bills for tracked cards are not spending (D-055, D-059).
- **Paid back**: money in from people that the owner confirmed. Only
  confirmed paybacks count (D-076).
- **To confirm**: money in that may be a payback; shown, never subtracted
  (D-061, D-076).
- **Net** = Spent minus Paid back: the headline (D-055).
- **Income**: pocket money, stipend, salary. Shown apart, never lowers Spent
  (D-055, D-061).
- **Not counted yet**: messages the app cannot count yet, such as foreign
  currency (D-035) and banks without a parser. They show as a count, never
  as a guess.
- A month is a calendar month in IST (D-002).

## Privacy

- Real SMS stays on the laptop and in Supabase. Shared samples are redacted,
  default-deny: every name and UPI ID is replaced unless it is a public
  brand (D-014, D-016, D-040).
- Logs and command output show counts, ids and versions only, never message
  text, names, amounts or account digits.
- The API answers only to the owner's login token; every query is scoped to
  the owner (D-078). It never returns raw message text.
- AI tools never read `.env` files, `D:\FlashPrivate\` or the database
  (D-019, D-048).

## Backup and restore

Supabase's free plan keeps no backups. The owner runs
`scripts\backup_db.ps1`, which dumps the app's tables with `pg_dump` (in
Docker) to `D:\FlashPrivate\backups\`. A restore goes into an empty database
first, then the app is pointed at it (D-084; steps in
[NOTES.md](../NOTES.md), "Back up and restore").

## Design rules in brief

Calm, like a bank statement: system font, tabular figures, one muted teal
accent, light and dark themes, no decoration that carries no information.
Every category has a muted colour and an icon tile; Home offers a list and a
ring chart. Everything on screen is in the URL, so Back and reload behave.
Full rules: [ui-spec.md](ui-spec.md).

## Known limits (start of Phase 5)

- Some HDFC UPI alerts use a template the parser does not know yet (about Rs
  15,700 of October spending showed only on the statement); the fix waits for
  the owner's approved `redact-sample --family HDFC --unparsed` sample.
  Meanwhile `statement-import` can add those rows from the statement.
- HDFC and SBI have their own parsers; ICICI, Axis, Kotak, YES and India Post
  use the careful generic parser; foreign-currency messages are not counted.
- Data comes from SMS backups the owner imports; live SMS on the phone is
  Phase 5.
- The server sleeps when idle and can take about a minute to wake; the phone
  copy shows meanwhile (there is no warm job, D-112).
- Owner answers made offline wait on the phone ("Saved on phone · syncing")
  and are sent when the server can be reached; totals move only after that.
- Open items in full: [NOTES.md](../NOTES.md#open-items).
