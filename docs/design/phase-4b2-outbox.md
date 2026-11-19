# Phase 4B-2: the outbox for owner actions

Every tap that changes owner data goes through one path, online or offline:
it is saved on the phone first, shown on its item as "Waiting to sync", sent
in order with an `Idempotency-Key`, applied on the server exactly once, and
reflected in totals only after the server confirms and a fresh snapshot
arrives (D-091 to D-094).

## The writes (all six)

| Screen and button | Request | Owner tables | Derived refresh |
| ----------------- | ------- | ------------ | --------------- |
| To-do sender: Friend, Family (Save), Ignore | `PUT /senders/{id}` `{"answer", "label"?}` | parties, party_texts or owner_roles | recompute |
| To-do Answered: "Ask me again later" | `DELETE /senders/{id}` | owner_roles, parties, party_texts | recompute |
| Sheet: "Just this one" / "All from X"; To-do "Pick a category" | `PUT /transactions/{id}/category` `{"category", "scope"}` | owner_categories or parties (+ party_texts) | recompute |
| Labels: Create | `POST /labels` `{"name"}` | labels | none |
| Sheet: a label | `PUT /transactions/{id}/label` `{"label_id"}` | txn_labels | recompute |
| Sheet: new label, Add | `PUT /transactions/{id}/label` `{"new_label"}` (new form) | labels, txn_labels | recompute |
| Sheet: No label | `DELETE /transactions/{id}/label` | txn_labels | recompute |

The sheet's "make a label and attach it" was two calls, the second needing the
id the first returned. Offline that id does not exist yet, so the label route
also takes `{"new_label": name}`: make the label (409 if the name exists) and
attach it, in one transaction. `{"label_id"}` works as before.

## Server: idempotency (D-091, D-092)

- Header `Idempotency-Key: <uuid>` on any of the six. Without it nothing
  changes (laptop scripts, tests).
- Table `client_ops`, primary key **(owner_id, op_id)**: the key is scoped to
  the owner, so another owner's key never matches (safer than a primary key on
  op_id alone, which would let one owner's key block another's). It also keeps
  `request_hash` (SHA-256 of method, path and canonical body) to spot reuse.
- First time: under the owner's lock, insert the row, run the write and its
  recompute, store the status and response, and commit once. `recompute()`
  commits itself, so it takes a `before_commit` hook that writes the row's
  result inside the same transaction. A crash leaves both or neither.
- Same key, completed: the stored status and body; nothing is written.
- Same key while the first is still running in this process: `409
  {"detail": "in_progress"}`. (In one transaction an in-progress row is never
  visible to another connection; the owner lock and the primary key make a
  second process wait, then replay the stored answer.)
- Same key, different method, path or body: `422 {"detail":
  "idempotency_key_reused"}`.
- 2xx and 4xx (404, 409, 422 from the write) are final and stored. A 5xx
  rolls back the whole transaction, row included, so a retry runs fresh.
  A 4xx is stored after the write is rolled back, in its own transaction.
- Rows are never deleted: one small row per tap.

## Recompute (D-094)

Each write recomputes the owner's derived rows: about 40 ms on SQLite with 704
FAKE transactions, more over the Supabase pooler on a cold Render. Draining 20
taps would run 20 full recomputes. So:

- `X-Defer-Recompute: 1` (honoured only with an `Idempotency-Key`): the write
  commits without a recompute and marks its row `recompute_pending`. The
  response says `"recompute": {"status": "deferred"}`.
- The phone sends it on every op of a drain except the last pending one.
- Every read route and the snapshot first recompute when the owner has a
  pending row, then clear the marks in the same commit. So derived data is
  never served out of step with owner data. A recompute stopped by an engine
  change (D-065) keeps the marks; the read shows the stale flag as today.
- Any recompute through a write clears the marks too.

## Phone: the outbox (D-091, D-093)

- IndexedDB `flash` version 2 adds store `outbox` (key `seq`, auto). The v1
  stores and their rows stay. `src/data/local.ts` still owns IndexedDB.
- Entry: `seq`, `op_id`, `created_at`, `kind` ("Category: Food & Drinks"),
  `item` (the name it is about), `method`, `path`, `body`, `targets` (txn ids,
  sender ids, merchant names, label names), `choice` (what to show), `state`,
  `attempts`, `last_error`, `key_reused`, `confirmed_at`.
- Lifecycle: `pending` -> `sending` -> `confirmed` -> removed once a snapshot
  **asked for after** the confirmation is applied (200 or 304); or `failed`
  (kept until Retry or Discard). An op left in `sending` by a closed app goes
  back to `pending`; its key makes the resend safe.
- As built, "after" is a request number, not `fetched_at > confirmed_at`: a
  snapshot asked for just before the confirmation can land after it, and
  clocks tie within a millisecond, so either would flip an item back to the
  old value. The store numbers its snapshot requests; a confirmed op records
  the number at confirmation; a confirmed op loaded from storage counts as
  confirmed before every request of the new session.
- Drain: first in, first out, one at a time, single flight. Triggers: a new
  tap, the `online` event (also resets the backoff), back in the foreground,
  after a snapshot refresh, and every 30 s while anything waits and the app
  is visible (the 30 s tick respects the backoff).

| Outcome | Op | Drain |
| ------- | -- | ----- |
| 2xx | confirmed | next op |
| network error, 90 s timeout, 5xx, 409 `in_progress` | stays pending | stops; retry after 5 s, 15 s, 60 s, then every 5 min |
| 401 | stays pending | one token refresh and one more try; still 401: "Sign in to sync", stops |
| other 4xx (404, 409, 422) | failed, server's words | next op |

- After a drain that confirmed an op: one snapshot refresh.
- Undo: only a `pending` op that is not being sent; it is removed.
- Retry of a failed op keeps its op_id, except after `422
  idempotency_key_reused`, which gets a new one.

## Screens

- The item shows the owner's choice with muted "Waiting to sync" (pending or
  sending), nothing extra once confirmed, "Couldn't save" when failed. Totals,
  ring, percentages, ledger sums and comparisons never change (D-088).
- To-do: items with a decision in the outbox leave "Who sent you money?" and
  "Pick a category" and the tab badge, and show in a "Waiting to sync" section
  with Undo.
- Freshness line: "Updated 5 min ago · 3 waiting to sync", and "1 couldn't
  save" as a link to a sheet (`?unsaved`) with Retry and Discard. "Sign in to
  sync" after a lasting 401.
- Speed sheet (`?speed`): a Sync block.

## Sign-out and 401

- Sign out with unsynced ops (pending, sending or failed): a confirm sheet,
  "<N> changes haven't synced yet. If you sign out now they will be lost.",
  "Stay signed in" first, then "Sign out anyway". Sign out wipes the database.
- A 401 never drops ops. It used to sign out and wipe. Now a lost session (a
  401 from a read, or the library losing the session) goes to the login
  screen and **keeps** the phone copy and the outbox on the device. The same
  login picks them up again; a different login wipes them first (D-089).
  Safer reading of "never drop ops on 401"; reported to the planner.
- An update reload waits up to 10 s for an op in `sending`.
