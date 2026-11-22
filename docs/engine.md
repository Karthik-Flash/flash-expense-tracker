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
| `senders.py` | Sender ID -> core (same rules as `scripts/redact_sms.py` and the phone's `BankSenders.kt`; all pass `backend/tests/fixtures/sender_ids.json`) and core -> bank, from `shared/bank_senders.json` (5A, D-123: the same file is packed into the APK; `not_banks` lists registered senders that are not banks, PhonePe). |
| `money.py` | `to_paise("Rs.1,25,000.50")` -> `12500050`. Accepts Rs / Rs. / INR / INR. / ₹, Indian grouping or no commas, 0-2 decimals. Rejects anything else (`AmountError`). |
| `timeparse.py` | Every catalogued date/time format. IST is a fixed UTC+05:30 offset (no zoneinfo). |
| `models.py` | `ParsedMessage` and `Unknown` (frozen dataclasses). |
| `parsers/base.py` | `Template`, `BankParser`, field building. |
| `parsers/<bank>.py` | The bank's templates and `PARSER_VERSION`. |
| `parsers/__init__.py` | Registry: bank code -> parser. |
| `merchant.py` | Counterparty text -> merchant (below). |
| `reconcile.py` | One role per transaction, links, totals (below). |

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

Each bank module has `PARSER_VERSION` (e.g. `hdfc-1.2.0`), stored on every
result so stored messages can be re-parsed when a parser improves. Bump it
in the same commit as any change that can alter a result:

- **MAJOR**: a result field changes meaning.
- **MINOR**: a template is added (messages that were Unknown now parse).
- **PATCH**: a template fix changes values for some messages.

Refactors that keep every result identical need no bump; the fixture tests
prove that.

## Adding a bank

0. **Counts first** (the owner runs them, D-100): `bank-survey`,
   `generic-preview`, then `redact-sample --family <bank>` and, after
   reading the file, `redact-sample --approve <bank>`.
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

## HDFC 1.2.0 (D-127)

The owner's approved sample of the HDFC messages no parser read (4Z,
`redact-sample --family HDFC --unparsed`) holds 44 messages of one shape: H04,
the forex markup notice ("Notice! 1. Forex Markup fee applies to your HDFC
Bank Debit Card International payment 2. Final txn amount may change …"). It
has no amount: the international spend itself comes as an H03 alert in INR
and is counted. Until 1.1.1 a `FOREIGN_CURRENCY` pattern made it
`foreign_currency_deferred`, so each one added to "not counted yet". Since
`hdfc-1.2.0` it is template H04, type `other_info`, channel `debit_card`,
hint `forex_notice`; it never makes a transaction. A foreign-currency card
spend (`Spent USD …`, N14) stays deferred. On the 288-message redacted sample:
131 of 135 HDFC results are unchanged field for field; the 4 forex notices
went from `foreign_currency_deferred` to `other_info` H04.

## SBI parser (`sbi-1.0.0`, D-108)

`app/engine/parsers/sbi.py`: 14 templates, one per money shape in
[templates/sbi.md](templates/sbi.md), over the normalised body. Amounts may
lack a currency mark inside a template. The event time comes from the text
as in the generic parser (a date followed by a time, near the arrival time),
else the arrival time. No template: `hold` and `deposit_notice`, then the
generic parser's reject reasons (not_a_transaction); an amount or a
completed-action verb left over is `generic_unsure` with `no_template` (or
`card_no_template`). On the redacted sample: 53 accepted, 2 unsure, 55
refused (the generic parser: 24, 34, 52). S07, an outgoing NEFT, is a debit
(the generic parser read "credited to Beneficiary" as a credit).

## Generic parser (`generic-1.0.0`, D-101)

`app/engine/parsers/generic.py` reads banks in `senders.SENDER_BANKS` that
have no dedicated parser (`parsers.GENERIC_BANKS`: today ICICI, AXIS, KOTAK,
YES, INDIA_POST; never HDFC or SBI, which have their own, never PhonePe, an
app). It stays pure
and never invents a value.

1. **Foreign currency** (USD, EUR, ...): `foreign_currency_deferred`, as
   for HDFC.
2. **Rejects** (`not_a_transaction`, detail = reason), in this order:
   `otp`, `request` (has requested, collect request), `promo`
   (pre-approved, offer, eligible, loan up to, ...), `failed` (failed,
   declined, unsuccessful, reversed, cancelled, insufficient),
   `mandate_notice` (mandate/AutoPay/SI with registered, created, will,
   upcoming, pre-debit, ...), `card_bill_due` (credit card, card bill or
   statement with an amount due or minimum), `scheduled` (will be debited,
   scheduled, upcoming, reminder, is due), then `balance_only` (no
   completed action, a balance word) and `other`.
3. **Accept** only with all of: an INR amount (Rs, Rs., INR, the rupee
   sign; an amount right after Avl Bal, balance, limit or outstanding does
   not count), a completed-action verb (debit: debited, spent, paid, sent,
   withdrawn, purchase, "txn of ... at"; credit: credited, received,
   deposited), and an anchor (a mask such as XX1234, x123, *1234 or
   "ending 1234"; a UPI/IMPS/NEFT/RRN/UTR/Ref reference with 6+ digits; or
   a UPI ID). The first verb gives the direction. Otherwise
   `generic_unsure` with `no_verb`, `no_amount`, `amount_format` (for
   example Western grouping), `several_amounts` or `no_anchor`; these stay
   in "not counted yet".
4. **Fields**: amount in paise (`money.to_paise`); the account digits only
   when the message names one; the reference; the channel (atm, credit_card
   only when the text says credit card, else debit_card for a card, upi,
   imps, neft, netbanking, or none); the counterparty only from a single UPI
   ID or an explicit slot (to/at/towards for a debit, from/by for a credit,
   UPI/P2A/ref/NAME, "; NAME credited") before the closing wording ("Not
   you", "call", "SMS"); the event time from a date followed by a time, in
   IST, within 45 days before to 1 day after arrival, else the arrival time
   (`time_inferred`).
5. **Result**: type `debit` or `credit` (never `refund`), template `GEN`,
   hints `generic` (plus `generic_refund` when a credit says refund, and
   `card_bill_payment` for a payment received on a credit card).

Dedupe (`pipeline/dedupe.py`): a reference gives the usual `ref` key; else
`("gen", bank, direction, amount, account, event minute)`. `kind_of(body)`
gives the bank survey's kind for any message. Fixtures:
`backend/tests/fixtures/generic_sms.json` (92 accepted, 53 rejected, FAKE).
`generic-preview` counts what it would do over stored messages before a
reparse.

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

## Reconcile: roles and links

`app/engine/reconcile.py` (`reconcile-1.2.1`; design in
[design/phase-3-backbone.md](design/phase-3-backbone.md), D-059 to D-067)
gives every transaction exactly one role, and links transactions that are,
or may be, one event. Pure and stdlib only: no database, clock, network or
randomness, and the same input in any order gives the same output. Built so
far, all in memory: roles from one transaction (step 3C-2), duplicates
(3C-3) and pair linking (3C-5). Not built: the card bill pair rule, owner
tables, storage.

```python
from app.engine.reconcile import OwnerData, Txn, derive, totals

result = derive(txns, owner, legacy_pairs)
d = result.roles[txn.id]  # Derived
d.role, d.rule, d.basis, d.reasons, d.duplicate_of
for link in result.links:  # Link, ordered by kind and ids
    link.kind, link.txn_a, link.txn_b, link.status, link.rule, link.reason, link.decided_by
t = totals(txns, result.roles, start, end)  # start <= txn_time_utc < end
t.spent_paise, t.paid_back_paise, t.net_paise, t.income_paise
```

- **Input.** One `Txn` per active transaction (`id`, `bank`, `type`,
  `direction`, `amount_paise`, `account_last4`, `channel`,
  `counterparty_raw`, `txn_time_utc`, `hints`, `reference`). An `OwnerData`,
  which may be empty: `accounts` (`OwnAccount`: `kind`, `bank`, `last4`,
  `texts`), `parties` (`Party`: `kind`, `income`, `texts`), `roles`
  (transaction id -> the owner's role decision) and `links` (`(kind, lower
  id, higher id)` -> `"same"` or `"different"`). `legacy_pairs`: the id pairs
  recorded in `duplicate_candidates` at import, read-only. The engine
  versions are `reconcile.VERSIONS`.
- **Output.** `Result(roles, links, merchants)`. `roles` holds one `Derived` per
  transaction: `role`, `rule` (the code of the rule that decided), `basis`
  (`engine`: the transaction's wording alone; `owner`: the rule read owner
  data), `reasons` (every rule that matched, the deciding one first),
  `duplicate_of` (the primary, only for role `duplicate`), and `own_account`
  and `party`: the position in `OwnerData` of the entry whose text the
  transaction matches. `Result.merchants` holds the engine's `Merchant` per
  transaction. `links` holds
  `Link`s: `kind`, `txn_a` < `txn_b`, `status` (`linked` or `candidate`),
  `rule`, `reason`, `decided_by` (`engine` or `owner`).

**Roles and totals** (D-060).

| Role | Direction | Total |
| ---- | --------- | ----- |
| `spend`, `card_bill_counted` | debit | Spent (+) |
| `refund` | credit | Spent (-) |
| `payback` | credit | Paid back (+) |
| `income` | credit | Income (+) |
| `uncertain` | credit | none (shown as "uncertain credits") |
| `self_transfer`, `card_bill_excluded`, `fd_move`, `duplicate`, `ignored` | either | none |

Net = Spent - Paid back. `totals()` takes any two aware datetimes; a month
is an IST month (D-002), so pass IST midnights. Amounts stay integer paise.

**Role rules from one transaction, in order.** The first match decides.

| Rule | Evidence | Role | Basis |
| ---- | -------- | ---- | ----- |
| `OWNER_role` | An owner role decision. Any role except `duplicate`; it must fit the direction | as decided | owner |
| `FD_channel` | Channel `fd` | `fd_move` | engine |
| `FD_own_text` | Text of an own FD | `fd_move` | owner |
| `CB_hint` | Credit with hint `card_bill_payment` | `card_bill_excluded` | engine |
| `CB_own_text` | Debit to a text of an own credit card | `card_bill_excluded` when the card is tracked, else `card_bill_counted` | owner |
| `ST_own_text` | Text of an own bank account or wallet | `self_transfer` | owner |
| `RF_type` | Type `refund` | `refund` | engine |
| `ST_masked` | Credit from a masked UPI ID whose handle and visible end fit an own UPI ID | `uncertain` | owner |

Only when none of those matched:

| Rule | Evidence | Role | Basis |
| ---- | -------- | ---- | ----- |
| `CR_income_party` | Credit from a party marked as income | `income` | owner |
| `CR_person_party` | Credit from a party of kind person | `payback` | owner |
| `CR_person_signal` | Credit; the merchant engine says person with `R5_honorific`, `R5_mobile_vpa` or `R5_consumer_vpa`, and (since `reconcile-1.7.0`, D-134) the owner paid that person at most 90 days before | `payback` | engine |
| `CR_no_debit` | The same signals, with no such payment (`reconcile-1.7.0`) | `uncertain` | engine |
| `CR_name_only` | Credit; person on the shape of the name alone | `uncertain` | engine |
| `CR_business` | Credit from a business (the engine, or a party of kind business) | `uncertain` | engine or owner |
| `CR_unsure`, `CR_no_text` | Credit; merchant unsure, or no text | `uncertain` | engine |
| `CR_own_account` | Credit from a text of an own credit card or FD that no rule above explains | `uncertain` | owner |
| `DB_no_counterparty` | Debit with no payee text that is not an ATM withdrawal | `spend` | engine |
| `DB_spend` | Any other debit | `spend` | engine |

- **Text of** an account or party: the transaction's merchant key equals the
  key of a text the owner listed (case, spacing and punctuation do not
  matter). One text listed in two places is an error.
- **Tracked** (D-059): the input holds a debit with channel `credit_card`,
  the card's bank and one of its last 4, from 60 days before the payment up
  to the payment itself (both ends included).
- A guess never lowers Net: an unexplained debit is `spend`, an unexplained
  credit is `uncertain`.

**Link rules.** A rule links a pair only when it is **unique**: each side has
exactly one compatible partner for that rule. Otherwise every pair involved
is a candidate. Nothing is greedy, and "closest in time" never wins. A
candidate changes no role and no total. Windows compare `txn_time_utc` and
include both ends.

| Kind | Rule | Compatible pair | Unique pair | Role effect of a link |
| ---- | ---- | --------------- | ----------- | --------------------- |
| `duplicate` | `DUP_autopay_card` | Two debits, same bank, card last 4 and amount; one `e_mandate`, one `debit_card` or `credit_card`; not two different brands; at most 24 hours apart | Linked (`unique_10min`) at most 10 minutes apart; candidate (`within_24h`) beyond | The earliest (then lowest id) keeps its role; the other is `duplicate` |
| `duplicate` | `DUP_same_amount` | Same bank, `account_last4`, direction and amount, at most 10 minutes apart, not a pair of the rule above, and not two different references (D-069) | Always a candidate (`same_amount`) | none |
| `duplicate` | `DUP_legacy` | A pair from `legacy_pairs`, both active, that no rule found | Always a candidate: `different_references` when both sides carry a reference and they differ, else `recorded_at_import` | none |
| `self_transfer` | `ST_reference` (`reconcile-1.5.0`, D-115) | A debit and a credit of the same amount on two different own bank accounts (listed or inferred), carrying the same 12-digit UPI/IMPS reference (`upi_reference`: the reference text holds exactly one), at most 24 hours apart; both legs unexplained or `ST_own_text` | Linked (`same_reference`): the shared reference proves it | Both legs `self_transfer` (rule `ST_reference`, basis engine) |
| `self_transfer` | `ST_pair` | As above with no shared reference (two different references are two payments) | Linked (`names_partner_account`) when one leg's text names the account the other leg is on, at most 24 hours apart; else, at most 30 minutes apart, candidate (`no_own_text`): the owner answers "Moved between your accounts?" | Both legs `self_transfer` (rule `ST_pair`, basis owner) |
| `refund` | `RF_same_amount` | A refund and a purchase (role `spend` or `card_bill_counted`) of the same amount, same bank and `account_last4`, purchase at most 30 days before | Linked (`same_merchant`) when the merchant keys are equal; else candidate (`different_merchant`) | none: a refund is role `refund`, linked or not |
| `refund` | `RF_partial` | As above with a larger purchase and equal merchant keys; only for a refund with no full-amount pair and no owner link | Always a candidate (`partial`) | none |
| `fd` | `FD_pair` | An `FD_channel` credit and an unexplained credit, same bank and amount, at most 3 days apart | Always a candidate (`second_credit`) | none |
| any | `OWNER_link` | The owner said "same" about a pair no rule proposed | Linked (`owner_same`) | As for the kind; an fd link gives `fd_move`, a refund link gives the credit role `refund` |

- **Unexplained**: the role comes from the engine's default rules (`CR_*`
  or `DB_*` with basis engine) or from `ST_masked`. A transaction whose role
  the owner fixed is never paired by a rule.
- A pair with more than one partner on a side is a candidate with reason
  `several_partners`. A pair the owner called the same counts as a partner.
- **Owner link decisions.** "same" links the pair (reason `owner_same`,
  decided by owner) and keeps the rule that found it. "different" removes
  the pair for good: no rule proposes it again, and it is dropped from
  `legacy_pairs` too. A decision about a transaction that is not in the
  input is ignored. A role decision wins over a link.
- **References never make a match**; a mandate ID is never a match key
  (D-046). Two different references of the same kind rule a same-amount
  pair out: they are two payments (D-069). A mandate ID and a payment
  reference are different kinds and rule nothing out (D-072). Such a pair is kept only when it was recorded at
  import, as `DUP_legacy` with reason `different_references`.
- A duplicate group is every transaction joined by linked duplicate links.
  A rule's group has two members; a larger one is the owner's.
- Errors (`ValueError`, never with a value from the data): an unknown kind
  or verdict, ids out of order, a "same" pair that cannot be that kind (two
  amounts as one duplicate, two debits as a transfer, a refund larger than
  its purchase), owner decisions that contradict each other, refunds linked
  by the owner that add up to more than the purchase, one account number
  under two own accounts.
- **Version.** Bump `RECONCILE_VERSION` on any change that can alter a role,
  a rule code, a basis or a link.

**Command** (from `backend\`): `python -m app.cli reconcile-stats`.
Read-only, in memory, counts only, safe to paste: role by direction, role by
rule, transactions matched by two or more rules, paybacks by basis,
uncertain credits, links by kind and status, candidates by kind and reason,
AutoPay + card pairs by time gap and by merchant facts (same key, brand
hits, which message is earlier), what became of the existing
`duplicate_candidates` pairs ("lost" must be 0), messages not counted yet,
owner data counts, and a warning line when the owner data lists no income
party, and the "stored run" (last recompute, its versions, stored rows that
differ from a fresh derive). It reads the owner tables. Storage and the
`recompute` and `owner-load` commands: [data-model.md](data-model.md).

**"matched by two or more rules"** in `reconcile-stats` counts transactions
whose `reasons` hold two or more rule codes. Two causes, shown on two lines
under it:

- *one-message rules agree*: two rules that read one transaction both
  matched (for example channel `fd` and the text of an own account); the
  earlier row decided.
- *a link or decision overrides*: the deciding rule is `DUP_autopay_card`,
  `ST_pair`, `OWNER_link` or `OWNER_role`, placed in front of the rule that
  read the message. Every non-primary member of a linked duplicate group is
  here, so on data with 4 linked duplicates and nothing else the line is 4.

**Helpers.** `reconcile.ist_month("2026-01")` gives the start and end (UTC)
of that IST calendar month, for `totals()`. `money.format_inr(paise)` gives
`Rs 1,23,456.78` (Indian grouping, `-Rs` for a negative amount).

## Categorise: one category per transaction

`app/engine/categorise.py` (`categorise-1.0.0`, D-073, D-074) runs on the
Reconcile result. Pure and stdlib only.

```python
from app.engine.categorise import CATEGORIES, breakdown, categorise, label_view

categories = categorise(txns, owner, result)  # {transaction id: Categorised}
c = categories[txn.id]
c.category, c.rule, c.basis  # "food_drinks", "BRAND", "engine"
breakdown(txns, result.roles, categories, start, end)  # {slug: paise}, sums to Spent
label_view(txns, result.roles, categories, labelled_ids)  # (Totals, {slug: paise})
```

`CATEGORIES` maps the 20 slugs to their names, in list order. Owner input:
`OwnerData.categories` (transaction id -> slug) and `Party.category`.

| Rule | When | Category | Basis |
| ---- | ---- | -------- | ----- |
| `OWNER_txn` | The owner decided this transaction (any role) | as decided | owner |
| `NS_<role>` | The role is not spending | payback: People; card_bill_excluded: Card bill; fd_move: Investments; income, self_transfer, duplicate, ignored, uncertain: Other | engine |
| `RF_linked` | A refund linked to a purchase | the purchase's | the purchase's |
| `OWNER_party` | The matched owner party has a default | the party's | owner |
| `CH_atm` | Debit, channel `atm` | Cash | engine |
| `ROLE_card_bill` | Role `card_bill_counted` | Card bill | engine |
| `CH_emi` | Debit, channel `emi` | EMI & Loans | engine |
| `HINT_fee` | Debit with hint `bank_charge` (no parser emits it yet) | Fees & Charges | engine |
| `BRAND` | The merchant is in the brand dictionary | `BRAND_CATEGORIES[brand]` | engine |
| `KEYWORD` | Every category keyword in the name agrees | that category | engine |
| `KW_conflict` | Keywords of two categories | Uncategorised | engine |
| `PERSON` | Debit to a person (engine kind, or a party of kind person) | People | engine |
| `NONE` | Nothing matched | Uncategorised | engine |

- Spending roles are `spend`, `card_bill_counted` and `refund` (minus). An
  unlinked refund goes through `OWNER_party`, `BRAND`, `KEYWORD`, `NONE`.
- Keywords are whole words of the name (`KEYWORD_CATEGORIES`): business
  keywords of the merchant engine whose meaning is clear, plus mutual,
  securities, broking, demat. Generic words (store, traders, services,
  hotel) are not mapped. The UPI ID is not searched.
- Every brand has one category (`BRAND_CATEGORIES`, checked by a test).
  Wallets (Paytm, PhonePe, MobiKwik) are Uncategorised.
- `breakdown()` sums a range by category and adds up exactly to Spent.
  `label_view()` gives a label's Spent, Paid back, Net and breakdown across
  all dates; a label never changes a category.
- Bump `CATEGORISE_VERSION` on any change that can alter a category, rule or
  basis. Recompute records it next to the other versions.

**Commands.** `category-stats`: counts and percentages only, safe to paste.
`category-review [--uncategorised] [--list]`: owner only, terminal only;
merchants by transaction count with their category, the owner picks one,
which is saved on a party (source `terminal`), then one recompute.
`totals --month` also prints Spent by category.

## People (`reconcile-1.4.0`, `categorise-1.1.0`, D-096)

The engine never names or joins anyone; it reads the owner's parties as
before. A party of kind **unsure** (named or joined in the app, no answer
yet) gives no owner opinion: its credits follow the merchant rules
(`CR_person_signal`, `CR_name_only`, ...) and its debits are People only when
the merchant engine says person. Senders group by party when one matches,
else by merchant key. Nothing changes for data without unsure parties.

## Paybacks, senders and inferred accounts (`reconcile-1.3.0`)

- **Only confirmed paybacks lower Net** (D-076). `totals()` puts a payback
  into Paid back only when its basis is `owner`; one the engine guessed goes
  to `Totals.to_confirm_paise`. Net = Spent - Paid back.
- **Senders** (`app/engine/credits.py`): `credit_senders(rows, salt)` groups
  `CreditRow`s of role payback, uncertain or income by merchant key (a credit
  with no key is its own sender), largest total first. A `Sender` has an
  opaque id (`s_` + a hash of the key and a per-owner salt), display name,
  total, count, dominant role, basis (owner when every credit is
  owner-decided) and status (`to_confirm` while any credit is uncertain or an
  engine-guessed payback). Answers live in `app/pipeline/owner_actions.py`.
- **Inferred own accounts** (D-077): `inferred_accounts(txns)` is every
  (bank, last 4) of a message on a bank account channel. Since
  `reconcile-1.5.0` (D-115) an SBI message with a last 4 counts too when it
  has no channel ("Your A/C X1234 has a credit…"): SBI has no card template.
  The self-transfer rules use them next to the owner's list: a shared
  12-digit reference links; otherwise a pair is a candidate (30 minutes)
  unless an owner text names the account.

## Statement reader and check (`stmt-hdfc-1.0.0`, D-114)

- `app/engine/statement_hdfc.py` reads an HDFC NetBanking "Delimited"
  statement (plain text, comma-separated, padded fields; header Date,
  Narration, Value Dat, Debit Amount, Credit Amount, Chq/Ref Number, Closing
  Balance, matched trimmed and case-insensitively). A row is read from the
  right: the last five fields are fixed, the first is the date (dd/mm/yy,
  an IST day), the rest is the narration, which may hold commas. Lines
  before the header and lines that are not rows are skipped. Each row gets
  its channel (upi, neft, imps, rtgs, atm, pos, nach, interest, charges,
  netbanking, cash, other), and for UPI the name and UPI ID, and the
  12-digit reference (one in the narration, else the reference field after
  leading zeros). `check_balances` counts rows whose closing balance is not
  the previous one plus credit minus debit: a bad read shows there first.
  Pure, stdlib only; meant to be reused by the Phase 6 statement import.
- `app/engine/statement_check.py` matches statement rows to the app's HDFC
  rows (any role but duplicate, the statement's IST days): the same
  reference and direction first, then the same amount and direction on the
  same day, then a day apart; never one row twice. Per IST month: totals of
  both sides, matched (by reference / by amount and day), statement-only,
  app-only, amount mismatches, and every unmatched row's likely cause:
  `no_sms`, `month_edge`, `foreign_currency`, `reversed_or_failed`,
  `duplicate_alert`, `card_or_other_account`, `unknown` (rules in the
  module docstring). `app/pipeline/statement.py` reads the app side and the
  month's Spent and Paid back as stored.
- `reconcile-stats` adds "inferred own accounts" and "self-transfers by
  basis". `credit-review [--list]`: owner only, terminal only.

## Phase 4Z: statement 1.1.0, causes, It's me, investments, names (D-117 to D-120)

- **`stmt-hdfc-1.1.0`**: a comma inside double quotes does not split a field
  (quoted thousands separators), a blank or "-" amount is zero, and a row
  with a negative or two-sided amount is one movement whose reading keeps the
  balance chain unbroken (`netted`); a row that nets to zero is skipped.
- **statement-check causes** (`statement_check.stmt_cause`, first that
  fits): foreign_currency, reversed_or_failed, sms_not_parsed, fd,
  investment_or_broking, card_bill_payment, own_or_internal,
  verification_or_tiny, no_sms, likely_spend, likely_income, unknown. The
  `Context` holds the owner's name variants, the own last 4s and the unread
  HDFC messages (IST day, amounts in their text); it is built in
  `app/pipeline/statement.py` and never printed.
- **statement-import** (`statement.plan_import`, `apply_import`): each
  statement-only row becomes a raw message (source `statement`, sender core
  `STATEMENT`) and a parse result of `stmt-hdfc-1.1.0`, then the usual
  `store.link_new`: the dedupe key is the SMS key when the row has a 12-digit
  reference. Hints: `statement`, plus `statement_check` (spend that asks
  "Looks right?"), `statement_ask` (own or investment debits), `bank_charge`.
  An SMS with no key match merges into the one statement row of the same
  bank, direction and amount within a day (`store.statement_twin`) and
  replaces its fields. Reparse and the surveys skip statement rows.
- **`reconcile-1.6.0`**: `PT_self` (an owner party of kind `self`: every
  payment is `self_transfer`) and `PT_investment` (kind `investment`: every
  payment is role `investment`, in no total), basis owner, among the rules a
  transaction carries itself; `SM_credit` (a statement credit is uncertain)
  and `SM_ask` (a statement debit with `statement_ask` is uncertain until the
  owner answers), basis engine, before the credit and debit defaults.
- **`app/engine/suggest.py`**: `is_owner_name` (token-based, tolerant of
  initials and order) and `is_investment` (broker, clearing and fund words).
  They only make To-do questions and statement causes, never a role.
- **`categorise-1.2.0`**: keywords per category on the name and the UPI ID's
  words; PERSON gives way to a business word; `NAME_person` for a person-like
  name the merchant engine was unsure of, or a bare personal UPI ID.
  `GUESS_RULES` (BRAND, KEYWORD, PERSON, NAME_person) are shown as "guessed
  from the name".

## 5B-1: People, paybacks and investments (D-133 to D-136)

### Engine changelog

| Version | Was | What changed |
| ------- | --- | ------------ |
| `categorise-1.3.0` | 1.2.0 | People only when clearly personal (below); rules `PERSON_name`, `PERSON_vpa` replace the merchant engine's kind and `NAME_person`; `PERSON` is only an owner party of kind person |
| `reconcile-1.7.0` | 1.6.0 | `CR_person_signal` needs a payment to the same person in the 90 days before; else `CR_no_debit` (uncertain). `totals()` gains `invested_paise` and the `invest` setting |
| `merchant-1.1.1` | unchanged | no brand, word list or key change, so no merchant key moves and recompute's key-change stop cannot fire |
| parsers | unchanged | `hdfc-1.2.0`, `sbi-1.0.0`, `generic-1.0.0`: a reparse changes no result; it runs the new recompute |

### Which rules sent a payee to People (categorise-1.2.0)

A spending debit with no owner decision, party default, channel rule, brand or
keyword was People when:

1. `PERSON`: the merchant engine said person. Its person signals are an
   honorific with more words, a 10-digit mobile UPI ID at any handle, one of
   the handles `okaxis`, `okhdfcbank`, `okicici`, `oksbi` (alone enough), or two
   to four words of letters with no merchant business word. Only a word of the
   1.2.0 list (`BUSINESS_WORDS`, the category keywords, hall, depot, hotel,
   agency, store, traders, …) stopped it. So "Sharma and Sons", "Test India
   Payments", "PAYTM*Ravi Kumar" (the gateway prefix is stripped first) and a
   masked `*k77@okhdfcbank` were People.
2. `NAME_person`: the merchant engine was unsure (mixed signals) and the name
   alone looked like a person's. So a person's name beside a merchant QR UPI ID
   (`paytmqr…`, `bharatpe…`, a Razorpay or `okbiz` handle) was People.
3. A party of kind person (the owner answered Friend) was People whatever the
   name.

### People only when clearly personal (categorise-1.3.0, D-133)

- An owner party of kind person: `PERSON` (People). Of kind business: never.
- Else nothing business-like may be anywhere (`business_like()`): a word of
  `NOT_PERSON` in the name or the UPI ID's words (the 1.2.0 list plus tech,
  co, and, sons, bros, india, payments, merchant, market, palace, …); a
  gateway, aggregator or merchant QR word in the UPI ID or its handle
  (`MERCHANT_VPA_WORDS`: rzp, razorpay, cashfree, payu, billdesk, paytmqr,
  bharatpe, gpay, mab, qr, pos, fbpe, …) or `biz` in the handle; and the
  merchant engine's own business reasons (card or AutoPay channel, a business
  word, a domain, a merchant UPI ID, an `okbiz` handle, digits in the name, a
  gateway prefix, two brands at once).
- Then `PERSON_name`: two to four words of letters, one of three letters or
  more (initials allowed), or an honorific with one to four words.
  `PERSON_vpa`: a personal UPI ID (a mobile number, or letters, digits and dots)
  at a consumer app's or a bank's handle (`ok*` but not `okbiz*`, `ybl`, `ibl`,
  `axl`, `paytm`, `apl`, `upi`, the banks' handles), with no name or with one
  word.
- Anything else, one word alone, five words, a masked UPI ID, an unknown
  handle: Uncategorised (`NONE`), and To-do asks.
- Categories never touch a role, a link or a total (categorise runs after
  reconcile; tested in `tests/test_people_bias.py` under both rule sets). The
  People ledger's "Sent" and the Home People slice move with the category.
- `categorise(rules="1.2.0")` keeps the old rules for `category-diff` only.

### Paybacks (reconcile-1.7.0, D-134)

How a credit becomes money back from a person, in order (the first that
matches decides):

1. **Owner answers** win: an owner role decision; It's me (party kind self:
   `self_transfer`); Investments (kind investment); a listed own account
   (`ST_own_text`); a shared 12-digit reference between two own accounts
   (`ST_reference`). A refund is a refund (`RF_type`), never a payback.
2. **`CR_income_party`**: a party marked as income (Family, Income) is income.
3. **`CR_person_party`**: a party of kind person (the owner answered Friend or
   Paid back): every credit of that person is a payback, basis owner, and
   counts in Paid back. A party of kind unsure (named or joined, no answer)
   gives no opinion.
4. **`CR_person_signal`**: no party answer, the merchant engine's person signal
   (honorific, mobile UPI ID, consumer handle) **and** the owner paid the same
   person (one party, so joined names and UPI IDs count together; else the same
   merchant key) at most 90 days before (`PAYBACK_WINDOW`, both ends included):
   a payback guess, basis engine. **It counts in To confirm only, never in
   Paid back, Net or Spent** (D-076: `totals()` moves a payback of basis engine
   to `to_confirm_paise`).
5. **`CR_no_debit`**: the same signal with no such payment: uncertain. Pocket
   money, a gift or a sale is not called a payback just because the sender is
   a person.
6. Every other credit: uncertain (`CR_name_only`, `CR_business`, `CR_unsure`,
   `CR_no_text`, `CR_own_account`, and `SM_credit` for a statement credit).

**Which payment a payback pays back** (`credits.payback_links`, the snapshot's
`paybacks`; display only, never a role or a total): a credit of role payback
and a spending debit (`spend`, `card_bill_counted`) to the same person, paid
at most 90 days before it. A credit with exactly one such payment is
`linked`; with several, a `candidate` of each (`several_payments`; the engine
never picks the closest in time). When a payment's linked credits add up to
more than the payment, they are all candidates (`more_than_paid`).

| Case (tests/test_paybacks.py, FAKE) | What happens |
| ----------------------------------- | ------------ |
| Payback in a later month | Linked; counts in the month it arrives (D-060), To confirm until answered, then Paid back |
| Partial paybacks | Each part linked to the one payment; Paid back is their sum |
| One payment paid back by several people (a split at a shop) | Not linked (no person to match), no guess (`CR_no_debit` or uncertain); each counts once the owner answers Friend |
| Several credits for one payment | Each linked to it while they add up to at most the payment |
| One credit covering several payments | A candidate of each payment; counted in full once confirmed |
| The same person under joined identities | Joined into one party: linked and a guess; answered Friend: confirmed |
| A credit from a person never paid | `CR_no_debit`, uncertain: not a payback, not even To confirm |
| A merchant refund vs a payback | Only refund wording (`RF_type`) is a refund (lowers Spent); a plain credit from a shop is uncertain |
| A transfer from the owner's own account under the owner's name | A bare name is uncertain; It's me or a listed account makes both legs `self_transfer`; never Paid back |

**The 13 engine paybacks** (the owner's `reconcile-stats`: payback 139 = owner
126 + engine 13) are role payback with basis engine. Before 5B-1 they already
counted in neither Paid back nor Net nor Spent: only in To confirm (the Home
"To confirm" row and the People ledger's "To confirm" column). Nothing needed
fixing; 1.7.0 makes them stricter (a payment to the person before), so those
with no such payment become uncertain. `payback-review` counts them.

### Investments (D-136)

- Only the owner makes an investment: the answer Investments (party kind
  investment, `PT_investment`) or an owner role. Role `investment` is in no
  total by default; `totals(..., invest=True)` (the owner's setting "Count
  investments in Spent") counts investment debits in Spent too, under the
  Investments category, so the breakdown still adds up to Spent.
- `Totals.invested_paise`: the month's investment debits, whatever the
  setting. A credit from a broker (a redemption) is in no total either way.
- A payee the app only suggests ("Is this an investment?", `suggest.is_investment`)
  stays a spend in Spent and is shown as Invested (to confirm) until the
  owner answers.
### Masked senders (reconcile-1.7.1, D-145)

HDFC writes the sender of a UPI credit masked ("*ahad@oksbi"); the payment names the payee in
full ("rahad@oksbi"). `reconcile.masked_fits(masked, full)`: the same handle, the full local
part ends with the visible end, something is visible. A credit with no payment to its own
person in the 90 days before takes the one person whose payment fits (`_masked_payee`, and
the same in `credits.payback_links`); two or more: no match. Tests: `tests/test_paybacks.py`
(masked to payee, two payees with one visible end, another handle or end, a blank mask, too
old, a joined identity, never on amount alone).