"""`doctor` (premium D, D-150): read-only checks of one owner's data. Counts only, never a
value from the data. Each check is a name and a number of problems; 0 everywhere is healthy.

- every active transaction has a source raw message and a parser version;
- every active transaction has its derived row (else: recompute first);
- no link, duplicate pointer, label or owner answer on a transaction that is not active;
- the snapshot's month totals = /summary = the export's Summary sheet = analytics, each month;
- the data version row exists once the owner has transactions.
"""

import uuid

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    DataVersion,
    OwnerCategory,
    OwnerRole,
    ParseResult,
    Transaction,
    TransactionSource,
    TxnDerived,
    TxnLabel,
    TxnLink,
)
from app.pipeline.recompute import OwnerDataError, plan, stale_reason

FIELDS = ("spent_paise", "invested_paise", "paid_back_paise", "net_paise", "income_paise")

# (check, number, counts as a problem): counts like "months checked" are only shown.
Line = tuple[str, int, bool]


def _count(session: Session, query) -> int:
    return session.scalar(select(func.count()).select_from(query.subquery())) or 0


def checks(session: Session, owner: uuid.UUID) -> list[Line]:
    """Every check in a fixed order. Reads only; the caller rolls the session back."""
    active = select(Transaction.id).where(
        Transaction.owner_id == owner, Transaction.status == "active"
    )
    live = active.scalar_subquery()
    out: list[Line] = [("transactions (active)", _count(session, active), False)]
    source = exists().where(TransactionSource.transaction_id == Transaction.id)
    out.append(("without a source message", _count(session, active.where(~source)), True))
    versionless = (
        select(TransactionSource.transaction_id)
        .join(ParseResult, ParseResult.id == TransactionSource.parse_result_id)
        .where(TransactionSource.transaction_id.in_(live))
        .where(or_(ParseResult.parser_version.is_(None), ParseResult.parser_version == ""))
    )
    out.append(("without a parser version", _count(session, versionless), True))
    derived = exists().where(TxnDerived.transaction_id == Transaction.id)
    out.append(("without derived data", _count(session, active.where(~derived)), True))
    links = select(TxnLink.id).where(
        TxnLink.owner_id == owner, or_(TxnLink.txn_a.not_in(live), TxnLink.txn_b.not_in(live))
    )
    out.append(("links to inactive rows", _count(session, links), True))
    dup = select(TxnDerived.transaction_id).where(
        TxnDerived.transaction_id.in_(live), TxnDerived.duplicate_of.is_not(None),
        TxnDerived.duplicate_of.not_in(live),
    )  # fmt: skip
    out.append(("duplicates of inactive rows", _count(session, dup), True))
    lost = sum(
        _count(session, select(column).where(model.owner_id == owner, column.not_in(live)))
        for model, column in (
            (TxnLabel, TxnLabel.transaction_id),
            (OwnerRole, OwnerRole.transaction_id),
            (OwnerCategory, OwnerCategory.transaction_id),
        )
    )
    out.append(("owner answers on inactive rows", lost, True))
    try:
        stale = stale_reason(plan(session, owner)) is not None
    except OwnerDataError:  # owner data the engine cannot use is itself the finding
        stale = True
    out.append(("derived tables stale", int(stale), True))
    out.extend(_totals(session, owner))
    missing = out[0][1] > 0 and session.get(DataVersion, owner) is None
    out.append(("data version missing", int(missing), True))
    return out


def _totals(session: Session, owner: uuid.UUID) -> list[Line]:
    """Each IST month with transactions: snapshot, /summary, export and analytics agree."""
    from app.api import analytics, export, snapshot, v1

    doc = snapshot.build(session, owner)
    months = [m["month"] for m in doc["months"]]
    bars: dict[str, dict] = {}
    first = months[0] if months else None
    while first and first <= months[-1]:  # analytics takes at most MAX_MONTHS at a time
        window = analytics.month_list(first, first)
        while len(window) < analytics.MAX_MONTHS and window[-1] < months[-1]:
            window = analytics.month_list(first, _next(window[-1]))
        for bar in analytics.build(session, owner, window)["months"]:
            bars[bar["month"]] = bar
        first = _next(window[-1])
    stale, last = v1.freshness(session, owner)
    wrong = 0
    for m in doc["months"]:
        summary = v1.month_summary(session, owner, m["month"], stale, last)
        t, _, _ = export.range_totals(session, owner, *v1._month(m["month"]))
        sheet = {f: getattr(t, f) for f in FIELDS}
        views = (m["summary"], sheet, bars.get(m["month"], {}))
        wrong += any(view.get(f) != summary[f] for view in views for f in FIELDS)
    return [("months checked", len(months), False), ("months that disagree", wrong, True)]


def _next(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y + m // 12}-{m % 12 + 1:02d}"
