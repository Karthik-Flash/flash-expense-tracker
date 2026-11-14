# HDFC Bank SMS templates

Survey of senders `HDFCBK` and `HDFCBN` in the redacted sample (14 Nov 2026):
**135 messages, 15 shapes, 135 matched** (100%). Produced with
`scripts/shape_survey.py`; regenerate with the command in [NOTES.md](../../NOTES.md).

This file holds shapes only. No message text or value from the sample is
copied here. Fixtures with fake values: `backend/tests/fixtures/sms/hdfc.json`.

**Placeholders:** `{AMOUNT}` money with Rs/Rs./INR/₹, `{DATE}`, `{TIME}`,
`{ACCT}` masked account or card (XX1234, *1234, **1234, x1234, or the 4 digits
after `DC`), `{REF}` reference or mandate ID, `{VPA}` UPI ID, `{PARTY}`
counterparty or merchant text, `{BAL}` balance amount, `{CURRENCY}` non-INR
code, `{URL}`, `{PHONE}` (helpline or SMS number), `{NUM}` any other number.
Line breaks are shown as separate lines.

**Fields** use the fixture names: `amount_paise`, `direction`,
`account_last4`, `channel`, `counterparty_raw`, `reference`, `balance_paise`,
`txn_time_utc`. Channel values: `upi`, `netbanking`, `debit_card`, `atm`,
`credit_card`, `e_mandate`, `nach`, `neft`, `imps`, `emi`, `cash`.

> **Redaction artifacts.** Default-deny redaction replaced some fixed bank
> words with `{PARTY}`: the card label in `From {PARTY} At` (real text is
> likely "HDFC Bank Card x" plus last 4), `from {PARTY} {NUM}` in H12, and the
> word in `Biometric {PARTY}!` (H09). The real templates contain fixed text
> there. Parsers must not depend on those slots; take the card number from
> `DC {ACCT}` instead. See Open questions 10.

## Shapes found

### H01 · sh_4d09f351 · 93 messages · HDFCBK, HDFCBN

```
Sent {AMOUNT}
From HDFC Bank A/C {ACCT}
To {PARTY}
On {DATE}
Ref {REF}
Not You?
Call {PHONE}/SMS BLOCK UPI to {PHONE}
```

- **Type:** debit · **Channel:** upi
- **Fields:** amount, account_last4, counterparty_raw (`To` line), date
  (dd/mm/yy, no time), reference (12-digit UPI RRN).
- **Notes:** The most common shape by far, from both sender IDs. The `To`
  line can hold several words, digits, or a wallet name (wallet top-ups). No
  balance. Date only, so `txn_time_utc` is null.

### H02 · sh_6159ada2 · 22 messages · HDFCBK

```
Credit Alert!
{AMOUNT} credited to HDFC Bank A/c {ACCT} on {DATE} from VPA {VPA} (UPI {REF})
```

- **Type:** credit · **Channel:** upi
- **Fields:** amount, account_last4, date (dd-mm-yy), counterparty_raw = the
  VPA, reference.
- **Notes:** No payer name, only the VPA. HDFC sometimes masks the VPA itself
  (`*` plus a few characters before `@`). Date only.

### H03 · sh_abd519ff · 4 messages · HDFCBK

```
Spent {AMOUNT} From {PARTY} At {PARTY} On {DATE}:{TIME} Bal {BAL} Not You? Call {PHONE}/SMS BLOCK DC {ACCT} to {PHONE}
```

- **Type:** debit · **Channel:** debit_card
- **Fields:** amount, account_last4 (card last 4, from `DC {ACCT}`),
  counterparty_raw (`At` text), txn_time (yyyy-mm-dd:HH:MM:SS, IST),
  balance (account balance after the spend).
- **Notes:** Amounts may have no decimals. The first `{PARTY}` is the card
  label (redaction artifact). Merchant text may contain ` * ` followed by
  more descriptor text. International spends also arrive in this shape, in INR,
  together with H04.

### H04 · sh_1aaf7a69 · 4 messages · HDFCBK

```
Notice!
{NUM}. Forex Markup fee applies to your HDFC Bank Debit Card International payment
{NUM}. Final txn amount may change based on forex rate on the settlement date
```

- **Type:** foreign_currency (deferred)
- **Fields:** none.
- **Notes:** Companion notice to an international debit card spend (H03).
  Not a transaction. Foreign-currency handling is deferred.

### H05 · sh_bbcdf74e · 2 messages · HDFCBK

```
Payment Successful! {AMOUNT} from A/c {ACCT} to {PARTY} via HDFC Bank NetBanking. Not you?Call {PHONE}
```

- **Type:** debit · **Channel:** netbanking
- **Fields:** amount (`Rs. ` with a space), account_last4 (mask of many `*`),
  counterparty_raw (payee or biller).
- **Notes:** No date, no reference, no balance. Time comes from `received_at`.

### H06 · sh_2c4c888b · 1 message · HDFCBK

```
Amt Deducted!
{AMOUNT} from your HDFC Bank A/c {ACCT} for Money Transfer via HDFC Bank Online Banking.
Not you?Call {PHONE}/SMS BLOCK OB to {PHONE}
```

- **Type:** debit · **Channel:** netbanking
- **Fields:** amount, account_last4.
- **Notes:** No payee, date or reference. Likely a fund transfer
  (IMPS/NEFT/own account); see Open questions 1.

### H07 · sh_844eba4b · 1 message · HDFCBK

```
HDFC Bank: You have successfully set the UPI Pin for your HDFC Bank A/c No. {ACCT}. Not You? Call {PHONE} or SMS BLOCK UPI to {PHONE}
```

- **Type:** other_info (security event)
- **Fields:** account_last4 only.
- **Notes:** Not a transaction. Could feed a future security log.

### H08 · sh_d43a0170 · 1 message · HDFCBK

```
AutoPay (E-mandate) Success!
For {PARTY}
Txn Amt:{AMOUNT}
Dt:{DATE}
Via:HDFC Bank DC {ACCT}
SI Hub ID: {REF}
TnC
```

- **Type:** debit · **Channel:** e_mandate
- **Fields:** amount (`INR` with no space), counterparty_raw (`For` line),
  date (dd/mm/yyyy), account_last4 (debit card), reference (SI Hub ID,
  alphanumeric).
- **Notes:** Recurring card mandate executed. Variant of H13.

### H09 · sh_5791118d · 1 message · HDFCBK

```
Biometric {PARTY}! You have enabled your biometric {PARTY} for HDFC Bank App. Not you? Call {PHONE}
```

- **Type:** other_info (security event)
- **Fields:** none.
- **Notes:** `{PARTY}` here is a fixed word hit by redaction.

### H10 · sh_25c299ba · 1 message · HDFCBK

```
Transaction Reversed!On HDFC Bank DEBIT/ATM Card {ACCT} Amt: {AMOUNT} By {PARTY} On {DATE}:{TIME}
```

- **Type:** refund · **Channel:** debit_card
- **Fields:** amount, account_last4 (card), counterparty_raw, txn_time.
- **Notes:** The `By` text is merchant name, then `* `, then a merchant
  transaction ID; split on `* ` into counterparty_raw and reference. No space
  after `Reversed!`. Should be linked to the original spend (Open questions 3).

### H11 · sh_7c3c7508 · 1 message · HDFCBK

```
Withdrawn {AMOUNT} From {PARTY} At {PARTY} On {DATE}:{TIME} Bal {BAL} Not You? Call {PHONE}/SMS BLOCK DC {ACCT} to {PHONE}
```

- **Type:** debit · **Channel:** atm
- **Fields:** amount, account_last4 (card), counterparty_raw (ATM location or
  ID), txn_time, balance.
- **Notes:** Same layout as H03 with `Withdrawn`. Cash withdrawal: spend
  category is "cash", not a merchant.

### H12 · sh_b5411ded · 1 message · HDFCBK

```
Alert:
{AMOUNT} will be debited on {DATE} from {PARTY} {NUM} for {PARTY}
ID:{REF}
Act:{URL}
```

- **Type:** mandate (pre-debit notification)
- **Fields:** amount (`INR.` with a dot), future date (dd/mm/yyyy), card last
  4 (`{NUM}`), counterparty_raw (`for` text), reference (mandate ID).
- **Notes:** Announces a future autopay debit; must not create a
  transaction. The matching H08/H13 message is the real debit.

### H13 · sh_6a2cfbb1 · 1 message · HDFCBK

```
AutoPay (E-mandate) Success!
For {PARTY}
Txn Amt:{AMOUNT}
Dt:{DATE}
Via:HDFC Bank DC {ACCT}
Mandate ID: {REF}
Not You? To Block+Reissue Call {PHONE}/SMS BLOCK DC {ACCT} to {PHONE}
```

- **Type:** debit · **Channel:** e_mandate
- **Fields:** as H08; reference label is `Mandate ID`.
- **Notes:** Newer variant of H08.

### H14 · sh_5208991c · 1 message · HDFCBK

```
HDFCBANK UPDATE: Your FD No {ACCT} has been pre maturely liquidated for {AMOUNT} on {DATE}
```

- **Type:** other_info (provisional; see Open questions 7)
- **Fields:** amount (`INR ` with commas), FD last 4, date (dd-MON-yyyy).
- **Notes:** Fixed deposit closed early. The money lands in the savings
  account; whether a separate credit SMS follows is unknown.

### H15 · sh_b34b84f1 · 1 message · HDFCBK

```
Mandate Set
{AMOUNT}
For {PARTY}
From HDFC Bank A/c {ACCT}
UMN: {REF}
Not you?
Call {PHONE}
```

- **Type:** mandate (UPI AutoPay setup)
- **Fields:** amount (mandate limit or first charge), counterparty_raw,
  account_last4 (`x` plus 4), reference (UMN, VPA-like).
- **Notes:** Setup only, no money moves.

## Summary

| Type             | Shapes | Messages |
| ---------------- | -----: | -------: |
| debit            |      7 |      103 |
| credit           |      1 |       22 |
| refund           |      1 |        1 |
| mandate          |      2 |        2 |
| foreign_currency |      1 |        4 |
| other_info       |      3 |        3 |
| collect_request  |      0 |        0 |
| card_alert       |      0 |        0 |
| balance_info     |      0 |        0 |
| fraud_warning    |      0 |        0 |
| **Total**        | **15** |  **135** |

Debit shapes: H01, H03, H05, H06, H08, H11, H13. Other info: H07, H09, H14.

## Open questions

1. **Self-transfers.** UPI `Sent` (H01), NetBanking (H05) and `Amt Deducted`
   (H06) can move money to the user's own account at another bank, or top up
   a wallet. Count as transfers, not spending? Needs a list of own accounts
   and wallets.
2. **Card bill payments.** Paying a credit card bill from savings is a
   transfer; the card spends are the real expenses. Avoid double counting
   once credit card SMS arrive.
3. **Reversals.** H10 has no UPI/bank reference, only a merchant transaction
   ID. Link to the original H03 spend by card, amount, merchant and time?
   And is a reversal a `refund` (counted against spending) or an undo
   (both hidden)?
4. **Autopay double messages.** Does an H08/H13 autopay debit also produce an
   H03 card `Spent` message? If yes, dedupe across shapes.
5. **Pre-debit notices.** H12 should not create a transaction. Store it to
   predict upcoming debits, or ignore?
6. **Date-only messages.** H01, H02, H08, H13 carry a date but no time. Fixtures
   use `txn_time_utc: null`; the parser keeps the date and falls back to
   `received_at` for the time. Agree?
7. **FD liquidation (H14).** Treat as a credit into savings, or info only
   (if a separate credit SMS also arrives)?
8. **Counterparty for UPI credits.** Only a VPA is available (H02), often
   masked by HDFC. Is the VPA enough as `counterparty_raw`?
9. **International card spends.** H03 shows INR, plus an H04 notice; the final
   amount can change at settlement. Treat as provisional?
10. **Redaction over-reach.** Fixed words (card label, "authentication",
    the URL scheme) were pseudonymised. Add them to the keep-list or stop
    words in a later redaction task, so future surveys see the real wording.

## Not yet seen

Common HDFC formats absent from this sample. Each has one fixture with fake
values; the shapes below are expected forms, not observed ones.

| Format                       | Expected type    | Expected shape (approximate)                                                                 |
| ---------------------------- | ---------------- | -------------------------------------------------------------------------------------------- |
| Credit card spend            | debit            | `Spent {AMOUNT} On HDFC Bank Card {ACCT} At {PARTY} On {DATE}:{TIME} Not You? ...`             |
| Credit card payment received | credit           | `PAYMENT OF {AMOUNT} RECEIVED TOWARDS YOUR CREDIT CARD ENDING {ACCT} ON {DATE}...`            |
| NEFT credit (salary)         | credit           | `Update! INR {AMOUNT} deposited in HDFC Bank A/c {ACCT} on {DATE} for NEFT Cr-{REF}-{PARTY}... Avl bal INR {BAL}` |
| IMPS credit                  | credit           | `{AMOUNT} credited to a/c {ACCT} on {DATE} by a/c linked to mobile {PHONE} (IMPS Ref No. {REF})` |
| IMPS debit                   | debit            | `IMPS of {AMOUNT} sent from A/c {ACCT} to {PARTY} on {DATE}. Ref {REF}`                       |
| EMI / loan debit             | debit            | `EMI of {AMOUNT} for Loan A/c {ACCT} has been debited from your HDFC Bank A/c {ACCT} on {DATE}` |
| NACH debit                   | debit            | `{AMOUNT} debited from A/c {ACCT} on {DATE} towards ACH D- {PARTY}-{REF}. Avl bal {BAL}`        |
| UPI refund credit            | refund           | `{AMOUNT} refund credited to HDFC Bank A/c {ACCT} from {PARTY} on {DATE} (UPI Ref {REF})`     |
| Cash deposit                 | credit           | `Cash deposit of {AMOUNT} in A/c {ACCT} on {DATE} at {PARTY}. Avl bal {BAL}`                  |
| UPI collect request          | collect_request  | `{PARTY} has requested money from you ... {AMOUNT} will be debited ... Collect ID: {REF}`     |
| Balance enquiry              | balance_info     | `Available Bal in HDFC Bank A/c {ACCT} as on {DATE} is {BAL}`                                 |
| Declined card transaction    | card_alert       | `Transaction of {AMOUNT} on HDFC Bank Card {ACCT} at {PARTY} declined ...`                     |
| Fraud advisory               | fraud_warning    | `HDFC Bank never asks for OTP, PIN or card details ...`                                       |
| Foreign currency card spend  | foreign_currency | `Spent {CURRENCY} {AMOUNT} On HDFC Bank Card {ACCT} At {PARTY} On {DATE}:{TIME} ...`           |
