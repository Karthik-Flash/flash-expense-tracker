"""GET /api/v1/export (5F, D-146): the owner's transactions of a date range as CSV or Excel.

Built on the server from the stored rows and the same totals as /summary (D-088), so the
Summary sheet says what the app says. Scoped to the login's owner like every route; a read,
so a deferred recompute runs first. Never raw SMS text, a reference or another owner's row.
"""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api import v1
from app.api.auth import current_owner
from app.api.snapshot import name_of
from app.engine.categorise import CATEGORIES, breakdown
from app.engine.reconcile import IST, totals
from app.models import Transaction
from app.pipeline import owner_actions
from app.pipeline.export import AMOUNT, COLUMNS, Sheet, to_csv, to_xlsx

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_owner)])
MAX_DAYS = 366 * 3

ROLE_TEXT = {
    "spend": "Spent",
    "card_bill_counted": "Card bill, spent",
    "refund": "Refund",
    "payback": "Paid back",
    "income": "Income",
    "self_transfer": "Between your accounts",
    "card_bill_excluded": "Card bill, not counted",
    "fd_move": "Fixed deposit",
    "investment": "Investment",
    "duplicate": "Second message",
    "ignored": "Not a payment",
    "uncertain": "To confirm",
}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """IST days, both included, as UTC instants [from, to)."""
    if end < start or (end - start).days > MAX_DAYS:
        raise HTTPException(422, f"the range is 1 to {MAX_DAYS} days, start before end")
    first = datetime.combine(start, time(), IST)
    return first, datetime.combine(end + timedelta(days=1), time(), IST)


def note(item: dict) -> str:
    """What the owner should know about a row, in a few words."""
    parts = []
    if item["role"] == "uncertain" or (item["role"] == "payback" and item["role_basis"] != "owner"):
        parts.append("waiting for your answer")
    if item["investment"] == "suggested":
        parts.append("investment, to confirm")
    if item["statement"]:
        parts.append("read from the bank statement")
    elif item["generic"]:
        parts.append("read automatically")
    return "; ".join(parts)


@router.get("/export", dependencies=v1.Fresh)
def export(
    owner: v1.Owner,
    session: v1.Db,
    start: Annotated[date, Query(description="first IST day, YYYY-MM-DD")],
    end: Annotated[date, Query(description="last IST day, YYYY-MM-DD")],
    format: Literal["csv", "xlsx"] = "csv",
) -> Response:
    since, until = _bounds(start, end)
    inv = v1.investments(session, owner)
    query = (
        v1._items(owner)
        .where(Transaction.txn_time_utc >= since, Transaction.txn_time_utc < until)
        .order_by(Transaction.txn_time_utc, Transaction.id)
    )
    found = [
        (t, v1._item(owner, t, d, lab, checked, inv))
        for t, d, lab, checked in session.execute(query)
    ]
    rows = []
    for t, item in found:
        local = t.txn_time_utc.astimezone(IST)
        rows.append([
            local.strftime("%Y-%m-%d"), local.strftime("%H:%M"), name_of(item),
            item["category_name"], item["label"]["name"] if item["label"] else "",
            ROLE_TEXT.get(item["role"], item["role"]),
            "in" if item["direction"] == "credit" else "out", t.amount_paise / 100,
            t.bank, t.account_last4 or "", "yes" if item["role_basis"] == "owner" else "no",
            note(item),
        ])  # fmt: skip
    header = tuple(c for c, _ in COLUMNS)
    name = f"flash-{start.isoformat()}-to-{end.isoformat()}"
    if format == "csv":
        disposition = {"Content-Disposition": f'attachment; filename="{name}.csv"'}
        return Response(
            to_csv(header, rows), media_type="text/csv; charset=utf-8", headers=disposition
        )
    stored = v1._stored(
        session, owner, Transaction.txn_time_utc >= since, Transaction.txn_time_utc < until
    )
    txns, roles, cats = v1._engine_view(stored)
    in_spent = owner_actions.owner_settings(session, owner)["count_investments_in_spent"]
    t = totals(txns, roles, since, until, in_spent)
    summary = [
        ["From", start.isoformat()], ["To", end.isoformat()],
        ["Spent", t.spent_paise / 100], ["Invested", t.invested_paise / 100],
        ["Paid back", t.paid_back_paise / 100], ["Net", t.net_paise / 100],
        ["Income", t.income_paise / 100],
        ["Investments counted in Spent", "yes" if in_spent else "no"], ["", ""],
        ["Spent by category", ""],
    ]  # fmt: skip
    for slug, paise in breakdown(txns, roles, cats, since, until, in_spent).items():
        summary.append([CATEGORIES[slug], paise / 100])
    sheets = [
        Sheet("Transactions", header, tuple(w for _, w in COLUMNS), rows, frozenset({AMOUNT})),
        Sheet("Summary", ("Item", "Rupees"), (30, 16), summary, frozenset({1})),
    ]
    disposition = {"Content-Disposition": f'attachment; filename="{name}.xlsx"'}
    return Response(to_xlsx(sheets), media_type=XLSX, headers=disposition)
