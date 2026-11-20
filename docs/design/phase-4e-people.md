# Phase 4E: people, names and joins

Status: built (4E, 20 Nov 2026). Decisions: D-096 (names and joins), D-097
(label limit), D-098 (HEAD /health).

## Today's model (before 4E)

- **Parties** (`parties`, owner data) are people or businesses the owner
  named: `label`, `kind` (person, business), `income_label`, a default
  `category`, and `source` (file, terminal, app). **Party texts**
  (`party_texts`) are counterparty texts (a name or a UPI ID) that belong to
  a party, one party per text.
- The engine never stores a party id on owner data. At every recompute it
  turns each party text into a merchant key (`normalise_merchant`) and
  matches transactions by key (D-065). A match gives the transaction the
  party: its kind and income flag decide credit roles (`CR_person_party`
  payback, `CR_income_party` income, else `CR_business` uncertain), its
  category is the default, and its label is the display name.
- **Senders** (To-do "Who sent you money?") group credits with a sender
  role by merchant key. Friend makes a person party (kind person), Family an
  income party, Ignore writes per-transaction `ignored` role decisions, and
  "Ask me again later" removes them (and a party the app made only to hold
  the answer).
- **People ledger** rows group person rows (People spending, paybacks) by
  `person_id`: `p_<party id>` when a party matches, else the sender id of the
  merchant key. So one friend under a name (debits) and a masked UPI ID
  (credits) is two rows, unless the owner file lists both texts on one
  party (D-079). The owner cannot do that on the phone.

## The model as built

- **A person is a party.** "Name this person" sets `parties.display_name`
  (new, 30 characters). The label stays the party's key, so an owner-file
  party keeps its file label and the app's name is shown over it. Clearing
  the name shows the label (file parties) or the engine's name (app
  parties) again. A party the app makes to hold a name or a join has the new
  kind **unsure**: no role answer yet, so the engine's own rules decide its
  credits as before. Nothing about money changes by naming.
- **"Same as…" moves texts.** Joining A into person B ends A's party-text
  rows (`ended_at`) and adds the same texts to B's party (source app). With
  no party yet, B gets one first (kind unsure, made from one of its
  transactions). Every text of A moves, so a person joined into another
  brings all their identifiers. A's emptied party stays as history. B keeps
  its name; an unnamed B takes the name it is shown by ("Same as Rohit V"
  makes the person "Rohit V"), else A's name.
- **"Separate"** ends one identifier's row in its person. The identifier
  is on its own again (no party): the engine's rules decide its rows, and
  per-transaction role decisions it had stay. The only identifier of a
  person cannot be separated. Separating then joining again adds a new row;
  ended rows are never deleted.
- **History.** `party_texts` gains `created_at` and `ended_at`; one text has
  at most one active row (a partial unique index replaces the old unique
  constraint). Recompute, the owner file and the export read active rows
  only. An ended row is never deleted or reopened.
- **Owner file rows.** A text from the owner file cannot be moved or
  separated in the app (409 "set in the owner file"); its file says where
  it belongs. The app may add texts to a file party and name it. The export
  writes texts from another source under `more_texts` with their source,
  and the name as `display_name`, so `owner-export` still works.

## Reparse

Owner rows hold texts and transaction ids only. Reparse keeps transaction
ids, and recompute matches texts by merchant key every time, so names and
joins survive reparse. A merchant engine change that would move a match
still stops recompute (`lost_matches`, D-066).

## Engine

The engine still never joins or names anyone; it reads parties as before.
Two small changes: a party of kind unsure gives no owner opinion on credit
roles (the merchant rules apply) and no person signal for the People
category, and senders group by party when a party matches. Grouping by party
means a joined person is one To-do card; its id is the id of the smallest
merchant key in the group, so a one-text party keeps its old id. Versions:
reconcile 1.4.0, categorise 1.1.0 (the first owner write after the deploy
rewrites every derived row; nothing else changes for existing data).

## Role conflicts

Each side's role comes from its sender: Friend, Family (income), Ignore, or
to confirm; a side with no credits has none. When both sides have a role and
they differ, the join needs `role` (one of the two; the phone asks first,
"Keep Friend" from the person joined into is the default button). Without
it the server answers 409 `role_conflict` and writes nothing. The chosen
role is applied to every credit of the joined person, as the To-do answer
would be. A side with no role takes the other side's.

## UI

- To-do sender card: "Name" and "Same as…" as quiet text buttons under
  Friend / Family / Ignore, and "See payments" on every sender and merchant
  card (Transactions filtered to that person, `?who=`; Back returns).
- Transaction sheet, a row with a person: Person with the name and its
  identifier; Rename, Same as…, Separate (when the person has more than one
  identifier).
- People ledger row: opens the person sheet (`?person=`): name, answer,
  identifiers (each with Separate), Rename, Same as…, Clear name, See
  payments, and "This month with <name>" for the month's view. To-do's Name
  and Same as… open the same sheet at that step (`&do=name|join`).
- A named row shows the name, with the identifier in small muted text under
  it, in To-do, the ledger, transaction rows and the sheet.
- Merchant cards: up to 4 one-tap category chips (the owner's most used
  categories by count of rows they set, then all rows), plus "More…".
- "Ask me again later" keeps a named or joined party (it only loses its
  answer); only a party the app made just to hold one answer is removed.
- The snapshot carries a `people` list (key, name, named, a transaction,
  answer, identifiers with a transaction each, from_file) for the picker
  and the sheet; no money in it.

## Offline and undo

Every new write goes through the outbox with an Idempotency-Key (D-091):
name, clear name, same as, separate. While waiting, the card or sheet shows
the new name or "Same as Rohit" with "Waiting to sync" and Undo (before it
is sent). Undo after sync is the opposite action: Clear name, Separate. A
join queued offline names its target by a transaction id, so it still
lands right after earlier queued actions. A conflict the phone could not see
(the roles changed elsewhere) comes back as "Couldn't save" with the reason.
