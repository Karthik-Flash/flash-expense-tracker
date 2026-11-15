# Phase 3 backbone: derived data and Reconcile

Design for task 3C-1 (15 Nov 2026). **Approved by the planner on 15 Nov 2026**
with the decisions in section I (D-059 to D-067). It is built in steps 3C-2
to 3C-8 (section H); NOTES.md says which steps are done. It covers
how every derived result (merchant, role, links, later category) is stored and
recomputed, and the full Reconcile design inside that. Fixed points it does
not reopen: D-001, D-002, D-046, D-055 to D-058, and the planner's list in the
3C-1 task.

Marks: **[A1]** ... **[A12]** are assumptions about real data that the
redacted sample cannot confirm (table in section 1). Section I lists the
questions (Q1 ...) and conflicts (C1 ...) the draft raised, each with the
planner's decision.

## 0. The design in short

Four ideas carry everything else.

1. **Derived data is one function.** `derived = f(active transactions, owner
   data, engine versions)`. One command recomputes all of it, every time, in
   memory, and writes only what changed. There is no incremental state to
   get out of step.
2. **Own evidence decides a role; a pair only links.** A transaction's role
   changes automatically only on evidence that transaction carries itself:
   its wording (type, channel, hint) or a text the owner listed. Two
   transactions that merely fit together (same amount, close in time) become
   a candidate for the owner. Two named exceptions, both needing a *unique*
   pair: AutoPay + card spend (B1), and the second leg of a self-transfer
   whose first leg names the very account the second leg is on (B2).
3. **A guess never lowers Net.** An unexplained debit is spend. An
   unexplained credit is `uncertain` and reduces nothing. An open candidate
   changes no role. So every error from missing information overstates
   spending, and the owner's review can only bring it down.
4. **Owner data stores the owner's words, never engine keys.** The owner says
   "this text is my SBI account" or "transaction 101 and 102 are the same".
   Merchant keys are worked out from those texts on every run, so a change
   to the key rules needs no migration of owner data.

## 1. Facts and assumptions

Counts only. Sample = `data/sample/redacted_sample.json` run through the
engine in memory. Real = the owner's import of 14 Nov (NOTES.md).

| Fact | Sample | Real |
| ---- | -----: | ---: |
| Active transactions | 127 | 678 |
| Debit / credit / refund | 103 / 23 / 1 | 539 / 134 / 5 |
| Time taken from the SMS arrival (`time_inferred`) | 121 of 127 | not known |
| With a reference | 118 | not known |
| Distinct `account_last4` | 3: one for UPI and NetBanking, one for all card channels, one FD | not known |
| Open duplicate candidates (10 min rule) | 0 | 18 |
| AutoPay successes; with a same-amount card spend within 3 days | 2; 0 | not known |
| Refunds; with a same-amount debit on that card in the 90 days before | 1; 0 | 5; not known |
| Refund messages merged on one dedupe key | 0 | 1 |
| FD closure credits | 1 | not known |
| UPI credits by merchant result: consumer handle / mobile UPI ID / unsure | 19 / 2 / 1 | not known |
| Merchant keys on credits that also appear on debits | 0 of 19 | planner: "usually a name key on debits and a UPI key on credits" |
| A debit and a credit of the same amount within 10 min | 3 pairs | not known |
| Messages not in totals: foreign currency / no parser | 4 / 153 | 44 / 153 |

| | Assumption the sample cannot confirm | Used in |
| -- | ------------------------------------ | ------- |
| A1 | The AutoPay success SMS and the card "Spent" SMS for one charge arrive within 10 minutes of each other. The sample has 2 AutoPay messages and no partner for either. | B1 |
| A2 | Most of the 18 real candidates are AutoPay + card spend pairs (D-047 calls it the typical case). | B1 |
| A3 | An HDFC UPI reference is unique per payment, so two UPI transactions with different references are two payments. References in the sample are fakes. | B1 |
| A4 | A masked UPI ID keeps the end of its local part (hdfc.md H02). | B2 |
| A5 | A transfer between two of the owner's accounts shows both SMS within 24 hours. Only one account is in the data today. | B2 |
| A6 | Credit card SMS, when they come, parse as channel `credit_card`. N01 and N02 have never been seen. | B3 |
| A7 | A card bill is paid 20 to 50 days after the purchases it covers. | B3 |
| A8 | The purchase behind a refund is in the data, on the same card, at most 30 days earlier. The one sample refund has no partner. | B4 |
| A9 | H14 is the only money message for an FD closure; no second credit SMS follows (hdfc.md H14 says this is unknown). | B5 |
| A10 | UPI handles `okaxis`, `okhdfcbank`, `okicici`, `oksbi` belong to individuals. | B6 |
| A11 | The owner's own name, as it appears after "To" on a UPI debit, is stable text. | B2 |
| A12 | The SMS arrival time is close to the transaction time. | all windows |

## A. Roles

Every **active** transaction gets exactly one role on every run. Superseded
transactions get none. Messages that are not transactions (pre-debit notices,
mandates, foreign-currency and no-parser messages) get no role; they stay in
`parse_results` and appear as "not counted yet" counts.

| Role | Direction | Meaning | In which total |
| ---- | --------- | ------- | -------------- |
| `spend` | debit | Money spent: a shop, a person, cash from an ATM, anything not proven otherwise | Spent (+) |
| `card_bill_counted` | debit | Bill payment for a card whose purchases are not in the data | Spent (+) |
| `refund` | credit | Money returned for an earlier spend | Spent (-) |
| `payback` | credit | A person paying the owner back | Paid back (+) |
| `income` | credit | From an income source the owner named | Income (+) |
| `self_transfer` | either | Between the owner's own accounts or wallets | none |
| `card_bill_excluded` | either | Bill payment for a card whose purchases are in the data, either leg | none |
| `fd_move` | either | Money moving into or out of a fixed deposit | none |
| `duplicate` | either | A second message for an event already counted | none |
| `ignored` | either | The owner says this is not a real movement. Only the owner can set it | none |
| `uncertain` | credit | A credit the engine cannot place. Reduces nothing | none (counted as "uncertain credits") |

**Totals** for a date range (a calendar month in IST by default). Each
transaction counts in the range that holds its own `txn_time_utc`.

- Spent = sum(`spend`) + sum(`card_bill_counted`) - sum(`refund`)
- Paid back = sum(`payback`)
- Net = Spent - Paid back
- Income = sum(`income`)

A refund and a payback count in the month they arrive (D-060). A link to a
purchase never moves either.

Every role is kept with the **rule code** that decided it and its **basis**:
`engine` when the transaction's wording alone decided, `owner` when the
deciding rule read owner data (a listed text, a party or a decision).

**Why nothing is counted twice.**

1. One row per transaction (`txn_derived`, primary key `transaction_id`), so
   one role per transaction.
2. Each role feeds at most one total, with one fixed sign. The table above
   is the whole mapping.
3. The amount summed is always the transaction's own `amount_paise`. Links
   never move or split an amount.
4. A duplicate group has exactly one member with a counting role; the rest
   are `duplicate`.
5. Both legs of a self-transfer, tracked card bill or FD move have roles
   that feed no total.

So the roles partition the active transactions, and every total is a signed
sum over a subset of that partition (invariant I16).

## B. Reconcile rules

`RECONCILE_VERSION = "reconcile-1.1.0"`; bump on any change that can alter a
role or a link. All rules live in one pure module (`app/engine/reconcile.py`,
stdlib only, no database).

### B0. Shared pieces

- **Merchant** of a transaction: the 3B engine result, or the owner's party
  when the transaction's text belongs to one (section C). The owner's party
  wins for kind and display name.
- **Own text**: a counterparty text or UPI ID the owner listed under one of
  their accounts. A transaction *points at* an own account when its merchant
  key equals the key of one of that account's texts.
- **On an own account**: the transaction's (`bank`, `account_last4`) is
  listed under that account. A debit card's last 4 is listed under the bank
  account it draws on.
- **Compatible pair**: two transactions that meet a rule's match condition
  inside its window.
- **Unique pair**: a compatible pair where each side has no other compatible
  partner for that rule. Only a unique pair can ever be linked by a rule.
  There is no "closest in time wins" and no greedy matching: if a side has
  two possible partners, every pair in that cluster is a candidate. A pair
  the owner called the same counts as a partner; a pair the owner called
  different does not.
- **Link**: kind (`duplicate`, `self_transfer`, `refund`, `fd`), the two
  transaction ids (lower first), status, the rule, a reason code, and who
  decided (`engine` or `owner`).
- **Link status**: `linked` (applied) or `candidate` (waiting for the owner,
  changes no role and no total).
- **Owner decisions**: a *link decision* says "same" or "different" to one
  pair for one kind; a *role decision* fixes one transaction's role. Both
  always win, and a role decision wins over a link. A decision about a
  transaction that is not active is kept and not applied. A decision that
  cannot hold (two amounts called one duplicate, two debits called a
  transfer) is an error.

| Reason | Rule | Meaning |
| ------ | ---- | ------- |
| `unique_10min` | `DUP_autopay_card` | Linked: the only partner, inside 10 minutes |
| `within_24h` | `DUP_autopay_card` | Candidate: more than 10 minutes apart |
| `same_amount` | `DUP_same_amount` | Candidate |
| `different_references` | `DUP_same_amount` | Candidate: two different per-payment references |
| `recorded_at_import` | `DUP_legacy` | Candidate: recorded in `duplicate_candidates`, found by no rule now |
| `names_partner_account` | `ST_pair` | Linked: one leg names the account the other is on |
| `no_own_text` | `ST_pair` | Candidate: unique, but neither leg names the other's account |
| `same_merchant` | `RF_same_amount` | Linked |
| `different_merchant` | `RF_same_amount` | Candidate |
| `partial` | `RF_partial` | Candidate |
| `second_credit` | `FD_pair` | Candidate |
| `several_partners` | any rule that can link | Candidate: a side has more than one partner |
| `owner_same` | the rule that found the pair, or `OWNER_link` | Linked by the owner |

Windows compare `txn_time_utc`. For most messages that is the SMS arrival
time [A12], so windows are generous and uniqueness does the real work.

### B1. Cross-message duplicates (D-032, D-046, D-047)

Exact repeats are already one transaction (same dedupe key). This rule
handles two transactions that may be one event.

| | D1 `DUP_autopay_card` | D2 `DUP_same_amount` |
| -- | -- | -- |
| Inputs | Active debits | Active transactions |
| Match | Same bank, `account_last4` (both carry the card's last 4) and amount. One leg has channel `e_mandate` (AutoPay success, H08 or H13), the other `debit_card` or `credit_card`. If both merchants have a `brand_id`, the ids are equal | Same bank, `account_last4`, direction and amount (the D-047 rule), and not a D1 pair. This is the rule that recorded the existing candidates, so none can be lost (D-062). A pair whose two sides carry different per-payment references is probably two payments [A3]; it is still a candidate, marked `different_references` for the review and counted on its own stats line. A mandate ID (hint `mandate_reference`) is not a per-payment reference |
| Window | Linked: 10 minutes. Candidate: 24 hours. Ten minutes is what Phase 2 recorded the 18 pairs with [A1]; the AutoPay SMS carries only a date, so a late SMS is still shown to the owner up to a day | 10 minutes, as recorded in Phase 2 |
| Zero | Nothing | Nothing |
| One (unique pair) | **Linked** inside 10 minutes; candidate between 10 minutes and 24 hours | Candidate. Two equal payments minutes apart are common (two tickets, two coffees), so this is never automatic |
| Many | Every pair a candidate | Every pair a candidate |
| Stored | `txn_links` row, kind `duplicate`, with status and rule | same |

- **Group**: linked duplicate links form groups (connected sets). The
  **primary** is the member with the earliest `txn_time_utc`, then the lowest
  id (Q9: kept for now; step 3C-3 reports whether this choice changes the
  merchant shown for an AutoPay + card pair, and the planner decides
  then). It keeps its normal role. Every other member gets role
  `duplicate` and `duplicate_of` = the primary. Later rules look only at
  primaries.
- **Owner**: "same" on a pair links it (rule or not, as long as bank,
  direction and amount agree). "different" removes the pair for good: it is
  never proposed again, by a rule or from the import-time list. A rule
  links a pair only when neither side has another partner, and a pair the
  owner called the same counts as a partner. So a group that a rule built
  has exactly two members, and a larger group is the owner's own. Owner
  decisions that contradict each other (A same as B, B same as C, A
  different from C) are an error in the engine; the review command refuses
  such a decision before it is saved.
- **Counting partners for D1.** Every card spend inside the 24 hours
  counts. A pair is linked only when it is inside 10 minutes and neither
  side has another partner inside 24 hours.
- **References never match anything.** A shared mandate ID neither makes a
  pair nor prevents one; references only label a candidate.
- **The existing 18 candidates.** `duplicate_candidates` is frozen: import
  keeps recording into it for now, its `status` column is never written, and
  Reconcile does not read it for decisions (C1). Reconcile finds its own
  pairs from the transactions. Every open legacy pair between two active
  transactions must come out as linked or candidate (D-062); a test and a
  `reconcile-stats` line check that none is lost. The recorded pairs are an
  input of the derive, read-only: one that no rule finds any more (a
  reparse moved a time) comes out as a candidate under rule `DUP_legacy`.
- **Tests**: a table of pairs where changing one field at a time (bank,
  last 4, amount, direction, channel, minute 10 against minute 11, brand)
  flips the result; unique against many; a group of three; primary choice;
  owner "same" and "different"; contradicting decisions; legacy coverage; I15
  and I17.

### B2. Self-transfers (D-029)

| | S1 `ST_own_text` | S2 `ST_pair` | S3 `ST_masked` |
| -- | -- | -- | -- |
| Inputs | Any active transaction; the own-account list | Debits and credits on own accounts | Credits whose counterparty is a masked UPI ID |
| Match | The transaction points at an own account of kind `bank_account` or `wallet` | A debit on own account X and a credit on a different own account Y, same amount | The masked ID has the same handle as one of the owner's UPI IDs and its visible characters are the end of that ID's local part [A4] |
| Window | None: the evidence is in the one message | 24 hours: UPI and IMPS are instant, NEFT settles in half-hour batches, and a late SMS must still fit [A5] | None |
| Zero | Not a self-transfer by this rule | Nothing | Nothing |
| One | Role `self_transfer`. Needs no second leg | Unique pair where one leg points (S1) at the account the other leg is on: **linked**, and the partner takes `self_transfer` too. Any other unique pair: candidate | Role `uncertain`, listed for the owner. Never an automatic self-transfer (a mask can fit several people), and never an automatic payback either (idea 3) |
| Many | Does not apply | Every pair a candidate; a leg identified by S1 keeps its role | Same as one |
| Stored | Role and rule in `txn_derived` | `txn_links` row, kind `self_transfer` | Role and rule in `txn_derived`; the review lists it by its rule code |

- **Only one leg in the data** (the other bank has no parser, or its SMS is
  missing): S1 decides alone. A transfer to the owner's SBI account shows as
  an HDFC debit "To" the owner's own name [A11]; listing that name under the
  SBI account is enough. When the SBI parser arrives, its credit leg is
  picked up by S1 as well (it names the owner's HDFC UPI ID), and S2 links
  the two.
- **No payee at all** (H06 "Money Transfer", H16 NEFT): there is nothing for
  S1 to read. Without an identified partner the debit stays `spend` with rule
  `DB_no_counterparty` and is listed for the owner (Q3, D-060).
- **Wallets** (Q5, D-063): a top-up is a self-transfer only when the owner
  lists the wallet as an own account (kind `wallet`, with the text the
  top-up shows). A wallet that is not listed is spend at that wallet.
  Wallet spends never appear in bank SMS, so listing a wallet takes that
  money out of the totals; the owner chooses.
- **Owner**: a "same" link decision on a pair (one debit, one credit, equal
  amounts) makes both legs `self_transfer`; "different" removes the pair. A
  role decision works for a single leg.
- **Which legs S2 looks at.** A leg must be on a listed own bank account or
  wallet (bank and last 4), must not be a duplicate, and must be either
  identified by S1 or still unexplained: its role is the engine's default
  from wording alone (spend, payback, uncertain) or S3. A leg whose role
  the owner fixed, a credit from an owner party, a refund, an FD move and a
  card bill are never paired. A linked partner takes `self_transfer` with
  rule `ST_pair` and basis `owner`.
- **Tests**: text match by name and by UPI ID; text under a credit card or
  FD account does not give `self_transfer`; pair windows at 24 hours and
  just past; unique against many; a leg that names the partner's account
  carries the role, any other pair does not; a masked UPI ID that fits an
  own ID is `uncertain`, one that does not is untouched; one-leg case.

### B3. Card bill payments (D-030, D-055)

| | |
| -- | -- |
| Inputs | Active transactions; own accounts of kind `credit_card` |
| Credit leg `CB_hint` | A credit with hint `card_bill_payment` (N02, "payment received towards your credit card"). Always `card_bill_excluded`: money arriving on a card is never income or a payback |
| Debit leg `CB_own_text` | A debit that points at an own account of kind `credit_card` (the owner listed the biller text or UPI ID the bill is paid to) |
| Debit leg `CB_pair` | A debit on an own bank account and a hinted credit leg, same amount, within 3 days (a bill paid by NEFT or a biller can post the next working day). Unique pair with the debit already identified by `CB_own_text`: linked. Otherwise: candidate |
| Zero | A debit that matches nothing here is not a card bill; it stays `spend` |
| Many | Every pair a candidate. Roles from `CB_hint` and `CB_own_text` stand |
| Stored | Role and rule in `txn_derived`; `txn_links` rows of kind `card_bill` for pairs |
| Owner | Link decision for a pair; role decision to force `card_bill_counted` or `card_bill_excluded` |

**The D-055 test, exactly.** Let the payment be a debit leg at time T for own
card K. K's purchases are **tracked** when the data holds at least one active
transaction with direction debit, channel `credit_card`, K's bank, an
`account_last4` listed under K, and `txn_time_utc` in the 60 days up to T.
Tracked gives `card_bill_excluded`; not tracked gives `card_bill_counted`
(category "Card bill" in 3D).

- Why 60 days: a bill covers purchases from about 50 to 20 days before it is
  paid [A7]; 60 leaves slack. A card with no purchase in that time was not
  being tracked when the bill was paid (new card, lost SMS, no parser), so
  counting the bill is the safe side (idea 3).
- A card at a bank with no parser can have no purchases in the data, so its
  bill always counts. That is the D-055 intent.
- A debit card has no bill; this rule never looks at it.
- **Not built yet: `CB_pair`.** It never changes a role, and no credit card
  SMS has been seen [A6]. It is built when N01 or N02 appear, together
  with link kind `card_bill`.
- Today's data has no credit card SMS [A6], so on real data the only hits
  will be `CB_own_text` payments to cards at other banks, all counted.
- **Tests**: purchase 59 days before against 61; purchase on another card or
  bank; a duplicate purchase still proves tracking; credit leg always
  excluded; debit leg with and without the owner's text; pair unique against
  many.

### B4. Refund linking (D-031)

A transaction of type `refund` always has role `refund`, linked or not, so
linking never changes a total. The link says which purchase it belongs to,
for the category view in 3D.

| | |
| -- | -- |
| Inputs | Active refunds R; active debits P with a counting role, with P no later than R, on the same card or, for a refund to a bank account, on the same account (D-064). Both mean the same bank and `account_last4`. A debit card purchase refunded to its bank account carries two different last 4 values: that pair is never automatic, the owner links it |
| Full `RF_same_amount` | P and R have the same amount |
| Partial `RF_partial` | P is larger than R and both have the same merchant key |
| Window | 30 days before R. D-031 says "a few days"; card reversals often take one to two weeks and some a month [A8]. Totals do not depend on the window |
| Zero | Standalone refund (D-031). It still reduces Spent in its month |
| One, full | Same merchant key: **linked**. Different key: candidate |
| One, partial | Candidate. Amounts differ, so it is never automatic |
| Many | Every pair a candidate |
| Guard | The refunds linked to one purchase never add up to more than the purchase. A rule link cannot break this: it is a unique pair of equal amounts, and an owner link on the same purchase makes the rule's pair a candidate. Owner links that add up to more than the purchase are an error |
| Stored | `txn_links` row, kind `refund` |
| Owner | "same" links a refund to a purchase (a debit and a credit, the credit no larger). The owner may also link a plain credit to a purchase as its refund (a UPI refund that the bank worded as a credit): that credit then gets role `refund`. "different" removes the pair |

- **Uniqueness is per rule.** A full-amount pair is unique among full-amount
  pairs. A partial match is proposed only for a refund with no full-amount
  pair and no owner link, so one refund from a shop the owner uses every
  day does not produce a candidate for every larger purchase there.
- **The refund merged on its dedupe key.** Two refund messages carried the
  same bank, direction, amount and reference, so Phase 2 made them one
  transaction with two sources. Either the bank sent one reversal twice
  (correct) or there were two reversals (one refund is missing). Reconcile
  cannot tell and does not try: `reconcile-stats` counts transactions with
  two or more source messages, and the review shows them with both arrival
  times. If the owner says "two events", that is a dedupe fix, not an owner
  decision, and it needs a pipeline change first (C6).
- A refund whose purchase is older than the data stays standalone and
  lowers Spent for a spend that was never counted. Known limit.
- **Tests**: same amount with same and different merchant; day 30 against
  day 31; purchase after the refund never matches; two equal purchases give
  candidates; partial stays candidate; the guard; a refund pointing at a
  duplicate group links to its primary; owner-linked plain credit.

### B5. FD movements (D-036)

| | |
| -- | -- |
| `FD_channel` | A transaction with channel `fd` (H14, FD closed early) has role `fd_move`. The wording says so; no window |
| `FD_own_text` | A transaction that points at an own account of kind `fd` has role `fd_move` |
| `FD_pair` | An unexplained credit (its role is the engine's default from wording alone) with the same amount as an `FD_channel` credit, same bank, within 3 days: **candidate** only. The account need not be listed: every transaction in the data is on one of the owner's accounts. If a second credit SMS does follow a closure [A9], the owner confirms once and that credit becomes `fd_move` instead of an uncertain credit |
| Zero / many | No pair: nothing. Several: every pair a candidate |
| Stored | Role and rule; `txn_links` rows of kind `fd` for pairs |
| Owner | Link decision for a pair; role decision for a single transaction (for example the debit that opens an FD, which has no wording of its own today) |
| Tests | Channel `fd` is always `fd_move` and never income or payback; pair is never automatic; H20 (no amount, not a transaction) gets no role |

### B6. Paybacks, income and uncertain credits (D-055)

Applies to every credit that B1 to B5 left alone. First match wins.

| # | Credit | Role | Rule |
| - | ------ | ---- | ---- |
| 1 | Its text belongs to an owner party with an income label | `income` | `CR_income_party` |
| 2 | Its text belongs to an owner party of kind person | `payback` | `CR_person_party` |
| 3 | Engine merchant is `person` and its reasons include `R5_honorific`, `R5_mobile_vpa` or `R5_consumer_vpa` | `payback` | `CR_person_signal` |
| 4 | Engine merchant is `person` on `R5_person_name` alone | `uncertain` | `CR_name_only` |
| 5 | Merchant is `business` (engine or owner party) | `uncertain` | `CR_business` |
| 6 | Merchant is `unsure`, or there is no text | `uncertain` | `CR_unsure`, `CR_no_text` |

- **Why these reason codes.** A mobile-number UPI ID and a consumer handle
  both describe a personal UPI account [A10]; an honorific is written
  evidence. A person-shaped name alone is not enough: name-only credits
  arrive by NEFT and IMPS, where salary and company payments arrive too, and
  a company name of two plain words looks like a person. On the sample this
  gives 21 paybacks and 1 uncertain credit out of 22 UPI credits (Q1).
- **Basis** (D-061). Every payback records its basis: `owner` for rule 2,
  `engine` for rule 3. `reconcile-stats` counts engine-basis paybacks
  separately. Recompute and `reconcile-stats` print a warning line when the
  owner data lists no income party: until one is listed, pocket money or a
  salary sent from a personal UPI ID counts as a payback.
- **Income sources** are owner parties with an income label ("Pocket
  money", "Stipend", "Salary"). Rule 1 runs before the person rules, so a
  parent who is an income source is never a payback. Debits to the same
  party stay `spend`.
- **Uncertain credits** have role `uncertain`. They reduce nothing and are
  counted on the dashboard. The owner clears one by naming the sender as a
  party (person or income source), listing it as an own account, linking it
  to a purchase as a refund, or fixing that one transaction's role.
- **A credit from a business** that is not worded as a refund (cashback, a
  refund through UPI, an employer) is uncertain, not income (Q8).
- **Joining two keys into one person.** The join is a party with several
  texts: the name as it appears on debits and the UPI ID as it appears on
  credits. It is available as soon as owner parties exist (step 3C-4),
  because an income source already needs it: the same parent can pay by UPI
  and by NEFT. In 3C a join changes three things only: income detection, the
  display name, and the kind. What waits for Phase 6: the engine *suggesting*
  joins (a name that resembles a UPI ID is a guess), and per-person balances
  (lent against paid back).
- **Tests**: one row per rule above; income before payback; each reason code
  alone and combined; a business keyword blocks payback; a party overrides
  the engine in both directions; debit to an income source stays spend.

### B7. Order and conflicts

One run, in this order:

1. Merchant for every active transaction (3B engine, then owner parties).
2. Duplicate links and groups (B1). Non-primary members are done.
3. Roles from own evidence, first match wins:

   | # | Evidence | Role |
   | - | -------- | ---- |
   | 1 | Channel `fd`, or text of an own FD (B5) | `fd_move` |
   | 2 | Hint `card_bill_payment`, or text of an own credit card (B3) | credit: `card_bill_excluded`; debit: by the tracked test |
   | 3 | Text of an own bank account or wallet (B2 S1) | `self_transfer` |
   | 4 | Type `refund` (B4) | `refund` |
   | 5 | Credit with a masked UPI ID that fits an own UPI ID (B2 S3) | `uncertain` |
   | 6 | Credit rules (B6) | `income`, `payback` or `uncertain` |
   | 7 | Any other debit | `spend` |

   Rule codes for the rows that section B does not name: `RF_type` (row 4),
   `DB_spend` and `DB_no_counterparty` (row 7; the second is a debit with no
   counterparty text that is not an ATM withdrawal), `CR_own_account` (row
   6: a credit from a text of an own credit card or FD that no earlier row
   explains; `uncertain`), and `OWNER_role` (an owner role decision, step
   5). A mask with no visible character (row 5) fits every own UPI ID on
   that handle.

4. Pair passes (B2, B3, B5, then B4), each with the unique-pair rule. A pair
   carries a role to an unidentified partner in one case only: B2 S2.
5. Owner link decisions, then owner role decisions. These override
   everything above.

**Conflicts.**

- Two rules match one transaction: the earlier row wins. Every matching
  rule code is kept in `role_reasons`, and `reconcile-stats` counts such
  transactions.
- One transaction linked by rules of two different kinds cannot happen.
  Duplicates are settled first and only primaries go on; the transfer rule
  takes only legs that nothing else explains (B2); a purchase must still
  count as spend to take a refund (B4); `FD_pair` never links. One
  movement has one explanation.
- A transaction with two partners of the same kind: candidates (B0).
- One text listed in two places (two accounts, two parties, or an account
  and a party), or two texts that give the same merchant key in different
  places: `owner-load` rejects the file. If a later merchant version makes
  two stored texts collide, recompute stops without writing (section D).
- An owner decision about a superseded transaction: kept, not applied,
  counted as inactive. If reparse makes the transaction active again, the
  decision applies again.

## C. Storage

Nine new tables, in two groups that never mix. `duplicate_candidates` and
all Phase 2 tables stay as they are.

**Owner tables** (migration `0004`). Written only by owner commands, and
later by the app. Import, reparse and recompute never write them.

```
own_accounts          id, owner_id, label, kind, bank
                      kind in (bank_account, credit_card, wallet, fd)
                      UNIQUE (owner_id, label)
own_identifiers       id, owner_id, own_account_id -> own_accounts, kind, value
                      kind in (last4, text)
                      UNIQUE (owner_id, kind, value, own_account_id)
                      (the loader also rejects one text under two accounts;
                      the same last 4 may exist at two banks)
parties               id, owner_id, label, kind, income_label (null = not income)
                      kind in (person, business)
                      UNIQUE (owner_id, label)
party_texts           id, owner_id, party_id -> parties, text
                      UNIQUE (owner_id, text)
owner_link_decisions  id, owner_id, kind, txn_a -> transactions, txn_b -> transactions,
                      verdict, decided_at, source
                      kind in (duplicate, self_transfer, card_bill, refund, fd)
                      verdict in (same, different); source in (terminal, file, app)
                      (kind card_bill waits for CB_pair, B3)
                      UNIQUE (owner_id, kind, txn_a, txn_b); CHECK (txn_a < txn_b)
owner_roles           transaction_id -> transactions (primary key), owner_id, role,
                      decided_at, source
```

- Owner tables hold texts and transaction ids, **never merchant keys**
  (idea 4). Labels, texts and last 4 digits are private: database only,
  never printed, never in git or fixtures.
- A party is three things in one: a merchant correction (kind and display
  name), a join (several texts), and an income source (the label). 3D adds
  category corrections and labels (D-056) as further owner tables keyed on a
  party or a transaction id; nothing here changes.
- Decisions point at transaction ids, which stay stable across reparse.

**Derived tables** (migration `0005`). Written only by recompute. Deleting
every row and running recompute gives the same rows back.

```
derive_runs    id, owner_id, started_at, finished_at, status, trigger, versions, counts
               status in (running, done, failed)
               trigger in (import, reparse, owner, manual)
               versions JSON: {"merchant": "merchant-1.1.1", "reconcile": "reconcile-1.1.0"}
               counts JSON: counts only
txn_derived    transaction_id -> transactions (primary key), owner_id,
               merchant_key, merchant_kind, merchant_confidence, display_name,
               brand_id, party_id -> parties (null), merchant_reasons JSON,
               role, role_rule, role_basis, role_reasons JSON,
               duplicate_of -> transactions (null)
               CHECK role in (the eleven roles)
               CHECK role_basis in (engine, owner)
               CHECK (role = 'duplicate') = (duplicate_of IS NOT NULL)
txn_links      id, owner_id, kind, txn_a -> transactions, txn_b -> transactions,
               status, rule, reason, decided_by
               kind as in owner_link_decisions; status in (linked, candidate)
               decided_by in (engine, owner)
               UNIQUE (kind, txn_a, txn_b); CHECK (txn_a < txn_b)
```

- One `txn_derived` row per active transaction holds the merchant, the role
  and, from 3D, the category (three more columns in a later migration).
- **Versions are per run, not per row.** A run recomputes everything and
  commits together with its `derive_runs` row, so the derived tables always
  match the last `done` run and the versions written on it.
- Indexes: `txn_derived.role`, `txn_derived.merchant_key`,
  `txn_links (status, kind)`.

**Both migrations.** Additive only, so they are safe in Render's build step
(D-018). Order: `0004` owner tables, then `0005` derived tables (it refers to
`parties`). Row level security is enabled with no policies on all nine
tables on Postgres, exactly as in `0002`, and the RLS test's table list
grows by nine. Nothing is added to the `keepalive` schema (D-053). Types are
the ones `models.py` already uses on both databases (`BigId`, `String`,
`JSON`, `UtcDateTime`, `Uuid`, check constraints); no partial indexes.

## D. Recompute

```
python -m app.cli recompute [--dry-run] [--accept-key-changes]
```

1. **Read**, in a fixed number of queries: active transactions, the owner
   tables, the current derived rows.
2. **Derive** in memory with the pure function. Inputs are sorted by id; no
   clock, no randomness, so the same input gives the same output.
3. **Compare** with the stored rows and write only the difference (insert,
   update, delete), plus one `derive_runs` row, in one database transaction.
   A crash leaves the previous state whole.
4. **Print** counts only: versions, rows changed per table, roles, links,
   and a warning line when the owner data lists no income party (D-061).

A second run with nothing changed writes no derived row.

| Topic | Design |
| ----- | ------ |
| Triggers | `import-sms` and `reparse` run it as their last step (not on `--dry-run`). `owner-load` and `reconcile-review` run it after saving. The owner can run it by hand. It is never scheduled and never runs on a request |
| Runtime target | Today (678 active transactions): the pure derive under 0.5 s; the whole command under 10 s against Supabase from the owner's PC. The command uses about a dozen statements however many rows there are (the import's cost was round trips per message; this has none). Pair rules bucket by amount, so the work grows as n log n, not n squared; 50,000 transactions stay in seconds |
| Version bump | Nothing special. The next run recomputes everything and writes what changed. `stats` and the API report "derived data is stale" when the last done run's versions differ from the code, or when a transaction changed after that run started |
| Deploy | A deploy that bumps a version leaves derived data stale until the owner runs `recompute` (Q6, D-066). Revisit in Phase 5, when the server takes in SMS itself |
| Reparse | Transaction ids are stable, so decisions keep pointing at the right rows. A superseded transaction loses its derived row and its links; decisions about it stay, inactive |

**A change to the merchant key rules, once owner data exists.** Owner tables
hold texts, and every run works out each text's key with the current engine,
exactly as it does for transactions. (A key does not depend on the channel,
so a text needs none.) So there is nothing to migrate. What can still go
wrong is that a rule change **splits** texts that used to share a key (some
transactions lose their party) or **merges** texts that used to differ (two
parties now claim one key). Recompute handles both:

- It compares the party and own-account match of every transaction before
  and after. If any transaction would lose or change one because the
  merchant version changed, it prints the counts and stops without writing,
  unless `--accept-key-changes` is given. `--dry-run` shows the same counts.
- If two owner texts now give one key in different places, it stops without
  writing. The owner fixes the file.
- Rule for engine work: a change that alters the key of any fixture text is
  a MAJOR merchant version, and its task must include the owner's dry run.

This is the "migration plan" D-058 asks for, made into a check (C2).

## E. Invariants

Continuing after I9. Each gets a test of the same name.

| | Invariant |
| -- | --------- |
| I10 | Every active transaction has exactly one `txn_derived` row with exactly one role; a superseded transaction has none |
| I11 | Recompute twice: the second run changes no derived row |
| I12 | Derived data is a pure function of its input: deleting all derived rows and recomputing gives back the same rows |
| I13 | Import, reparse and recompute never change an owner table |
| I14 | The owner always wins: every active role decision equals the derived role; every "same" link decision is a linked link; no pair with a "different" decision is linked or a candidate |
| I15 | A duplicate group counts once: exactly one member has a role other than `duplicate`, and every other member points at it |
| I16 | Totals equal the sums over roles: for any date range the roles partition the active transactions, and Spent, Paid back, Net and Income equal the formulas in section A (checked against a second, naive implementation on seeded random data) |
| I17 | Ambiguity changes nothing: removing every candidate link leaves every role the same |
| I18 | Roles respect direction: `spend` and `card_bill_counted` only on debits; `refund`, `payback`, `income` and `uncertain` only on credits |
| I19 | Links are sound: a linked self-transfer, card bill or FD pair is one debit and one credit of equal amount; a transaction is in at most one such linked pair; refunds linked to a purchase never exceed it |
| I20 | Owner decisions survive reparse: after a parser version bump, reparse and recompute, every decision on a still-active transaction still holds, and none was deleted |
| I21 | Privacy (extends I9): `recompute`, `reconcile-stats` and `owner-load` print counts, ids and versions only, also on errors; `reconcile-review` refuses to run without a terminal |

## F. Owner input

**The file.** One JSON file the owner keeps at
`D:\FlashPrivate\private\owner.json`. Agents never read it. JSON because the
standard library reads and writes it, so the same shape works for a backup
(Q7, D-065). Fake values:

```json
{
  "accounts": [
    {"label": "HDFC savings", "kind": "bank_account", "bank": "HDFC",
     "last4": ["0001", "0002"],
     "texts": ["test.user@okhdfcbank"]},
    {"label": "SBI savings", "kind": "bank_account", "bank": "SBI",
     "last4": ["0003"],
     "texts": ["TEST OWNER", "test.user@oksbi"]},
    {"label": "Test credit card", "kind": "credit_card", "bank": "SBI",
     "last4": ["0004"],
     "texts": ["TEST CARD BILLER"]},
    {"label": "Test wallet", "kind": "wallet", "texts": ["TEST WALLET"]}
  ],
  "parties": [
    {"label": "Test Parent", "kind": "person", "income": "Pocket money",
     "texts": ["test.parent@okaxis", "TEST PARENT"]},
    {"label": "Test Friend", "kind": "person",
     "texts": ["PERSON_901", "9000000001@ybl"]},
    {"label": "Test Mess", "kind": "business", "texts": ["TEST FOODS 12"]}
  ],
  "decisions": [
    {"kind": "duplicate", "a": 101, "b": 102, "verdict": "same"},
    {"kind": "role", "transaction": 103, "role": "self_transfer"}
  ]
}
```

- `last4`: the account's last 4 and the last 4 of any debit card on it.
- `texts`: how this account or party appears as a counterparty, copied as
  the SMS shows it (a name or a UPI ID). Case, spacing and punctuation do
  not matter; the engine normalises them.
- `income`: present only for an income source.
- `decisions` is optional. The owner normally makes decisions in the
  terminal review; this section exists so a backup can be loaded.

**Commands.**

| Command | What it does |
| ------- | ------------ |
| `owner-load --input <file> [--dry-run]` | Checks the file, then makes the accounts and parties in the database equal to the file (matched by label, so unchanged entries keep their ids). Decisions in the file are added or updated, never removed. Then runs recompute. Loading the same file twice changes nothing. Prints counts only: accounts, identifiers, parties, texts, texts that match no transaction, decisions, derived rows changed. An error names the entry by position ("party 3: text listed twice"), never by value |
| `reconcile-review [--kind K] [--limit N]` | Owner only. Shows one candidate at a time with real details (date in IST, amount, counterparty, channel, rule) between two `PRIVATE: do not paste this into any chat or file.` lines, and asks: same, different, skip, quit. For an uncertain credit it asks for the role instead. Saves each answer as an owner decision and runs recompute at the end. **Refuses to run unless stdin and stdout are both a terminal**, with the same kind of message and exit code 2 as `merchant-review`. `K`: `duplicate`, `self_transfer`, `card_bill`, `refund`, `fd`, `uncertain_credit`, `no_payee`, `merged` (transactions with two or more source messages; display only) |
| `owner-export --output <file>` | Owner only. Writes every owner table in the file shape above, with each decision's transaction ids and dedupe keys, so decisions can be restored into a rebuilt database. Refuses a path inside the repository. Built in step 3C-8 (Q7, D-065) |

Later the app writes the same owner tables through the API (3E, 3F); the
file stays as the bulk route and the backup.

## G. Survey: `reconcile-stats`

Read-only and counts only, safe to paste. It runs the same pure derive in
memory, like `merchant-stats`, so it works before the derived tables exist.
Never names, amounts, references or account digits. Lines as built in
`reconcile-1.1.0` (`n` is a count; "role by", "candidates by" sections print
only the rows that occur):

```
reconcile-stats (reconcile-1.1.0, merchant-1.1.1, read-only)
transactions (active)                  n
role by direction
  <direction> <role>                   n     ("debit duplicate" is always shown)
role by rule
  <rule code>                          n
matched by two or more rules           n
paybacks by basis
  engine                               n
  owner                                n
uncertain credits                      n
links by kind and status
  <kind> candidate                     n     (all eight rows are always shown)
  <kind> linked                        n
candidates by kind and reason
  <kind> <reason>                      n
autopay and card pairs by time gap
  up to 10 min                         n
  10-60 min                            n
  1-24 h                               n
autopay and card pairs, merchant
  same merchant key                    n
  brand on both                        n
  brand on autopay only                n
  brand on card only                   n
  brand on neither                     n
  earlier message is autopay           n
  earlier message is card              n
existing candidates
  recorded                             n
  linked                               n
  still candidate                      n
  decided different                    n
  not active                           n
  lost                                 n
not counted yet
  foreign currency                     n
  no parser                            n
owner data
  accounts                             n
  parties                              n
  income sources                       n
  role decisions                       n
  link decisions                       n
warning: owner data lists no income party (only when that is so)
```

- "existing candidates" are the pairs in `duplicate_candidates`. **"lost"
  must be 0**: a recorded pair between two active transactions that is
  neither a link nor decided different. "not active" counts recorded pairs
  where a transaction is no longer active.
- "autopay and card pairs" covers every `DUP_autopay_card` link, linked or
  candidate. The merchant lines answer Q9 on real data without a name: how
  often the two messages give the same merchant key, which side hits the
  brand dictionary, and which message is the earlier one (the primary).
- Lines that arrive with later steps: last recompute and stored rows that
  differ (3C-6); owner texts that match no transaction and inactive
  decisions (3C-4, 3C-7); card bill lines; transactions with two or more
  sources; months with uncertain credits; credits with a same-amount debit
  inside 10 minutes.

## H. Build plan

Engine first, in memory, so the rules can be tuned on the owner's real
counts before a migration fixes anything (as in 3B). Each step is one task:
tests green, ruff clean, docs and NOTES updated, and where marked the
owner's counts-only run.

| Step | What | Tests | Heavy |
| ---- | ---- | ----- | ----- |
| 3C-2 | `app/engine/reconcile.py`: input and output dataclasses (transactions, an in-memory owner-data structure, one role with rule and basis), every role rule that reads one transaction only (B7 step 3: wording, owner texts and parties, the tracked test), owner role decisions, `totals()`. First `reconcile-stats`: role by direction, role by rule, paybacks by basis, uncertain credits, not counted yet, the income warning. On real data the owner data stays empty until 3C-4. Owner run | One case per row of B6 and B7; I16 against a naive second implementation on seeded random data; I18; stats prints no values | |
| 3C-3 | **Built in memory (`reconcile-1.1.0`).** Duplicates: pair finding by amount bucket, D1 and D2, unique-pair rule, groups, primary, legacy coverage. Stats sections. Owner run: tells whether [A1] and [A2] hold. Report whether the choice of primary changes the merchant shown for an AutoPay + card pair (Q9) | The B1 table; I15, I17; legacy coverage on fixtures | yes |
| 3C-4 | Migration `0004`, owner models, `owner-load` with validation. The loaded owner data feeds the rules built in 3C-2 (S1, S3, `CB_own_text`, `FD_own_text`, parties, income); party display names in the merchant step. Owner run | File validation (every rejection, no values in errors); load twice changes nothing; I13; RLS on the new tables; party overrides | |
| 3C-5 | **Built in memory (`reconcile-1.1.0`), except `CB_pair`** (B3: waits for credit card SMS). Pair linking: one matcher (window, unique pair) used by S2, `FD_pair` and refund links | Zero, one, many for every rule; window edges; I19; refund guard | yes |
| 3C-6 | Migration `0005`, `recompute` (compare and write), triggers in `import-sms`, `reparse` and `owner-load`, stale flag in `stats`, the key-change check | I10, I11, I12, I20, I21; key-change stop and `--accept-key-changes`; SQLite and Postgres | yes |
| 3C-7 | `reconcile-review` and the two decision tables in use; decisions in `owner-load` | I14; refusal without a terminal; contradicting decision refused; inactive decisions | |
| 3C-8 | `owner-export`. Docs (`data-model.md`, `engine.md`), DECISIONS, owner's full review, tag `phase-3c-done` | Export then load into an empty database restores every owner row | |

## I. Questions and conflicts, with the planner's decisions

Decided on 15 Nov 2026 and recorded in `docs/DECISIONS.md`.

**Questions.**

| | Question | Decision | Entry |
| -- | -------- | -------- | ----- |
| Q1 | Is a consumer handle alone (`R5_consumer_vpa`) enough to call a credit a payback? | Yes. Every payback records its basis (owner or engine). Income parties are checked first. `reconcile-stats` counts engine-basis paybacks separately. Recompute and `reconcile-stats` print a warning line when the owner data lists no income party | D-061 |
| Q2 | May a unique AutoPay + card spend pair inside 10 minutes be linked without asking? | Yes | D-062 |
| Q3 | A transfer with no payee (H06, H16) and no identified partner: spend, or not counted? | Spend, listed for review | D-060 |
| Q4 | Does a refund reduce the month it arrives in, or the month of its purchase? | The month it arrives, for refunds and paybacks | D-060 |
| Q5 | Wallets: D-029 makes a top-up a transfer, but wallet spends never appear in SMS | A top-up is a self-transfer only when the owner lists the wallet as an own account. Otherwise it is spend | D-063 |
| Q6 | After a deploy that bumps an engine version, who recomputes? | The owner; the API shows a stale flag. Revisit in Phase 5, when the server takes in SMS itself | D-066 |
| Q7 | Owner file as JSON, and `owner-export` in 3C? | Yes to both | D-065 |
| Q8 | A credit from a business that is not worded as a refund: uncertain, or income? | Uncertain | D-061 |
| Q9 | Which duplicate is the primary? Proposed: earliest time, then lowest id | Keep for now. Step 3C-3 reports whether the choice changes the merchant shown for an AutoPay + card pair; the planner decides then | D-062 |
| Q10 | Should investment debits (a mutual fund SIP) have a role of their own? | No. They stay `spend` until Phase 6 (D-026) | D-060 |
| Q11 | Is the `ignored` role wanted? | Keep. Only the owner can set it | D-060 |

**Conflicts with earlier decisions and docs.**

| | Earlier text | Decision | Entry |
| -- | ------------ | -------- | ----- |
| C1 | D-047 and data-model.md: Reconcile "decides open candidates (confirm or dismiss)" in `duplicate_candidates.status` | Approved. The table is frozen. Reconcile must find every existing candidate again, as a link or a candidate (test and stats line) | D-062 |
| C2 | D-057, D-058 and engine.md: "Corrections will be keyed on" the merchant key; a key change "needs a migration plan" | Approved. Owner data stores text and transaction ids, not merchant keys | D-065 |
| C3 | D-032, D-047, PLAN 3C: duplicates are "merged" | Approved. Nothing merges; one side gets role `duplicate` | D-062 |
| C4 | D-031: "within a few days" | Approved: 30 days. A refund to a bank account links on the same account, the way a card refund links on the same card (B4) | D-064 |
| C5 | D-055: an unsure credit "goes to the unknown queue" | Terms: "unknown messages" are unparsed messages; "uncertain credits" are credits with no role evidence. The role is `uncertain` (the draft said `unknown`) | D-061 |
| C6 | Reparse cannot split a transaction that has two sources (`relink` in `pipeline/reparse.py`), so a wrongly merged refund cannot be undone by a key fix | Not fixed now. The owner inspects the merged refund's source messages privately (NOTES.md, cheat sheet) | D-064 |
| C7 | data-model.md: Reconcile "closes mandates on cancellation" | Deferred to Phase 6; data-model.md corrected | D-067 |
| C8 | PLAN 3C listed transfers, card bills, refunds and duplicates only | PLAN updated: 3C also covers FD moves, paybacks, income, owner parties, storage, recompute, review and export | D-059 |
| C9 | D-029 and wallets | See Q5 | D-063 |
