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
| GET | `/api/v1/summary?month=YYYY-MM` | The month in IST: Spent, Paid back (owner-confirmed only), To confirm, Net, Income, Spent by category, counts, stale flag |
| GET | `/api/v1/transactions?month=&category=&label=&cursor=&limit=` | Newest first, `limit` 1 to 200 (default 50); `next_cursor` for the next page |
| GET | `/api/v1/categories` | The fixed list: `slug`, `name` |
| GET | `/api/v1/labels` | `id`, `name`, number of transactions |
| POST | `/api/v1/labels` | `{"name"}`: 201 created, or 200 with the existing label of that name |
| GET | `/api/v1/labels/{id}` | The label view across all dates: Spent, Paid back, To confirm, Net, Spent by category |
| GET | `/api/v1/senders?status=to_confirm\|confirmed\|all` | Senders of paybacks, uncertain credits and income, largest total first |
| PUT | `/api/v1/senders/{id}` | `{"answer": "friend"}`, `{"answer": "income", "label": "..."}` or `{"answer": "ignore"}` |
| PUT | `/api/v1/transactions/{id}/category` | `{"category": slug, "scope": "merchant" \| "transaction"}` |
| PUT | `/api/v1/transactions/{id}/label` | `{"label_id"}`: at most one label per transaction |
| DELETE | `/api/v1/transactions/{id}/label` | Remove the label (also when there is none) |

**Writes** are saved with source `app`, are idempotent, and end with one
recompute in the same database transaction, under the owner's lock: the
answer and the derived rows are saved together or not at all. The response
is `{"result": {...}, "recompute": {"status": "done" | "unchanged", "run": id}}`.
Errors: 404 (not this owner's, or no such id), 422 (validation), 409 (owner
data that cannot hold, or a recompute stopped by an engine change).

- `scope: merchant` sets the default on the merchant's party (made from the
  transaction's text if there is none): every past and future payment to it.
  This transaction's own one-off, if any, is removed. A transaction with no
  merchant text (an ATM withdrawal) answers 422; use `scope: transaction`.
- `friend` makes the sender's party a person (a payback, confirmed);
  `income` makes it an income source with that label; `ignore` sets role
  `ignored` on its current credits. A sender with no text gets role
  decisions instead of a party.

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
