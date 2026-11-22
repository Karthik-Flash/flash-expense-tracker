"""Owner review commands after the 5B-1 deploy (D-137): category-diff and payback-review.

Both read only: a fresh derive in memory (recompute.plan), never a write. They print counts
only; the rows go to a PRIVATE CSV file the owner names, which must be outside the
repository (the CLI refuses a path inside it).

- category_diff: every active transaction categorised by the categorise-1.2.0 person rules
  and by the current ones (1.3.0), on the same roles. Rows whose category differs.
- payback_review: every credit that is, or may be, money back from a person: paybacks the
  owner confirmed, ones the engine suggests (To confirm, never in Net), and credits with
  no answer (uncertain), with the payment each one pays back (credits.payback_links).
"""

import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.engine.categorise import categorise
from app.engine.credits import PaybackRow, payback_links
from app.engine.reconcile import IST
from app.pipeline.recompute import plan

DIFF_COLUMNS = (
    "transaction_id", "time_ist", "direction", "amount_paise", "role", "name",
    "counterparty", "category_1_2_0", "rule_1_2_0", "category_1_3_0", "rule_1_3_0",
)  # fmt: skip
PAYBACK_COLUMNS = (
    "transaction_id", "time_ist", "amount_paise", "name", "counterparty", "answer", "rule",
    "pays_back", "link",
)  # fmt: skip


@dataclass
class CategoryDiff:
    before: Counter  # category -> transactions, under 1.2.0
    after: Counter  # the same under 1.3.0
    rows: list[dict]  # the changed transactions, DIFF_COLUMNS


def _ist(moment) -> str:
    return moment.astimezone(IST).strftime("%Y-%m-%d %H:%M")


def category_diff(session: Session, owner: uuid.UUID) -> CategoryDiff:
    p = plan(session, owner)
    old = categorise(p.txns, p.owner, p.result, rules="1.2.0")
    new = p.categories
    rows = []
    for t in sorted(p.txns, key=lambda t: (t.txn_time_utc, t.id)):
        a, b = old[t.id], new[t.id]
        if a.category != b.category:
            rows.append(dict(zip(DIFF_COLUMNS, (
                t.id, _ist(t.txn_time_utc), t.direction, t.amount_paise,
                p.result.roles[t.id].role, p.result.merchants[t.id].display_name or "",
                t.counterparty_raw or "", a.category, a.rule, b.category, b.rule,
            ), strict=True)))  # fmt: skip
    before = Counter(c.category for c in old.values())
    return CategoryDiff(before, Counter(c.category for c in new.values()), rows)


@dataclass
class PaybackReview:
    counts: Counter  # engine_suggested, owner_confirmed, unanswered
    by_month: dict[str, Counter]  # IST month -> the same counts
    links: Counter  # linked, candidate, none (paybacks only)
    rows: list[dict]  # PAYBACK_COLUMNS


def _person(d, merchant) -> str | None:
    """Who a transaction is with, as payback_links compares it: a party, else a key."""
    if d.party is not None:
        return f"p_{d.party}"
    return f"k:{merchant.merchant_key}" if merchant.merchant_key else None


def answer_of(role: str, basis: str) -> str | None:
    if role == "payback":
        return "owner_confirmed" if basis == "owner" else "engine_suggested"
    if role == "uncertain" and basis == "engine":
        return "unanswered"
    return None


def payback_review(session: Session, owner: uuid.UUID) -> PaybackReview:
    p = plan(session, owner)
    roles, merchants = p.result.roles, p.result.merchants
    links = payback_links(
        PaybackRow(t.id, t.direction, t.amount_paise, t.txn_time_utc,
                   _person(roles[t.id], merchants[t.id]), roles[t.id].role)
        for t in p.txns
    )  # fmt: skip
    pays_back: dict[int, list] = {}
    for x in links:
        pays_back.setdefault(x.credit, []).append(x)
    counts, by_month, linked, rows = Counter(), {}, Counter(), []
    for t in sorted(p.txns, key=lambda t: (t.txn_time_utc, t.id)):
        d = roles[t.id]
        answer = answer_of(d.role, d.basis) if t.direction == "credit" else None
        if answer is None:
            continue
        counts[answer] += 1
        month = t.txn_time_utc.astimezone(IST).strftime("%Y-%m")
        by_month.setdefault(month, Counter())[answer] += 1
        mine = pays_back.get(t.id, [])
        status = mine[0].status if mine else "none"
        if d.role == "payback":
            linked[status] += 1
        rows.append(dict(zip(PAYBACK_COLUMNS, (
            t.id, _ist(t.txn_time_utc), t.amount_paise, merchants[t.id].display_name or "",
            t.counterparty_raw or "", answer, d.rule, " ".join(str(x.debit) for x in mine),
            status,
        ), strict=True)))  # fmt: skip
    return PaybackReview(counts, dict(sorted(by_month.items())), linked, rows)
