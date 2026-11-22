"""GET /api/v1/analytics (premium B, D-148): the Insights charts and stats for a range of IST
months, every number computed here (D-088).

Per month the same totals() and breakdown() as /summary over the same rows, so the bars and
/summary always agree (tests/test_analytics.py checks every month). One read of the range's
rows; the ETag is the snapshot's cheap one (the data version, the IST day, the engine
versions) plus the range, so an unchanged answer is a 304 without building it.
"""

import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from app.api import v1
from app.api.auth import current_owner
from app.api.snapshot import (
    canonical,
    cheap_etag,
    is_person_item,
    name_of,
    people,
    person_key,
    spent_effect,
)
from app.engine.categorise import CATEGORIES, breakdown
from app.engine.reconcile import CARD_CHANNELS, IST, totals
from app.models import Transaction

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_owner)])
MAX_MONTHS = 24
TOP = 8
MOVES = 3
REGULAR_MONTHS = 3  # a regular payee: paid in at least this many months of the range
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def month_list(start: str, end: str) -> list[str]:
    """Every IST month from start to end, both included."""
    y, m = map(int, start.split("-"))
    out = []
    while f"{y}-{m:02d}" <= end and len(out) <= MAX_MONTHS:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    if not out or len(out) > MAX_MONTHS:
        raise HTTPException(422, f"the range is 1 to {MAX_MONTHS} months, start before end")
    return out


def share(part: int, whole: int) -> int:
    """Basis points (1/100 of a per cent), rounded half up; 0 of nothing."""
    return (part * 10_000 * 2 + whole) // (whole * 2) if whole > 0 else 0


def build(session, owner, months: list[str]) -> dict:
    bounds = [v1._month(m) for m in months]
    since, until = bounds[0][0], bounds[-1][1]
    inv = v1.investments(session, owner)
    rows = v1._stored(
        session, owner, Transaction.txn_time_utc >= since, Transaction.txn_time_utc < until
    )
    txns, roles, cats = v1._engine_view(rows)
    bars, by_cat = [], defaultdict(dict)
    for month, (start, end) in zip(months, bounds, strict=True):
        t = totals(txns, roles, start, end, inv.in_spent)
        parts = breakdown(txns, roles, cats, start, end, inv.in_spent)
        for slug, paise in parts.items():
            by_cat[slug][month] = paise
        bars.append({
            "month": month, "spent_paise": t.spent_paise, "invested_paise": t.invested_paise,
            "paid_back_paise": t.paid_back_paise, "net_paise": t.net_paise,
            "income_paise": t.income_paise, "to_confirm_paise": t.to_confirm_paise,
        })  # fmt: skip
    spent = sum(b["spent_paise"] for b in bars)
    categories = sorted(
        (
            {
                "slug": slug,
                "name": CATEGORIES[slug],
                "total_paise": sum(per.values()),
                "share_bp": share(sum(per.values()), spent),
                "months": [per.get(m, 0) for m in months],
            }
            for slug, per in by_cat.items()
        ),
        key=lambda c: (-c["total_paise"], c["slug"]),
    )
    query = v1._items(owner).where(
        Transaction.txn_time_utc >= since, Transaction.txn_time_utc < until
    )
    found = [
        (t, v1._item(owner, t, d, lab, checked, inv))
        for t, d, lab, checked in session.execute(
            query.order_by(Transaction.txn_time_utc.desc(), Transaction.id.desc())
        )
    ]
    items = [item for _, item in found]
    return {
        "start": months[0],
        "end": months[-1],
        "months": bars,
        "categories": categories,
        "moves": moves(categories, months),
        "merchants": top_merchants(items, inv.in_spent, spent),
        "people": top_people(items),
        "stats": stats(found, bars, since, until, inv.in_spent),
    }


def moves(categories: list[dict], months: list[str]) -> dict | None:
    """The biggest category increases and decreases, the last month against the one before."""
    if len(months) < 2:
        return None
    change = [
        {
            "slug": c["slug"],
            "name": c["name"],
            "from_paise": c["months"][-2],
            "to_paise": c["months"][-1],
            "change_paise": c["months"][-1] - c["months"][-2],
        }
        for c in categories
    ]
    up = sorted((c for c in change if c["change_paise"] > 0), key=lambda c: -c["change_paise"])
    down = sorted((c for c in change if c["change_paise"] < 0), key=lambda c: c["change_paise"])
    return {"from": months[-2], "to": months[-1], "up": up[:MOVES], "down": down[:MOVES]}


def top_merchants(items: list[dict], invest: bool, spent: int) -> list[dict]:
    """Spent per name outside People, biggest first."""
    rows: dict[str, dict] = {}
    for item in items:
        effect = spent_effect(item, invest)
        if effect == 0 or item["category"] == "people":
            continue
        name = name_of(item)
        r = rows.setdefault(name, {"name": name, "total_paise": 0, "count": 0})
        r["total_paise"] += effect
        r["count"] += 1
    out = sorted(rows.values(), key=lambda r: (-r["total_paise"], r["name"]))[:TOP]
    return [r | {"share_bp": share(r["total_paise"], spent)} for r in out]


def top_people(items: list[dict]) -> list[dict]:
    """The People ledger of the range: Sent, Got back, To confirm, Net, and how many rows."""
    count = Counter(person_key(i) for i in items if is_person_item(i))
    rows = [p for p in people(items) if p["sent_paise"] > 0]  # people the owner paid
    sent = sum(p["sent_paise"] for p in rows)
    return [
        p | {"count": count[p["key"]], "share_bp": share(p["sent_paise"], sent)} for p in rows[:TOP]
    ]


def stats(found: list, bars: list[dict], since: datetime, until: datetime, invest: bool) -> dict:
    today = v1._now().astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    last = min(until, today + timedelta(days=1))
    days = max(1, (last - since).days)
    spent = sum(b["spent_paise"] for b in bars)
    spends = [(t, item) for t, item in found if spent_effect(item, invest) > 0]
    biggest = max(spends, key=lambda x: (x[0].amount_paise, x[0].id), default=None)
    weekdays = Counter(t.txn_time_utc.astimezone(IST).weekday() for t, _ in spends)
    busiest = max(weekdays.items(), key=lambda x: (x[1], -x[0]), default=None)
    by_way = Counter()
    for t, _ in spends:
        way = "upi" if t.channel == "upi" else "card" if t.channel in CARD_CHANNELS else "other"
        by_way[way] += t.amount_paise
    paid = sum(by_way.values())
    months_of: dict[str, set[str]] = defaultdict(set)
    totals_of: Counter = Counter()
    for t, item in spends:
        name = name_of(item)
        months_of[name].add(t.txn_time_utc.astimezone(IST).strftime("%Y-%m"))
        totals_of[name] += t.amount_paise
    regular = sorted(
        (
            {"name": n, "months": len(ms), "total_paise": totals_of[n]}
            for n, ms in months_of.items()
            if len(ms) >= REGULAR_MONTHS
        ),
        key=lambda r: (-r["months"], -r["total_paise"], r["name"]),
    )[:TOP]
    waiting = sum(
        i["role"] == "uncertain" or (i["role"] == "payback" and i["role_basis"] != "owner")
        for _, i in found
    )
    return {
        "days": days,
        "per_day_paise": spent // days,
        "payments": len(found),
        "biggest": None
        if biggest is None
        else {
            "id": biggest[1]["id"],
            "name": name_of(biggest[1]),
            "amount_paise": biggest[0].amount_paise,
            "time_utc": biggest[1]["time_utc"],
        },
        "busiest_weekday": None
        if busiest is None
        else {"day": WEEKDAYS[busiest[0]], "count": busiest[1]},
        "ways_bp": {way: share(by_way[way], paid) for way in ("upi", "card", "other")},
        "regular": regular,
        "waiting": {
            "count": waiting,
            "amount_paise": sum(b["to_confirm_paise"] for b in bars),
        },
    }


@router.get("/analytics", dependencies=v1.Fresh)
def analytics(
    owner: v1.Owner,
    session: v1.Db,
    start: Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="IST month")],
    end: Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="IST month")],
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    months = month_list(start, end)
    base = cheap_etag(session, owner, None)
    etag = '"a-' + hashlib.sha256(f"{base}|{start}|{end}".encode()).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if if_none_match and etag in (t.strip().removeprefix("W/") for t in if_none_match.split(",")):
        return Response(status_code=304, headers=headers)
    body = canonical(build(session, owner, months))
    return Response(body, media_type="application/json", headers=headers)
