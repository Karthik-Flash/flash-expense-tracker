# Data API (`/api/v1`)

FastAPI, `backend/app/api/v1.py`. Every route needs a login (D-078). Money is
an integer number of paise. Times are UTC ISO strings ending in `Z`; the
client shows IST. No response holds raw message text or a reference.

## Login

Send the Supabase Auth access token: `Authorization: Bearer <token>`.

- Accepted: ES256 tokens signed by a key in
  `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`, with a valid `exp`, issuer
  `<SUPABASE_URL>/auth/v1` and audience `authenticated`. Keys are cached and
  fetched again (at most once a minute) when a token names an unknown key id.
- Since 5C (D-129) the token's `sub` is looked up in `app_users` (owner_id,
  role admin or member). `AUTH_USERS` (`"<sub>:<owner_id>"`, comma-separated)
  is the seed and a fallback: an entry with no row yet becomes an admin row on
  its first request. It may be empty once the row exists; malformed is 503.

| Status | When |
| ------ | ---- |
| 401 | No token, not Bearer, malformed, not ES256, unknown key id, bad signature, expired, wrong issuer or audience |
| 403 | A valid token whose user is not in `AUTH_USERS` |
| 503 | `SUPABASE_URL` or `AUTH_USERS` unset or malformed, or the keys cannot be fetched |

Every query and every write is scoped to the token's owner. Another
owner's transaction, label or sender is "404 not found".

## Routes

| Method | Path | What |
| ------ | ---- | ---- |
| GET | `/api/v1/sync/snapshot` | Everything the app shows, in one document (below). ETag; 304 on If-None-Match |
| GET | `/api/v1/summary?month=YYYY-MM` | The month in IST: Spent, Paid back (owner-confirmed only), To confirm, Net, Income, Spent by category, counts, stale flag, and `previous` (below) |
| GET | `/api/v1/transactions?month=&category=&label=&cursor=&limit=` | Newest first, `limit` 1 to 200 (default 50); `next_cursor` for the next page |
| GET | `/api/v1/transactions/{id}` | One transaction, the same item as in the list |
| GET | `/api/v1/categories` | The fixed list: `slug`, `name` |
| GET | `/api/v1/labels` | Every label with its totals across all dates: `id`, `name`, `transactions`, `spent_paise`, `paid_back_paise`, `to_confirm_paise`, `net_paise` |
| POST | `/api/v1/labels` | `{"name"}`: 201 with `{"id", "name"}`; 409 when the owner has that name in any case; 422 when the name breaks the rules (below) |
| GET | `/api/v1/labels/{id}` | The label view across all dates: the totals above and Spent by category |
| GET | `/api/v1/senders?status=to_confirm\|confirmed\|ignored\|all` | Senders of paybacks, uncertain credits, income and ignored credits, newest credit first, then the higher `txn_id` (5B-1) |
| PUT | `/api/v1/senders/{id}` | `{"answer": "friend"}`, `{"answer": "income", "label": "..."}` or `{"answer": "ignore"}` |
| DELETE | `/api/v1/senders/{id}` | Forget the answer: the sender is to confirm again |
| PUT | `/api/v1/transactions/{id}/category` | `{"category": slug, "scope": "merchant" \| "transaction"}` |
| PUT | `/api/v1/transactions/{id}/label` | `{"label_id"}`, or `{"new_label": name}` to attach the label of that name, made in the same write when the owner has none (any case, spaces tidied; D-110: a label made offline can be picked again before it syncs): at most one label per transaction |
| DELETE | `/api/v1/transactions/{id}/label` | Remove the label (also when there is none) |
| PUT | `/api/v1/people/{txn}/name` | `{"name"}`: name the person of transaction `txn` (D-096) |
| DELETE | `/api/v1/people/{txn}/name` | Clear that name (404 when there is none) |
| PUT | `/api/v1/people/{txn}/join` | `{"into": txn, "role"?}`: "Same as": the person of `txn` joins the person of `into` |
| DELETE | `/api/v1/people/{txn}/join` | "Separate": the identifier of `txn` leaves its person |
| PUT | `/api/v1/transactions/{id}/check` | "Looks right" on a row the generic parser read (D-101): clears `check`, no recompute (422 on any other row) |
| PUT | `/api/v1/transactions/{id}/ignore` | "Not a payment" (D-103): owner role `ignored`, in no total |
| DELETE | `/api/v1/transactions/{id}/ignore` | "Count it again": removes that role (no change when there is none; 409 when the owner set another role) |
| PUT | `/api/v1/transfers/{debit}/{credit}` | `{"verdict": "same" \| "different"}`: "Moved between your accounts?" (D-115). Same: both legs `self_transfer`; different: the pair is gone for good. 404 for a pair the engine never proposed; 409 when a leg is already "same" with another |
| PUT | `/api/v1/profile/names` | `{"names": [...]}`: "Your name as banks show it" (D-117), the whole list (at most 6, 2 to 60 characters each); no recompute |
| PUT | `/api/v1/profile/settings` | `{"count_investments_in_spent": true \| false}` (5B-1, D-136; JSON true or false only): the owner's setting, through the outbox; answers `{"settings": {...}}`, no recompute (totals read it when they are worked out) |
| PUT | `/api/v1/people/{txn}/kind` | `{"kind": "self" \| "investment"}`: It's me or Investments for the person of `txn` (D-117, D-118); every payment of the party, both ways |
| DELETE | `/api/v1/people/{txn}/kind` | Undo: the party gets back the kind it had (404 when it is neither) |
| PUT | `/api/v1/people/{txn}/suggestion` | `{"kind"}`: No to "Is this you?" / "Is this an investment?": not asked again |
| POST | `/api/v1/devices` | `{"device_id": uuid, "name"}` (5A, D-122): registers this phone; 201 with `{"device", "token"}`. The token is shown only here. Not an outbox write |
| GET | `/api/v1/devices` | `{"devices": [...]}`: every phone of the owner (never a token or hash) |
| DELETE | `/api/v1/devices/{device_id}` | Revoke: its token stops at once (an outbox write; revoking twice is the same answer; 404 for another owner's) |
| POST | `/api/v1/ingest/sms` | The device token only (below): a batch of bank SMS from the phone |
| POST | `/api/v1/signup` | No login (5C, D-128): `{"email", "password", "code"}`; 201 `{"ok": true}`, then the app signs in as usual |
| POST | `/api/v1/invites` | The admin: 201 `{"invite", "code"}`; the code is shown only here. Not an outbox write |
| GET | `/api/v1/invites` | The admin: `{"invites": [...]}` (`id`, `created_utc`, `expires_utc`, `used_utc`, `revoked_utc`; never a code) |
| DELETE | `/api/v1/invites/{invite_id}` | The admin: revoke an unused invite (outbox write); 409 for a used one |
| GET | `/api/v1/members` | The admin: everyone who uses Flash (`email`, `role`, `joined_utc`, `last_seen_utc`, `transactions`, `phones`): counts only |
| POST | `/api/v1/account/delete` | `{"confirm": "DELETE"}` and a fresh sign-in (D-131): every row of the account, then the login. 409 `fresh_login_required` or `admin_cannot_delete` |
| HEAD | `/health` | 200, no body, no database (D-098): the warm job's fallback |

**Writes** are saved with source `app` and are idempotent. Since 4F-B
(D-106) a write commits its owner data, its stored answer and a recompute
mark in one transaction, under the owner's lock, and answers at once:
`{"result": {...}, "recompute": {"status": "deferred", "run": null}}`. The
next read recomputes. A write first brings the earlier writes' derived rows
up to date (owner actions read them); if that fails, the write is still
saved. Errors: 404 (not this owner's, or no such id), 422 (validation), 409
(a conflict the owner decides, or a label name the owner already has).

**CORS (D-104)**: the app is on another origin, so the browser sends a
preflight first. The API allows exactly the headers and methods in
`frontend/src/api/headers.ts` (Authorization, Accept, Content-Type,
If-None-Match, Idempotency-Key, X-Defer-Recompute; GET, PUT, POST, DELETE)
from the origins in `CORS_ORIGINS`, and exposes `ETag`. Every request is
logged as one line: method, route template, status, duration. Only three
kinds of origin are ever allowed, whatever `CORS_ORIGINS` holds: the Vercel
app, the Android app's WebView `https://localhost` (5A, D-125; exactly, no
port) and local dev servers. The phone's native upload sends no Origin: it is
not subject to CORS.

### Users, invites and the account (5C, D-128 to D-131)

- **Sign-up** checks, in order: rate limits (10 per IP per 15 minutes, 5 per
  code per hour, 60 overall per hour: 429 "Too many tries. Wait a few minutes
  and try again."), an email of the usual shape (422), the code (case, spaces
  and dashes ignored; unknown, used, expired or revoked all answer 400 "This
  invite code doesn't work. Check it, or ask for a new one."), then the
  Supabase login (`SUPABASE_SECRET_KEY` on the `apikey` header, `POST
  /auth/v1/admin/users`, `email_confirm: true`). A refused login (an email
  that exists, a password Supabase rejects) is 400 "Could not create the
  account. Check the details, or ask for a new invite." and the code is not
  spent; Supabase down or the key missing is 503. The new member gets a new
  owner_id; a failed save deletes the new login again.
- **Admin routes** (invites, members) answer 403 to a member.
- **Delete my account**: the token's `amr` must hold a `password` entry from
  the last 10 minutes (the app asks for the password again); the admin gets
  409 `admin_cannot_delete`. Answer `{"deleted": <rows>, "login_deleted":
  bool}`; `false` means the login waits for `python -m app.cli auth-cleanup`.
- A device token stops (401 `device_revoked`) once its owner has no
  `app_users` row (nor an `AUTH_USERS` entry).
- Snapshot: `account` (`role`, `email`); for the admin also `admin`
  (`invites`, `members` as above).

### Devices and the SMS ingest (5A, D-122, D-123)

- **Device token**: `POST /api/v1/devices` with the login token makes 256
  random bits (`secrets.token_urlsafe(32)`) and stores only their SHA-256
  (`devices.token_hash`). The same `device_id` again replaces the token (the
  old one stops), so a lost answer is repaired by asking again. The name is
  tidied (spaces) and cut to 60 characters; an empty one is 422.
- The device token is **ingest-only**: it is not a login token, so every
  other route answers 401; `POST /api/v1/ingest/sms` accepts nothing else
  (a login token there is 401). `Authorization: Bearer <device token>`.
  401 `invalid device token` for an unknown one, 401 `device_revoked` for a
  revoked phone (the phone stops and says so).
- **Ingest** body `{"messages": [{"sender", "body", "received_at_utc",
  "device_msg_id"}]}`: 1 to 500 messages; `sender` at most 64 characters;
  `body` 1 to 2,048 bytes (UTF-8); `received_at_utc` an ISO time with a zone
  (the inbox row's `date`, to the millisecond: it is part of the content
  hash); `device_msg_id` 1 to 64 characters (the inbox `_id`, echoed back).
  Anything else is 422 and nothing is stored.
- Per message, in order: a sender whose core is not a bank of
  `app/engine/shared/bank_senders.json` (PhonePe is registered but not a
  bank) is `refused_not_bank`; a promotional sender (TRAI suffix P) or an OTP
  is `refused_filtered`; else the message goes through `store.ingest()` as
  import-sms stores it (source `live_sms`): `stored` (a new raw message,
  parsed, a transaction when it is money) or `duplicate` (the same content
  hash is there, from the laptop or an earlier upload). Refused messages are
  never stored. Answer: `{"results": [{"device_msg_id", "status"}],
  "counts": {"stored", "duplicate", "refused_not_bank",
  "refused_filtered"}}`. A new message sets the recompute mark (D-106): the
  next read recomputes. One `import_batches` row (source `live_sms`) per
  upload; `devices.last_seen_at` is set.
- Bodies, senders and tokens are never logged; the request log has the route
  template only.

- `scope: merchant` sets the default on the merchant's party (made from the
  transaction's text if there is none, kind `unsure` since 4E, so a category
  never answers who someone is): every past and future payment to it.
  This transaction's own one-off, if any, is removed. A transaction with no
  merchant text (an ATM withdrawal) answers 422; use `scope: transaction`.
- `friend` makes the sender's party a person (a payback, confirmed);
  `income` makes it an income source with that label; `ignore` sets role
  `ignored` on its current credits. A sender with no text gets role
  decisions instead of a party. An ignored sender can be answered again.
- `DELETE /senders/{id}` removes the sender's role decisions. A party the app
  made only for the answer is removed too. Any other party stays (see
  People), so its credits are to confirm again.
- Senders group by person (D-096): a joined person is one sender; its id is
  the id of its smallest merchant key, so a one-text party keeps its id.
  Each sender also has `person_id` and `txn_id` (a transaction to name or
  join it by).
- **Names** (a label, an income label, a person's name): trimmed, inner runs
  of spaces joined into one, then 1 to 30 characters (D-097: the database
  holds the same limit for labels). The client applies the same rules
  (`frontend/src/screens/derive.ts`).

### People (D-096)

A person is an owner party; every route names it by one of its
transactions (`txn`), so a queue of taps made offline lands right.

- **Name**: sets the party's `display_name`, making a party (kind `unsure`:
  no answer, the engine's rules keep deciding) from the transaction's text
  when there is none. The name shows everywhere the person appears; each
  transaction item then carries its `identifier` (below). Naming changes no
  role, category or amount.
- **Same as**: every active text of the person of `txn` moves to the person
  of `into` (the old rows end, the new ones are source `app`). The person
  keeps its name, or the name it is shown by. When both sides have an answer
  (Friend, Family, Ignore, or to confirm) and they differ, `role` must be one
  of the two (`friend`, `income`, `ignore`, `none`): without it 409 and
  nothing is written; another value 422. The chosen answer is applied to
  every credit of the person, as the To-do answer would be. 409 when they
  are already one person.
- **Separate**: ends the row of the identifier of `txn`; it is on its own
  again (engine rules; its per-transaction role decisions stay). 409 for a
  person's only identifier; 404 when it is not part of a person.
- A text from the owner file is moved or separated only in the file: 409
  "this identifier is set in the owner file". The app may name a file party
  and join other texts to it.
- `DELETE /senders/{id}` keeps a party that is named or joined (and one with
  a category or from the owner file): it loses its answer (kind `unsure`,
  file parties `business`), so its credits are to confirm again.

### Idempotency-Key (D-091, D-092)

The app sends every write with `Idempotency-Key: <uuid>` (the phone outbox's
op id). Without the header a write behaves exactly as above.

| Case | Answer | Written |
| ---- | ------ | ------- |
| A new key | the write's answer (2xx, or a 4xx such as 404, 409, 422) | the write, its recompute and the stored answer, in one transaction |
| The same key again, same request | the stored status and body | nothing |
| The same key while the first is still running | 409 `{"detail": "in_progress"}` | nothing |
| The same key with another method, path or body | 422 `{"detail": "idempotency_key_reused"}` | nothing |
| A key that is not a UUID | 422 | nothing |
| A 5xx | 500 | nothing, so a retry runs fresh |

A key belongs to its owner (table `client_ops`, key `(owner_id, op_id)`):
another owner's key never matches. A 2xx or 4xx answer is final and is kept.

### Deferred recompute (D-094)

`X-Defer-Recompute: 1`, honoured only with an `Idempotency-Key`: the write
commits without its recompute and answers `"recompute": {"status":
"deferred", "run": null}`. The phone sends it on every queued write but the
last. Every read route and the snapshot first run the recompute such a write
left, so they never serve derived data out of step with owner data. A
recompute stopped by an engine change leaves the mark; the read shows
`stale` as before.

**Recompute marks (D-106).** A write marks the owner; the first read
recomputes and clears the mark. A recompute that fails keeps the mark with
the error type; reads serve the stored rows (`stale: true`) and try again
after 5 minutes.

**New engine versions (D-102).** When the last done run was made by other
engine versions than the running ones (after a deploy), the first read
recomputes first (trigger `read`) and serves fresh totals; later reads do
nothing extra. If that recompute fails, the read serves the stored rows
with `stale: true` ("Totals are being updated") and the error type is
logged; the process does not retry on every read.

## Snapshot (D-088)

`GET /api/v1/sync/snapshot`, the app's only read. Send `Accept:
application/json` (a waking Render answers browser-like requests with an
HTML page) and, after the first answer, `If-None-Match: <ETag>`.

| Field | What |
| ----- | ---- |
| `schema_version` | `1`. The app discards a copy of another version |
| `generated_at` | UTC time of this answer (not part of the ETag) |
| `owner_id`, `engine_versions` | Whose data, made with which engines |
| `months[]` | Every IST month with transactions, oldest first: `month`; `summary` (exactly the `/summary` answer); `changes` (`spent_paise` and per category slug, against `summary.previous`); `chart` (`total_paise` and at most 6 slices plus one `slug: null` "Other (n)"); `merchants` (per category slug, `name`, `total_paise`, `count`, biggest first); `people` (the People ledger: `key`, `name`, `sent_paise`, `got_back_paise`, `to_confirm_paise`, `net_paise`) |
| `transactions[]` | Every transaction item (below), newest first |
| `todo` | `senders` (to confirm), `answered` (confirmed or ignored), `merchants` (uncategorised spending by name: `name`, `total_paise`, `count`, `txn_id`, `last_time_utc`), `unnamed`, `transfers` (4A, D-115: self-transfer candidates no owner answered, newest first: `debit`, `credit`, `amount_paise`, `from_bank`, `to_bank`, `debit_time_utc`, `credit_time_utc`), `suggestions` (4Z: `kind` self or investment, `key`, `txn_id`, `name`, `count`) |
| `people[]` | 4E: everyone the owner can name or join, by name: `key` (as `person_id`), `name`, `named`, `txn_id`, `role` (`friend`, `income`, `ignore`, `none`, or null with no credits), `identifiers` (newest first: `name` as the bank wrote it, `txn_id`, `from_file`). No money |
| `labels[]` | `/labels/{id}` for every label, by name |
| `categories[]` | `/categories` |

- **ETag**: `"<sha256>"` of the canonical JSON (sorted keys, no spaces)
  without `generated_at`. The same data always gives the same ETag. A
  matching `If-None-Match` answers 304 with no body.
- **Gzip**: every answer of 1,000 bytes or more is gzipped when the client
  accepts it. FAKE data, 704 transactions over 11 months: 230,686 bytes
  raw, 11,918 gzipped (real data compresses less).
- CORS allows the `If-None-Match` header and exposes `ETag`.
- The People ledger keys a person by `person_id`, else `name:<shown name>`;
  a name the bank did not give is "Bank transfer", "Bank transfer in" or
  "Cash withdrawal", as in the app.

## Transaction item (fake values)

```json
{
  "id": 1042,
  "time_utc": "2026-01-09T06:00:00Z",
  "amount_paise": 10000000,
  "direction": "debit",
  "display_name": "Person_901",
  "identifier": null,
  "person_id": "s_3f9a0c1d2e4b5a6c7d8e",
  "role": "spend",
  "role_basis": "engine",
  "category": "people",
  "category_name": "People",
  "category_basis": "engine",
  "label": null,
  "generic": false,
  "check": false
}
```

- `role_basis`: `owner` when the owner decided the role (a confirmed payback,
  income, ignored), else `engine`. A payback with basis `engine` is to confirm.
- `person_id`: who the money went to or came from. `p_<n>` when the text
  matches an owner party, else the sender id of the text (`s_...`, the same
  id as in `/senders`), else `null` (no counterparty text, such as an ATM
  withdrawal). One person seen under a name and a UPI ID gets one id once the
  owner joins them ("Same as", D-096) or lists both texts on one party in
  the owner file.
- `identifier`: on a named person's row, the identifier it came from as the
  bank wrote it (a name or a UPI ID, maybe masked), when it differs from
  `display_name`; else `null`.
- `generic`: read by the generic parser (another bank, D-101). `check`: a
  generic row the owner has not checked yet and that is not ignored or a
  duplicate; the app lists it under "Check these payments".

A sender also carries `income_label`: the label of a confirmed income
sender, else `null`. `status` is `to_confirm`, `confirmed` or `ignored`
(every credit ignored). A new credit from an ignored sender makes it to
confirm again.

## Summary response (fake values)

```json
{
  "month": "2026-01",
  "spent_paise": 3275275,
  "paid_back_paise": 0,
  "to_confirm": {"amount_paise": 25055500, "senders": 4},
  "net_paise": 3275275,
  "income_paise": 0,
  "categories": [
    {"slug": "food_drinks", "name": "Food & Drinks", "amount_paise": 99900},
    {"slug": "cash", "name": "Cash", "amount_paise": 1872100},
    {"slug": "emi_loans", "name": "EMI & Loans", "amount_paise": 555500},
    {"slug": "uncategorised", "name": "Uncategorised", "amount_paise": 747775}
  ],
  "counts": {"uncategorised_spend": 17, "senders_to_confirm": 4, "not_counted_yet": 3},
  "stale": false,
  "last_recompute_utc": "2026-11-16T10:00:00.000000Z"
}
```

`categories` always adds up to `spent_paise`. `stale` is true when no
recompute has run, the engine versions changed, or stored rows differ from
a fresh derive; the owner runs `recompute` (D-066).

`previous` is the month before, for "compared with last month", under the
same rules as Spent:

```json
"previous": {"month": "2025-12", "whole": false, "spent_paise": 2101900, "categories": [...]}
```

When `month` is the current IST month, `previous` runs from the start of
the month before up to the same IST day of the month, that day included
(all of it when the month before is shorter); `whole` is false. For any
other month it is the whole month before; `whole` is true.

Since 4Z the snapshot also has `profile` (`{"names": [...]}`, D-117); a person
in `people` has `kind` (self, investment or null); a transaction item has
`statement` (read from the bank statement, D-120) and `category_guessed`
(D-119). Role `investment` is in no total (D-118).

Since 5A the snapshot also has `devices` (the owner's phones: `device_id`,
`name`, `created_utc`, `last_seen_utc`, `revoked_utc`) and `sms`
(`{"newest_utc"}`: when the newest SMS the server has arrived, from a laptop
import or the phone; the Bank SMS sheet starts a first scan a day before it).

## 5B-1 additions (D-133 to D-138)

- **To-do order.** Every To-do list in the snapshot (`todo.senders`,
  `todo.answered`, `todo.merchants`, `todo.suggestions`, `todo.transfers`) and
  `GET /senders` are newest first: the newest transaction's time, then the
  higher transaction id (`txn_id`, or `debit` for a transfer). Suggestions gain
  `last_time_utc`. The app sorts again with the same rule, so an older phone
  copy shows the same order.
- **Summary** (`/summary` and every snapshot month) gains `invested_paise`
  (debits of role `investment`: investments the owner confirmed),
  `invested_to_confirm_paise` (payments with an open "Is this an investment?"
  question; they are in Spent) and `investments_in_spent` (the setting). With
  the setting on, `spent_paise`, `net_paise`, the categories (Investments),
  `previous`, the ring, "Paid to" and every label's totals count confirmed
  investment debits as Spent; off (the default) they are outside Spent.
- **Transaction item** gains `investment`: `"confirmed"` (role investment),
  `"suggested"` (an open investment question) or `null`.
- **Snapshot** gains `paybacks`: `[{"debit", "credit", "status"}]`, which
  payment each payback pays back (D-134), `linked` or `candidate`; display
  only. `profile` gains `settings`: `{"count_investments_in_spent": false}`.
## 5B-2 additions (D-139 to D-144)

- **Ingest** (`POST /api/v1/ingest/sms`, device token): each message may carry `origin`
  (`"inbox"`, the default, or `"live"`). The answer adds `new_transactions`: one item per
  transaction this request created, `{"device_msg_id", "id", "direction", "amount_paise",
  "display_name", "category", "category_name", "role", "paid_back_question"}`; empty for
  duplicates, twins, notices and refused messages. Older phones ignore it.
- **Snapshot ETag**: `"v-<sha256>"` from the owner's data version (D-140), the IST day, the
  engine versions and the login's account block; a 304 builds nothing. Same data, same ETag;
  any write, upload or recompute gives a new one.
## 5F additions (D-146)

- `GET /api/v1/export?start=YYYY-MM-DD&end=YYYY-MM-DD&format=csv|xlsx`: the owner's
  transactions of those IST days (both included; 422 for a reversed range or more than about
  3 years) as a file built on the server, with `Content-Disposition: attachment`. CSV: the
  Transactions columns; xlsx: a Transactions and a Summary sheet. Never SMS text or a
  reference; formula-like text cells start with `'`.
## Premium run additions (D-147, D-148)

- Snapshot: `account.since_utc` (when this login joined) and `profile.data`
  (`{payments, first_utc, last_utc}`), for Profile.
- `GET /api/v1/analytics?start=YYYY-MM&end=YYYY-MM`: IST months, both included, 1 to 24
  (422 otherwise). `months[]` per month: `spent_paise`, `invested_paise`,
  `paid_back_paise`, `net_paise`, `income_paise`, `to_confirm_paise` (the same totals as
  `/summary`); `categories[]` (`slug`, `name`, `total_paise`, `share_bp`, `months[]`);
  `moves` (the last month against the one before: `up[]`, `down[]`, up to 3 each, or null);
  `merchants[]` and `people[]` (up to 8, with `count` and `share_bp`); `stats` (`days`,
  `per_day_paise`, `payments`, `biggest`, `busiest_weekday`, `ways_bp` {upi, card, other},
  `regular[]` paid in 3 or more months, `waiting` {count, amount_paise}). Shares are basis
  points. ETag `"a-<sha256>"` from the snapshot's cheap ETag and the range; If-None-Match
  gives a 304 without building.
- Premium C (D-149), outbox writes with Idempotency-Key:
  - `PUT /api/v1/transactions/{id}/payback` `{"answer": "paid_back" | "not_paid_back"}`: this
    one credit (422 for a debit). Beats the person-level answer (`/senders/{id}`), which never
    overwrites or deletes it. `DELETE` the same path forgets it.
  - `DELETE /api/v1/rules/{party_id}`: undo "All payments to <name>" (the party's default
    category); 404 for a party that is not the owner's. Repeating it is the same answer.
  - Snapshot `profile.rules[]` (`party_id`, `name`, `category`, `category_name`, `payments`)
    and `profile.credit_answers` (`{"<txn id>": "paid_back" | "not_paid_back"}`).

## 5G additions (D-153, D-156)

- `POST /api/v1/ingest/sms`: each `new_transactions` item adds `time_utc` (additive; older
  phones ignore it), so a notification can open its payment before any download.
- `PUT /api/v1/transactions/{id}/payback` also takes `{"answer": "income"}`: this one credit
  counts as Income (role income, a per-credit answer).
- `PUT /api/v1/transactions/{id}/leave` `{"question": "category" | "sender"}` and `DELETE`
  the same path (both questions back): "Leave as is" for the payment's payee, through the
  outbox. No amount, role or category changes. A left sender has `status` `left` in
  `/senders`, the snapshot's `todo.answered`, and is not counted in the month's
  `to_confirm.senders`.
- Snapshot: `todo.left` (`[{person_id, category, sender}]`) for "Ask again" in a payment's
  sheet; `profile.settings.count_investments_in_spent` is `true` unless the owner turned it
  off.
