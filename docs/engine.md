# Parsing engine

`backend/app/engine/` turns one bank SMS into a structured result. It is pure
Python (stdlib only) and imports no FastAPI, SQLAlchemy or app config, so it
runs in tests, scripts and later a worker unchanged.

```python
from datetime import datetime, UTC
from app.engine import parse_message

result = parse_message("VM-HDFCBK-S", body, received_at=datetime.now(UTC))
```

## Rules

- **One message, literally.** The parser reports only what this SMS says.
  Transfers, card bill payments, refund linking and duplicates across
  messages are decided later, in the Reconcile stage (step 3C).
- **Exactly one template.** If no template matches: `Unknown("no_template")`.
  If two match: `Unknown("ambiguous")`. The engine never picks one.
- **Notice fallback, never for amounts.** A parser may name an info fallback
  (HDFC: `H_INFO`). A message that matches no template **and contains no
  amount** (Rs, INR, ₹, or a foreign code such as USD followed by a number)
  becomes `other_info` under that id, never `is_money`. A message with an
  amount and no template stays `Unknown("no_template")`: amounts are never
  guessed.
- **Strict fields.** A matching template whose values do not check out (bad
  date, ambiguous amount, two different card numbers in one SMS) gives
  `Unknown("ambiguous")`, not a guess.
- **Money is integer paise** (`Decimal`, never `float`). **Times are UTC.**

## Pipeline

```
sender ID --parse_sender--> core (VM-HDFCBK-S -> HDFCBK)
core      --SENDER_BANKS--> bank code (HDFC)          else Unknown("unknown_sender")
bank      --PARSERS-------> BankParser                else Unknown("no_parser_for_bank")
body      --normalise-----> one line, single spaces
          --foreign check-> Unknown("foreign_currency_deferred")
          --templates-----> 0 matches, no amount: other_info (info fallback, if set)
                            0 matches, amount: Unknown("no_template")
                            2+ matches: Unknown("ambiguous")
                            1 match: fields -> ParsedMessage (or "ambiguous" if a value is invalid)
```

| Module | Job |
| ------ | --- |
| `senders.py` | Sender ID -> core (same rules as `scripts/redact_sms.py`; both pass `backend/tests/fixtures/sender_ids.json`) and core -> bank. |
| `money.py` | `to_paise("Rs.1,25,000.50")` -> `12500050`. Accepts Rs / Rs. / INR / INR. / ₹, Indian grouping or no commas, 0-2 decimals. Rejects anything else (`AmountError`). |
| `timeparse.py` | Every catalogued date/time format. IST is a fixed UTC+05:30 offset (no zoneinfo). |
| `models.py` | `ParsedMessage` and `Unknown` (frozen dataclasses). |
| `parsers/base.py` | `Template`, `BankParser`, field building. |
| `parsers/<bank>.py` | The bank's templates and `PARSER_VERSION`. |
| `parsers/__init__.py` | Registry: bank code -> parser. |

## Results

**`ParsedMessage`** fields: `bank`, `template_id`, `parser_version`, `type`,
`direction`, `amount_paise`, `currency`, `account_last4`, `channel`,
`counterparty_raw`, `reference`, `balance_paise`, `txn_time_utc`,
`time_inferred`, `hints`; property `is_money`.

| Type | Money? | Meaning |
| ---- | ------ | ------- |
| `debit` | yes | Money left an account or card. |
| `credit` | yes | Money arrived (includes FD closure; Reconcile decides if it is income). |
| `refund` | yes | Money returned for an earlier spend (direction credit). |
| `collect_request` | no | Someone asked for money (UPI collect). |
| `mandate` | no | A recurring payment was set up. |
| `upcoming_debit` | no | Notice of a future debit (for forecasts later). |
| `card_alert` | no | Declined or blocked card event. |
| `balance_info` | no | Balance only. |
| `fraud_warning` | no | Bank advisory. |
| `other_info` | no | Security and account notices. |

- `direction` is `debit`/`credit` for money types, else null.
- Money types always carry `txn_time_utc`: the SMS's own date-time, or
  `received_at` with `time_inferred: true` when the SMS has no time. Non-money
  types have both null.
- `account_last4` is the card's last 4 for card transactions.
- `counterparty_raw` is the text as written (whitespace collapsed); it may be
  a UPI ID. Naming it is a later step.
- `hints`: facts the wording states, for Reconcile, e.g. `card_bill_payment`.

**`Unknown`** has `reason`, plus `bank` and `detail` when known:
`unknown_sender`, `no_parser_for_bank`, `no_template`,
`foreign_currency_deferred`, `ambiguous`.

## Parser versions

Each bank module has `PARSER_VERSION` (e.g. `hdfc-1.1.1`), stored on every
result so stored messages can be re-parsed when a parser improves. Bump it
in the same commit as any change that can alter a result:

- **MAJOR**: a result field changes meaning.
- **MINOR**: a template is added (messages that were Unknown now parse).
- **PATCH**: a template fix changes values for some messages.

Refactors that keep every result identical need no bump; the fixture tests
prove that.

## Adding a bank

1. **Survey**: `scripts/shape_survey.py` on the redacted sample with the
   bank's sender cores; write `docs/templates/<bank>.md` (shapes only).
2. **Fixtures**: `backend/tests/fixtures/sms/<bank>.json`, fake values only
   (rules in DECISIONS D-027). The fixture tests pick the file up
   automatically.
3. **Parser**: `backend/app/engine/parsers/<bank>.py` with one `Template` per
   shape (comment naming the shape id), `PARSER_VERSION`, and `PARSER`.
4. **Register**: one line in `parsers/__init__.py`, and the bank's sender
   cores in `senders.SENDER_BANKS` if missing.
5. **Bank wording**: add the bank's fixed phrases to `BANK_VOCABULARY` in
   `scripts/redact_sms.py`.
6. **Check coverage**:
   `backend\.venv\Scripts\python.exe scripts\parse_coverage.py --input data\sample\redacted_sample.json`
   It prints counts and the shapes of Unknown messages, never bodies.

## Merchant normalisation

`app/engine/merchant.py` (`merchant-1.1.1`, D-057, D-058, D-068) turns a transaction's
`counterparty_raw` into a stable merchant. Pure and stdlib only; the only I/O
is loading `brands.json` once.

```python
from app.engine.merchant import channel_for, normalise_merchant

m = normalise_merchant(txn.counterparty_raw, channel_for(txn.channel, txn.hints))
m.kind, m.confidence, m.merchant_key  # "business", "high", "brand:swiggy"
```

**Channel.** `channel_for` maps the stored parser channel: `debit_card`,
`credit_card` -> `card`; `upi` -> `upi` (`autopay` with hint `autopay`,
H17); `netbanking`, `neft`, `imps` -> `bank_transfer`; `atm` -> `atm`;
`e_mandate`, `nach` -> `autopay`; anything else (`fd`, `emi`, `cash`, none)
-> `other`.

**Rules, in order** (codes in `Merchant.reasons`):

| Rule | What | Result |
| ---- | ---- | ------ |
| R0 | No text left after cleaning (`R0_no_text`), or channel `atm` (`R0_atm`) | `none`, high, no key |
| R1 | NFKC, casefold, collapse whitespace, strip outer punctuation (not `*`, the UPI mask). One `local@handle` is split off (`R1_vpa`); an `@` that is not a valid UPI ID is `R1_vpa_malformed` and stays name text | - |
| R2 | Gateway prefix `PAYTM*`, `RAZ*`, `PYU*`, `CCA*` at the start of the name, only with `*` and only if text remains (`R2_gateway`). Cities are never stripped | - |
| R3 | Brand dictionary on whole tokens, anchored: an alias matches only at the start of the name (after the gateway prefix and a leading `www` word) or at the start of the UPI local part (split on `. - _ *`). An alias later in the text is no match. Longest alias wins (tokens, then characters); two brands of the same length, one from the name and one from the UPI ID: `R3_tie`, no match | `business`, high, `brand:<id>` |
| R4 | Channel `card` or `autopay` (`R4_card`, `R4_autopay`) | `business`, high |
| R5 | Signals, below | below |

R5 signals. Business: `R5_keyword` (a word in `BUSINESS_WORDS`, or `M/S`),
`R5_domain` (`name.com`, `.in`, `.net`, `.org`, `.io`, `.app`),
`R5_merchant_vpa` (local part `q` + 6 or more digits, or starting `paytmqr`,
`bharatpe`, `vyapar`, `gpay-`), `R5_business_handle` (handle starts with
`okbiz`), `R5_digits` (a digit in the name). Person:
`R5_honorific` (first word `mr mrs ms dr shri smt` and more words follow),
`R5_mobile_vpa` (local part is a 10-digit mobile, optional `91`),
`R5_consumer_vpa` (handle `okaxis`, `okhdfcbank`, `okicici` or `oksbi`),
`R5_person_name` (2-4 words of letters only, no business keyword or domain).

- Business signals only: `business` (`R5_business`), high unless
  `R5_digits` is the only signal.
- Person signals only: `person` (`R5_person`), high with an honorific or
  with a mobile UPI ID plus a person-shaped name, else low.
- Both (`R5_unsure_mixed`) or neither (`R5_unsure_none`): `unsure`, low.

`BUSINESS_WORDS` (186 words) holds common Indian shop and business words
(`kirana`, `tiffin`, `mess`, `xerox`, `medicals`, `travels`, ...). Whole
tokens only; never a word of one or two letters, never a word that is also
a common Indian given name or surname. The handle lists
(`CONSUMER_HANDLES`, `BUSINESS_HANDLE_PREFIXES`) sit next to it.

**Merchant key.** `brand:<id>` on a dictionary match; else `vpa:<upi id>`
(casefolded, mask kept); else `name:<words>`: casefolded, apostrophes
removed, every other non-letter/digit a space, leading honorifics removed,
single spaces. Case, spacing and punctuation do not change the key; `S.K.`
and `SK` do (`s k` vs `sk`). A key change is a version bump. Owner data
stores the owner's text, never a key, and each run works the key out again,
so a key change needs no data migration; recompute checks that no
transaction loses its owner match (D-065).

**Display name**, for every kind except `none`: the brand's name on a
dictionary match; else the cleaned name in title case, gateway prefix
removed, when there is name text; else the UPI ID in lower case. A name
beside a UPI ID is shown, and the UPI ID stays the key (`merchant-1.1.1`,
D-068). Normalising a display name again gives the same key when the
display name comes from the same text as the key, so not for a name shown
beside a UPI ID (tested).

**Dictionary** `app/engine/brands.json`: `id`, `name`, `aliases`. Only
well-known national brands from public knowledge, nothing from the owner's
data; the owner's merchants and people come from corrections (3D) and live
only in the database. Each display name is also an alias, and no alias may
belong to two brands (checked at load and in tests). No categories yet.

**Version.** `MERCHANT_VERSION` covers rules, word lists, dictionary and key
format: bump it on any change that can alter a kind, a key or a display
name.

**Commands** (from `backend\`, read-only, engine runs in memory over active
transactions):

- `python -m app.cli merchant-stats`: counts only, safe to paste. Kind by
  channel, confidence and direction (debit, credit, refund), reason codes,
  dictionary hits, distinct keys (by kind and confidence, seen once or more),
  how many keys cover 50%, 80% and 95% of keyed transactions, keys with
  both a debit and a credit, unsure shapes, UPI handles seen 5+ times.
- `python -m app.cli merchant-review [--kind K] [--confidence C]
  [--reason CODE] [--direction debit|credit|refund] [--sample N] [--seed S]`:
  **owner only**. One line per merchant key: raw counterparty text, display
  name, key, kind and confidence, reasons, number of transactions; never
  amounts or references. First and last line: `PRIVATE: do not paste this
  into any chat or file.` It refuses to run when stdout is not a terminal,
  so it cannot be piped, redirected or captured by a tool. Agents never run
  it on real data.
