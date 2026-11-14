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
`txn_time_utc`, `time_inferred`. Channel values: `upi`, `netbanking`,
`debit_card`, `atm`, `credit_card`, `e_mandate`, `nach`, `neft`, `imps`,
`emi`, `cash`, `fd`.

**Time convention.** For money types (debit, credit, refund) `txn_time_utc`
is always set: the message's own date and time converted from IST, or, when
the message has no time, `received_at` with `time_inferred: true`. For all
other types both are null.

> **Re-survey (14 Nov 2026, refreshed sample, `--verify` Leaks: 0).** Same
> 135 messages and 15 shapes. H03, H11 and H12 now show the real card label
> ("HDFC Bank Card x{ACCT}" / "HDFC Bank Card {ACCT}") and got new shape ids.
> H09 still shows `{PARTY}` in its word slot: the word there is in the private
> name map and is not "authentication". The parser accepts any single word
> in that slot, so it does not matter for parsing. Each shape's parser
> template has the same id (H01...) in `backend/app/engine/parsers/hdfc.py`.

> **Full-data run (14 Nov 2026, 764 HDFC messages).** hdfc-1.0.0 parsed
> 683, deferred 44 as foreign currency and left 37 as `no_template`. Six of
> the unmatched shapes (15 messages) became H16-H21 (hdfc-1.1.0). The rest,
> reported as 25 shapes, were all amount-free notices (UPI activated, card limits, welcome kit, KYC, login
> alerts, FD booked or renewed, payee added, device registration); they now
> take the `H_INFO` fallback below instead of getting one template each.
> Shapes H16-H21 came from the user's local run; shape ids were not recorded.

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
  balance. Date only: `txn_time_utc` = `received_at`, `time_inferred: true`.

### H02 · sh_6159ada2 · 22 messages · HDFCBK

```
Credit Alert!
{AMOUNT} credited to HDFC Bank A/c {ACCT} on {DATE} from VPA {VPA} (UPI {REF})
```

- **Type:** credit · **Channel:** upi
- **Fields:** amount, account_last4, date (dd-mm-yy), counterparty_raw = the
  VPA, reference.
- **Notes:** No payer name, only the VPA. HDFC sometimes masks the VPA itself
  (`*` plus a few characters before `@`). Date only (time inferred).

### H03 · sh_5c7a7a9b · 4 messages · HDFCBK

```
Spent {AMOUNT} From HDFC Bank Card {ACCT} At {PARTY} On {DATE}:{TIME} Bal {BAL} Not You? Call {PHONE}/SMS BLOCK DC {ACCT} to {PHONE}
```

- **Type:** debit · **Channel:** debit_card
- **Fields:** amount, account_last4 (card last 4),
  counterparty_raw (`At` text), txn_time (yyyy-mm-dd:HH:MM:SS, IST),
  balance (account balance after the spend).
- **Notes:** Amounts may have no decimals. The card's last 4 appears twice
  (`x{ACCT}` and `DC {ACCT}`, often with two spaces after `DC`); the parser
  checks they agree. Merchant text may contain ` * ` followed by
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
- **Notes:** `{PARTY}` is a fixed word that the private name map still
  replaces (not "authentication"). The template accepts any single word.

### H10 · sh_25c299ba · 1 message · HDFCBK

```
Transaction Reversed!On HDFC Bank DEBIT/ATM Card {ACCT} Amt: {AMOUNT} By {PARTY} On {DATE}:{TIME}
```

- **Type:** refund · **Channel:** debit_card
- **Fields:** amount, account_last4 (card), counterparty_raw, txn_time.
- **Notes:** The `By` text is merchant name, then `* `, then a merchant
  transaction ID; split on `* ` into counterparty_raw and reference. No space
  after `Reversed!`. Should be linked to the original spend (Open questions 3).

### H11 · sh_edf2c444 · 1 message · HDFCBK

```
Withdrawn {AMOUNT} From HDFC Bank Card {ACCT} At {PARTY} On {DATE}:{TIME} Bal {BAL} Not You? Call {PHONE}/SMS BLOCK DC {ACCT} to {PHONE}
```

- **Type:** debit · **Channel:** atm
- **Fields:** amount, account_last4 (card), counterparty_raw (ATM location or
  ID), txn_time, balance.
- **Notes:** Same layout as H03 with `Withdrawn`. Cash withdrawal: spend
  category is "cash", not a merchant.

### H12 · sh_9ca903ac · 1 message · HDFCBK

```
Alert:
{AMOUNT} will be debited on {DATE} from HDFC Bank Card {ACCT} for {PARTY}
ID:{REF}
Act:{URL}
```

- **Type:** upcoming_debit (pre-debit notification; not money)
- **Fields:** amount (`INR.` with a dot), future date (dd/mm/yyyy), card last
  4 (`{ACCT}`), counterparty_raw (`for` text), reference (mandate ID). The
  link after `Act:` is not stored.
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

- **Type:** credit · **Channel:** fd (Reconcile treats it as own money
  moving, not income)
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

### H16 · full data · 4 messages

```
Amt Deducted!
{AMOUNT} from your HDFC Bank A/c {ACCT} for NEFT transaction via HDFC Bank Online Banking
Not you?Call {PHONE}/SMS BLOCK OB to {PHONE}
```

- **Type:** debit · **Channel:** neft
- **Fields:** amount, account_last4. No payee, no date (time inferred).
- **Notes:** Same family as H06 ("Money Transfer").

### H17 · full data · 2 messages

```
UPI Mandate:
Sent {AMOUNT}
from HDFC Bank A/c {NUM}
To {PARTY}
{DATE}
Ref {REF}
Not You? Call {PHONE}/SMS BLOCK UPI to {PHONE}
```

- **Type:** debit · **Channel:** upi · **Hint:** `autopay`
- **Fields:** amount, account_last4 (last 4 digits of the plain account
  number), counterparty_raw, reference, date (validated; time inferred).
- **Notes:** A UPI AutoPay charge executed under a mandate (compare H15).

### H18 · full data · 3 messages

```
AutoPay Active!
For {PARTY}
Starting:{DATE}
Mandate ID:{REF}
On HDFC Bank Card {ACCT}
Manage: {URL}
TnC
```

- **Type:** mandate · **Channel:** e_mandate
- **Fields:** counterparty_raw, reference (mandate ID), card last 4, start
  date (validated). No amount.
- **Notes:** Card AutoPay set up; charges arrive later as H08 or H13.

### H19 · full data · 2 messages

```
Update:
{AMOUNT} UPI mandate to {PARTY} has been cancelled from HDFC Bank A/c {ACCT}.
UMN: {REF}
```

- **Type:** mandate · **Channel:** upi · **Hint:** `mandate_cancelled`
- **Fields:** amount (mandate limit), counterparty_raw, account_last4,
  reference (UMN).
- **Notes:** No money moves. Reconcile closes the H15 mandate with this UMN.

### H20 · full data · 3 messages

```
Alert!
Your FD No.{ACCT} is prematurely liquidated and funds are transferred to your HDFC Bank A/c {ACCT}.
Not you?Call {PHONE}
```

- **Type:** other_info · **Channel:** fd · **Hint:** `fd_closure`
- **Fields:** account_last4 is the FD number (as in H14). No amount.
- **Notes:** Info only; the money is in H14 or a separate credit SMS.

### H21 · full data · 1 message

```
HDFC Bank MF a/c - {ACCT}. You have placed a SUBSCRIPTION order in {PARTY} for {AMOUNT} on {DATE}.
```

- **Type:** other_info · **Hint:** `mf_order`
- **Fields:** amount, account_last4 (MF account), counterparty_raw (fund),
  date (validated).
- **Notes:** Order only, not a debit. Investments are Phase 6.

### H_INFO · fallback · remaining notices in full data

No pattern. Any HDFC message that matches no template above and contains no
amount (Rs, INR, ₹, or a foreign currency code followed by a number) parses
as `other_info` with `template_id` `H_INFO` and no fields. A message with an
amount never takes this path; it stays `Unknown("no_template")`. Fixtures:
three invented notices (UPI activated, card limit, login alert).

## Summary

| Type             | Shapes | Messages |
| ---------------- | -----: | -------: |
| debit            |      7 |      103 |
| credit           |      2 |       23 |
| refund           |      1 |        1 |
| mandate          |      1 |        1 |
| upcoming_debit   |      1 |        1 |
| foreign_currency |      1 |        4 |
| other_info       |      2 |        2 |
| collect_request  |      0 |        0 |
| card_alert       |      0 |        0 |
| balance_info     |      0 |        0 |
| fraud_warning    |      0 |        0 |
| **Total**        | **15** |  **135** |

Debit: H01, H03, H05, H06, H08, H11, H13. Credit: H02, H14. Mandate: H15.
Upcoming debit: H12. Other info: H07, H09. (Sample counts above.)

Added from the full-data run: debit H16, H17; mandate H18, H19; other info
H20, H21 and the `H_INFO` fallback.

## Open questions (all resolved 14 Nov 2026, see Resolved)

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

## Resolved

Principle: **the parser reports only what one message says.** Transfers,
card bill payments, refund linking and cross-message duplicates need other
messages and the user's own accounts, so they are decided in the Reconcile
stage (Phase 2-3).

| # | Question | Decision |
| - | -------- | -------- |
| 1 | Self-transfers | Become transfers, not spending. Reconcile decides, using a user "my accounts and UPI IDs" list. The parser just reports the debit. |
| 2 | Card bill payments | Transfers, so card spends are not counted twice. Reconcile decides; the parser sets a hint when the wording says it is a card payment. |
| 3 | Reversals | Refund linked to the original spend (same card last 4, same amount, within a few days). Unmatched: standalone refund. Reconcile. |
| 4 | AutoPay success + card "Spent" | Possible duplicate; both are parsed, merged in Phase 2. |
| 5 | Pre-debit notice | Type `upcoming_debit`, not money. Stored later for month-end forecasts (Phase 6). |
| 6 | Date without time | `txn_time_utc` = `received_at`, with `time_inferred: true`. |
| 7 | FD closed early | `credit` with channel `fd`; Reconcile treats it as an own-money transfer in, not income. |
| 8 | Masked UPI ID as only counterparty | Acceptable for now; quick-tagging lets the user name it later. |
| 9 | International card spends | Deferred with `foreign_currency`. |
| 10 | Bank words redacted | Fixed in prompt 1b (`BANK_VOCABULARY`, link paths faked). Re-surveyed: H03, H11, H12 show the real wording; H09's word slot is still mapped (harmless for parsing). |

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
