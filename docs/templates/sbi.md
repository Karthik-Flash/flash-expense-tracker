# SBI SMS templates

Survey of SBI senders (cores `SBIUPI`, `CBSSBI`, `SBIBNK`, `SBIINB`, `SBIPSG`,
`SBYONO`) in the redacted sample (21 Nov 2026): **110 messages, 61 shapes**.
`sbi-1.0.0` reads 53 with 14 templates; 55 are refused with a reason; 2 stay
"not counted yet". Before it, the generic parser read 24, left 34 unsure and
refused 52.

This file holds shapes only. Payer and company names in the sample are written
here as `{PARTY}`. Fixtures with fake values:
`backend/tests/fixtures/sms/sbi.json` (one per template). Placeholders as in
[hdfc.md](hdfc.md); `{NUM}` here is also an amount SBI writes with no currency
mark.

## Money templates (`backend/app/engine/parsers/sbi.py`)

| Id | Messages | Type, channel | Shape |
| --- | ---: | --- | --- |
| S01 | 16 | debit, upi | `Dear UPI user A/C {ACCT} debited by {NUM} on date {DATE} trf to {PARTY} Refno {REF} If not u? call-...-SBI` (also with "." before "If", and "call {ACCT}. -SBI") |
| S02 | 12 | credit, upi | `Dear SBI User, your A/c {ACCT}-credited by {AMOUNT} on {DATE} transfer from {PARTY} Ref No {REF} -SBI` |
| S03 | 3 | debit | `Dear Customer, Your A/C {ACCT} has a debit by transfer of {AMOUNT} on {DATE}. Avl Bal {BAL}.-SBI` |
| S04 | 1 | credit | `Dear Customer, Your A/C {ACCT} has a credit by Transfer of {AMOUNT} on {DATE} by {PARTY}. Avl Bal {BAL}.-SBI` |
| S05 | 5 | credit | `Dear Customer,Your A/C {ACCT} has a credit by {PARTY} of {AMOUNT} on {DATE}. Avl Bal {BAL}. Download YONO-SBI` (dividends, ACH credits) |
| S06 | 2 | credit, upi | `Your A/C {ACCT} has credit for UPI/{NUM}/{ACCT}/{NUM} of {AMOUNT} on {DATE}. Avl Bal {BAL}.-SBI` (the UPI path is the reference) |
| S07 | 3 | **debit**, neft | `Dear Customer, Your NEFT of {AMOUNT} with UTR {REF} DTD {DATE} credited to Beneficiary AC NO. {ACCT} at {PARTY} on {DATE} at {TIME} PM.-SBI` (money sent: the generic parser read it as a credit) |
| S08 | 2 | credit | `Your A/C {ACCT} Credited {AMOUNT} on {DATE} -Deposit by transfer from Mr. {PARTY}. Avl Bal {BAL}-SBI` |
| S09 | 1 | debit | `Your AC {ACCT} Debited {AMOUNT} on {DATE} -{PARTY}. Avl Bal {BAL}.-SBI` (a charge) |
| S10 | 1 | credit, imps | `Dear Customer, Your a/c no. {ACCT} is credited by {AMOUNT} on {DATE} by a/c linked to mobile {NUM}-{PARTY} (IMPS Ref no {REF}).If not done by you, call {ACCT}. -SBI` |
| S11 | 4 | credit, neft | `Dear Customer, {AMOUNT} credited to your A/c No {ACCT} on {DATE} through NEFT with UTR {REF} by {PARTY}, INFO: ...-SBI` |
| S12 | 1 | debit, imps | `Dear Customer, Your a/c no. {ACCT} is debited for {AMOUNT} on {DATE} and a/c {ACCT} credited (IMPS Ref no {REF}). -SBI` |
| S13 | 1 | debit, netbanking | `Dear Customer, Thx for INB txn of {AMOUNT} frm A/c {ACCT} ref# {REF} on {DATE}. If not done, fwd ... -SBI` |
| S14 | 1 | debit, netbanking | `Dear Customer, SBCollect Txn {REF} dtd {NUM} {AMOUNT} for {PARTY} is successful. -SBI` |

The counterparty is only what an explicit slot holds ("trf to", "transfer
from", "by", "credit by"); S03, S06, S07 and S12 have none. The account is the
masked number of the owner's own account; S07 and S14 name none.

## Refused (not a payment) and unsure

| Reason | Messages | What |
| --- | ---: | --- |
| `other` | 26 | Fraud and safety alerts, branch notices, profile and address changes, interest-rate notices, messages in Kannada and Hindi |
| `hold` | 14 | "hold for {AMOUNT} created in deposit Ac ..." and "... has been removed" (a lien, no money moved) |
| `promo` | 6 | Card offers and campaigns |
| `mandate_notice` | 5 | UPI mandates created or revoked, an AutoPay "is scheduled" |
| `deposit_notice` | 3 | "TDR/STDR No ... for {AMOUNT} has been created" |
| `failed` | 1 | A mandate cancelled |
| unsure `no_template` | 2 | "Amount of {AMOUNT} disbursed from SBI Loan A/c No {ACCT} ... For {PARTY}" (who received it is not clear) |

No SBI debit or credit card message is in the sample. Until one is, a card
message is "not counted yet" (`card_no_template`), never read as the other
card.
