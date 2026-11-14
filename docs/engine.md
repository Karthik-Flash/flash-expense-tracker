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
  messages are decided later, in the Reconcile stage (Phase 2-3).
- **Exactly one template.** If no template matches: `Unknown("no_template")`.
  If two match: `Unknown("ambiguous")`. The engine never picks one.
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
          --templates-----> 0 matches: Unknown("no_template")
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

Each bank module has `PARSER_VERSION` (e.g. `hdfc-1.0.0`), stored on every
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
