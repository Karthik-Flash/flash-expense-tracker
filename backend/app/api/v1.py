"""Data API under /api/v1 (docs/api.md). Every route needs a login; every query and write
is scoped to the token's owner. Money is integer paise; times are UTC ISO strings.
No response holds raw message text or a reference.

Writes use source "app", are idempotent, and end with one recompute in the same database
transaction: the answer and the derived rows are saved together, or nothing is. With an
Idempotency-Key a repeat writes nothing and gets the first answer (app/api/ops.py). Every
read first runs a recompute a deferred write left (D-094).
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api import ops
from app.api.auth import current_owner
from app.db import get_session
from app.engine.categorise import CATEGORIES, SPENDING_ROLES, UNCATEGORISED, breakdown, label_view
from app.engine.credits import sender_id
from app.engine.reconcile import IST, ist_month, totals
from app.models import (
    Label,
    ParseResult,
    Party,
    RawMessage,
    Transaction,
    TxnDerived,
    TxnLabel,
)
from app.pipeline import owner_actions
from app.pipeline.recompute import OwnerDataError, last_run_time, plan, stale_reason

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_owner)])
Owner = Annotated[uuid.UUID, Depends(current_owner)]
Db = Annotated[Session, Depends(get_session)]
Month = Annotated[str, Query(pattern=r"^\d{4}-\d{2}$", description="IST month, YYYY-MM")]
Fresh = [Depends(ops.fresh_reads)]  # every read: a deferred recompute runs first
NOT_COUNTED = ("foreign_currency_deferred", "no_parser_for_bank")


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SenderAnswer(Body):
    answer: Literal["friend", "income", "ignore"]
    label: str | None = Field(None, max_length=200)  # the rules: owner_actions.clean_name


class CategoryAnswer(Body):
    category: str
    scope: Literal["merchant", "transaction"]


class NewLabel(Body):
    name: str = Field(max_length=200)  # the rules: owner_actions.clean_name


class LabelAnswer(Body):
    """An existing label, or a new one made and attached in the same write (4B-2)."""

    label_id: int | None = None
    new_label: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def one_of(self) -> "LabelAnswer":
        if (self.label_id is None) == (self.new_label is None):
            raise ValueError("send label_id or new_label")
        return self


def _now() -> datetime:
    return datetime.now(UTC)


def _month(month: str) -> tuple[datetime, datetime]:
    try:
        return ist_month(month)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z") if moment else None


def _stored(session: Session, owner: uuid.UUID, *where) -> list:
    """Stored derived rows with their transaction, for one owner."""
    query = (
        select(Transaction, TxnDerived)
        .join(TxnDerived, TxnDerived.transaction_id == Transaction.id)
        .where(Transaction.owner_id == owner, Transaction.status == "active", *where)
    )
    return list(session.execute(query))


def _engine_view(rows: list) -> tuple[list, dict, dict]:
    """Stored rows as the engine's inputs for totals(), breakdown() and label_view()."""
    txns = [
        SimpleNamespace(id=t.id, amount_paise=t.amount_paise, txn_time_utc=t.txn_time_utc)
        for t, _ in rows
    ]
    roles = {t.id: SimpleNamespace(role=d.role, basis=d.role_basis) for t, d in rows}
    categories = {t.id: SimpleNamespace(category=d.category) for t, d in rows}
    return txns, roles, categories


def _categories(parts: dict[str, int]) -> list[dict]:
    return [{"slug": s, "name": CATEGORIES[s], "amount_paise": v} for s, v in parts.items()]


def _person(owner: uuid.UUID, t: Transaction, d: TxnDerived) -> str | None:
    """Who the money went to or came from: the owner party its text matches (p_), else the
    sender id of its text (s_, as in /senders). One person under a name and a UPI ID is one
    only once the owner lists both texts on one party."""
    if d.party_id is not None:
        return f"p_{d.party_id}"
    return sender_id(str(owner), d.merchant_key, t.id) if d.merchant_key else None


def _item(owner: uuid.UUID, t: Transaction, d: TxnDerived, lab: Label | None) -> dict:
    return {
        "id": t.id,
        "time_utc": _iso(t.txn_time_utc),
        "amount_paise": t.amount_paise,
        "direction": t.direction,
        "display_name": d.display_name,
        "person_id": _person(owner, t, d),
        "role": d.role,
        "role_basis": d.role_basis,
        "category": d.category,
        "category_name": CATEGORIES.get(d.category, d.category),
        "category_basis": d.category_basis,
        "label": {"id": lab.id, "name": lab.name} if lab else None,
    }


def _items(owner: uuid.UUID):
    return (
        select(Transaction, TxnDerived, Label)
        .join(TxnDerived, TxnDerived.transaction_id == Transaction.id)
        .outerjoin(TxnLabel, TxnLabel.transaction_id == Transaction.id)
        .outerjoin(Label, Label.id == TxnLabel.label_id)
        .where(Transaction.owner_id == owner, Transaction.status == "active")
    )


def _previous(session: Session, owner: uuid.UUID, month: str) -> dict:
    """The month before, to compare with: up to the same IST day when `month` is the current
    IST month, else the whole month. Same rules as Spent."""
    year, number = map(int, month.split("-"))
    before = f"{year - (number == 1)}-{(number - 2) % 12 + 1:02d}"
    start, end = _month(before)
    today = _now().astimezone(IST)
    whole = today.strftime("%Y-%m") != month
    if not whole:
        end = min(end, start + timedelta(days=today.day))
    rows = _stored(
        session, owner, Transaction.txn_time_utc >= start, Transaction.txn_time_utc < end
    )
    txns, roles, categories = _engine_view(rows)
    return {
        "month": before,
        "whole": whole,
        "spent_paise": totals(txns, roles, start, end).spent_paise,
        "categories": _categories(breakdown(txns, roles, categories, start, end)),
    }


def _label_totals(rows: list) -> dict:
    txns, roles, cats = _engine_view(rows)
    t, parts = label_view(txns, roles, cats, [x.id for x in txns])
    return {
        "transactions": len(rows),
        "spent_paise": t.spent_paise,
        "paid_back_paise": t.paid_back_paise,
        "to_confirm_paise": t.to_confirm_paise,
        "net_paise": t.net_paise,
        "categories": _categories(parts),
    }


def freshness(session: Session, owner: uuid.UUID) -> tuple[bool, str | None]:
    """(stale, last recompute time) of the owner's stored rows."""
    try:
        p = plan(session, owner)
    except OwnerDataError as exc:
        raise HTTPException(409, str(exc)) from None
    return stale_reason(p) is not None, _iso(last_run_time(session, owner))


@router.get("/summary", dependencies=Fresh)
def summary(owner: Owner, session: Db, month: Month) -> dict:
    return month_summary(session, owner, month, *freshness(session, owner))


def month_summary(
    session: Session, owner: uuid.UUID, month: str, stale: bool, last_recompute: str | None
) -> dict:
    """The /summary answer for one IST month; the snapshot reuses it (D-088)."""
    start, end = _month(month)
    rows = _stored(
        session, owner, Transaction.txn_time_utc >= start, Transaction.txn_time_utc < end
    )
    txns, roles, categories = _engine_view(rows)
    t = totals(txns, roles, start, end)
    parts = breakdown(txns, roles, categories, start, end)
    open_senders = [
        s for s in owner_actions.senders(session, owner, start, end) if s.status == "to_confirm"
    ]
    not_counted = session.scalar(
        select(func.count())
        .select_from(ParseResult)
        .join(RawMessage, RawMessage.id == ParseResult.raw_message_id)
        .where(
            RawMessage.owner_id == owner,
            ParseResult.is_current,
            ParseResult.unknown_reason.in_(NOT_COUNTED),
            RawMessage.received_at >= start,
            RawMessage.received_at < end,
        )
    )
    return {
        "month": month,
        "spent_paise": t.spent_paise,
        "paid_back_paise": t.paid_back_paise,
        "to_confirm": {"amount_paise": t.to_confirm_paise, "senders": len(open_senders)},
        "net_paise": t.net_paise,
        "income_paise": t.income_paise,
        "categories": _categories(parts),
        "counts": {
            "uncategorised_spend": sum(
                d.role in SPENDING_ROLES and d.category == UNCATEGORISED for _, d in rows
            ),
            "senders_to_confirm": len(open_senders),
            "not_counted_yet": not_counted,
        },
        "stale": stale,
        "last_recompute_utc": last_recompute,
        "previous": _previous(session, owner, month),
    }


@router.get("/transactions", dependencies=Fresh)
def transactions(
    owner: Owner,
    session: Db,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    category: str | None = None,
    label: int | None = None,
    cursor: Annotated[str | None, Query(pattern=r"^\d+_\d+$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    if category is not None and category not in CATEGORIES:
        raise HTTPException(422, "not a category of the list")
    query = _items(owner)
    if month:
        start, end = _month(month)
        query = query.where(Transaction.txn_time_utc >= start, Transaction.txn_time_utc < end)
    if category:
        query = query.where(TxnDerived.category == category)
    if label is not None:
        query = query.where(TxnLabel.label_id == label)
    if cursor:
        ms, last_id = map(int, cursor.split("_"))
        moment = datetime.fromtimestamp(ms / 1000, UTC)
        query = query.where(
            or_(
                Transaction.txn_time_utc < moment,
                and_(Transaction.txn_time_utc == moment, Transaction.id < last_id),
            )
        )
    query = query.order_by(Transaction.txn_time_utc.desc(), Transaction.id.desc()).limit(limit + 1)
    rows = list(session.execute(query))
    items = [_item(owner, t, d, lab) for t, d, lab in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1][0]
        next_cursor = f"{int(last.txn_time_utc.timestamp() * 1000)}_{last.id}"
    return {"items": items, "next_cursor": next_cursor}


@router.get("/transactions/{txn_id}", dependencies=Fresh)
def transaction(owner: Owner, session: Db, txn_id: int) -> dict:
    row = session.execute(_items(owner).where(Transaction.id == txn_id)).first()
    if row is None:
        raise HTTPException(404, "no such transaction")
    return _item(owner, *row)


@router.get("/categories")
def categories(owner: Owner) -> list[dict]:
    return [{"slug": slug, "name": name} for slug, name in CATEGORIES.items()]


@router.get("/labels", dependencies=Fresh)
def labels(owner: Owner, session: Db) -> list[dict]:
    """Every label with its totals across all dates (no breakdown: see /labels/{id})."""
    rows = defaultdict(list)
    query = (
        select(Transaction, TxnDerived, TxnLabel.label_id)
        .join(TxnDerived, TxnDerived.transaction_id == Transaction.id)
        .join(TxnLabel, TxnLabel.transaction_id == Transaction.id)
        .where(Transaction.owner_id == owner, Transaction.status == "active")
    )
    for t, d, label_id in session.execute(query):
        rows[label_id].append((t, d))
    found = session.scalars(select(Label).where(Label.owner_id == owner).order_by(Label.name))
    out = []
    for x in found:
        view = _label_totals(rows[x.id])
        del view["categories"]
        out.append({"id": x.id, "name": x.name, **view})
    return out


@router.get("/labels/{label_id}", dependencies=Fresh)
def label_detail(owner: Owner, session: Db, label_id: int) -> dict:
    found = session.get(Label, label_id)
    if found is None or found.owner_id != owner:
        raise HTTPException(404, "no such label")
    rows = _stored(session, owner, Transaction.id.in_(
        select(TxnLabel.transaction_id).where(TxnLabel.label_id == label_id)
    ))  # fmt: skip
    return {"id": found.id, "name": found.name, **_label_totals(rows)}


@router.get("/senders", dependencies=Fresh)
def senders(
    owner: Owner,
    session: Db,
    status: Literal["to_confirm", "confirmed", "ignored", "all"] = "to_confirm",
) -> list[dict]:
    income = dict(
        session.execute(
            select(Party.id, Party.income_label).where(
                Party.owner_id == owner, Party.income_label.is_not(None)
            )
        ).all()
    )
    return [
        {
            "id": s.id,
            "display_name": s.display_name,
            "total_paise": s.total_paise,
            "count": s.count,
            "role": s.role,
            "basis": s.basis,
            "status": s.status,
            "last_time_utc": _iso(s.last_time_utc),
            "income_label": income.get(s.party_id) if s.role == "income" else None,
        }
        for s in owner_actions.senders(session, owner)
        if status in ("all", s.status)
    ]


@router.put("/senders/{sender_id}")
def answer_sender(owner: Owner, session: Db, op: ops.OpDep, sender_id: str, body: SenderAnswer):
    def action() -> dict:
        s = owner_actions.answer_sender(session, owner, sender_id, body.answer, body.label, "app")
        return {"id": s.id, "credits": s.count}

    return ops.write(session, owner, op, action, body.model_dump())


@router.delete("/senders/{sender_id}")
def reset_sender(owner: Owner, session: Db, op: ops.OpDep, sender_id: str):
    def action() -> dict:
        s = owner_actions.reset_sender(session, owner, sender_id)
        return {"id": s.id, "credits": s.count}

    return ops.write(session, owner, op, action)


@router.put("/transactions/{txn_id}/category")
def set_category(owner: Owner, session: Db, op: ops.OpDep, txn_id: int, body: CategoryAnswer):
    def action() -> dict:
        owner_actions.set_category(session, owner, txn_id, body.category, body.scope, "app")
        return {"id": txn_id, "category": body.category, "scope": body.scope}

    return ops.write(session, owner, op, action, body.model_dump())


@router.post("/labels", status_code=201)
def create_label(owner: Owner, session: Db, op: ops.OpDep, body: NewLabel):
    """A new label: 201. A name the owner already has, in any case: 409."""

    def action() -> dict:
        made = owner_actions.create_label(session, owner, body.name, "app")
        return {"id": made.id, "name": made.name}

    return ops.write(session, owner, op, action, body.model_dump(), recomputes=False, status=201)


@router.put("/transactions/{txn_id}/label")
def set_label(owner: Owner, session: Db, op: ops.OpDep, txn_id: int, body: LabelAnswer):
    def action() -> dict:
        label_id = body.label_id
        if body.new_label is not None:
            owner_actions.transaction_of(session, owner, txn_id)  # a missing one: 404 first
            label_id = owner_actions.create_label(session, owner, body.new_label, "app").id
        owner_actions.set_label(session, owner, txn_id, label_id, "app")
        return {"id": txn_id, "label_id": label_id}

    return ops.write(session, owner, op, action, body.model_dump())


@router.delete("/transactions/{txn_id}/label")
def clear_label(owner: Owner, session: Db, op: ops.OpDep, txn_id: int):
    def action() -> dict:
        owner_actions.clear_label(session, owner, txn_id)
        return {"id": txn_id, "label_id": None}

    return ops.write(session, owner, op, action)
