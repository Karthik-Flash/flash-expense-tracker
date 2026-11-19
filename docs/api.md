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
- `AUTH_USERS` maps the token's `sub` to an owner: `"<sub>:<owner_id>"`,
  comma-separated.

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
| GET | `/api/v1/senders?status=to_confirm\|confirmed\|ignored\|all` | Senders of paybacks, uncertain credits, income and ignored credits, largest total first |
| PUT | `/api/v1/senders/{id}` | `{"answer": "friend"}`, `{"answer": "income", "label": "..."}` or `{"answer": "ignore"}` |
| DELETE | `/api/v1/senders/{id}` | Forget the answer: the sender is to confirm again |
| PUT | `/api/v1/transactions/{id}/category` | `{"category": slug, "scope": "merchant" \| "transaction"}` |
| PUT | `/api/v1/transactions/{id}/label` | `{"label_id"}`, or `{"new_label": name}` to make a label and attach it in one write (409 when the name exists): at most one label per transaction |
| DELETE | `/api/v1/transactions/{id}/label` | Remove the label (also when there is none) |

**Writes** are saved with source `app`, are idempotent, and end with one
recompute in the same database transaction, under the owner's lock: the
answer and the derived rows are saved together or not at all. The response
is `{"result": {...}, "recompute": {"status": "done" | "unchanged", "run": id}}`.
Errors: 404 (not this owner's, or no such id), 422 (validation), 409 (owner
data that cannot hold, a recompute stopped by an engine change, or a label
name the owner already has).

- `scope: merchant` sets the default on the merchant's party (made from the
  transaction's text if there is none): every past and future payment to it.
  This transaction's own one-off, if any, is removed. A transaction with no
  merchant text (an ATM withdrawal) answers 422; use `scope: transaction`.
- `friend` makes the sender's party a person (a payback, confirmed);
  `income` makes it an income source with that label; `ignore` sets role
  `ignored` on its current credits. A sender with no text gets role
  decisions instead of a party. An ignored sender can be answered again.
- `DELETE /senders/{id}` removes the sender's role decisions. A party the app
  made only for the answer is removed too. A party that also holds a default
  category, or comes from the owner file, keeps it and becomes a business,
  so its credits are to confirm (`CR_business`).
- **Names** (a label, an income label): trimmed, inner runs of spaces joined
  into one, then 1 to 30 characters. The client applies the same rules
  (`frontend/src/screens/derive.ts`).

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
| `todo` | `senders` (to confirm), `answered` (confirmed or ignored), `merchants` (uncategorised spending by name: `name`, `total_paise`, `count`, `txn_id`), `unnamed` |
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
  "person_id": "s_3f9a0c1d2e4b5a6c7d8e",
  "role": "spend",
  "role_basis": "engine",
  "category": "people",
  "category_name": "People",
  "category_basis": "engine",
  "label": null
}
```

- `role_basis`: `owner` when the owner decided the role (a confirmed payback,
  income, ignored), else `engine`. A payback with basis `engine` is to confirm.
- `person_id`: who the money went to or came from. `p_<n>` when the text
  matches an owner party, else the sender id of the text (`s_...`, the same
  id as in `/senders`), else `null` (no counterparty text, such as an ATM
  withdrawal). One person seen under a name and a UPI ID gets one id only
  once the owner lists both texts on one party (owner file); the app cannot
  join them yet.

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
