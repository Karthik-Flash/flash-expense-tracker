# To-do, in plain English

To-do holds the questions only you can answer. Nothing in it changes a total by itself;
your answer does, and only in the ways listed here. Answering anywhere (To-do, a payment's
sheet, a person's sheet) removes the question everywhere: the server keeps one answer per
payment or payee, and the app hides a question the moment you answer, even offline (it
shows under "Saved on phone" until the server has it).

## What appears, and why

| Section | What is in it | Grouped by | Order |
| --- | --- | --- | --- |
| Moved between your accounts? | A debit on one of your accounts and a credit of the same amount on another, close in time, with no shared reference | the pair | newest first |
| Is this you? / Is this an investment? | A payee whose name matches one of your names, or a broker or fund house | the payee | newest first |
| Who sent you money? | Money in that Flash cannot place: from a person (maybe paying you back), or from someone unknown | the sender (one row for all their credits, with the count and the total) | newest credit first |
| Pick a category | Spending that is still Uncategorised | the payee name (count and total) | newest payment first |
| Check these payments | A payment read by the generic reader (a bank with no reader of its own) or from a statement, not yet checked: Looks right / Not a payment | the payment | newest first |
| Answered | Senders you answered (or left as is), to change the answer | the sender | newest first |

The tab's number is the count of open rows (Who sent you money?, Pick a category, Moved
between your accounts?, Is this you?, Is this an investment?, Check these payments); a row
with several payments counts once. Answered and Saved on phone are not counted.

## What each answer does

| Answer | Where | What changes |
| --- | --- | --- |
| Friend | Who sent you money? | Every credit from them counts as **Paid back**: Net goes down by those credits. |
| Family / Income | Who sent you money? | Every credit from them counts as **Income** (shown with your label); Net does not move. |
| Ignore | Who sent you money? | Every credit from them is left out of every total. |
| Paid back / Not paid back / This is income, **Just this one** | A credit's sheet | Only that credit, and it wins over the answer for the sender. "Use the answer for <name>" undoes it. |
| **Leave as is** | Who sent you money? | The question stops for that sender. Their credits stay as they were (still waiting for an answer, so Net does not move); they show under the answered senders as "Left as is", and the payment's sheet has **Ask again**. |
| A category, "All payments to <name>" | Pick a category, or a payment's sheet | The payee's category, for past and future payments. Spent does not move: a category only splits Spent. Profile > Your rules lists it, with Undo. |
| A category, "Just this payment" | A payment's sheet | That payment only; it wins over the rule. |
| **Leave as is** | Pick a category | The question stops for that payee. Its payments stay Uncategorised in Spent; nothing else moves. **Ask again** in a payment's sheet brings it back. |
| Not a payment | A payment's sheet (also "Check these payments") | That one row leaves every total. **Count it again** undoes it. This is not "Leave as is": it changes the totals. |
| Same / Different | Moved between your accounts? | Same: both legs leave Spent and Income. Different: they stay as they were. |
| Yes / No | Is this you? Is this an investment? | Yes: payments to that payee leave Spent (It's me) or count as Invested. No: never asked again. |

A guess never lowers Net: only Friend, Paid back for one credit, Same, and It's me take money
out of Spent or Net. Investments count in Spent unless you turn that off in Profile.
