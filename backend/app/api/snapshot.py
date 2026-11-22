"""GET /api/v1/sync/snapshot: everything the app shows, in one document (D-088).

The phone keeps it as its local copy (D-089) and renders every screen from it. Every money
figure in it is worked out here, from the same functions as the other /api/v1 routes, so the
app never adds up money itself. The ETag is the SHA-256 of the canonical JSON without
`generated_at`, so the same data always has the same ETag; If-None-Match on it gives 304.
"""

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import select

from app.api import devices, users, v1
from app.api.auth import Caller, current_owner, current_user
from app.engine.categorise import UNCATEGORISED
from app.engine.credits import PaybackRow, payback_links
from app.engine.reconcile import IST, counted
from app.models import AppUser, Label, OwnerLinkDecision, Transaction, TxnDerived, TxnLink
from app.pipeline import owner_actions, statement, version
from app.pipeline.recompute import VERSIONS

SCHEMA_VERSION = 1
RING_SLICES = 6  # the ring shows the 6 biggest categories, the rest as one "Other"

router = APIRouter(prefix="/api/v1", dependencies=[Depends(current_owner)])


def spent_effect(item: dict, invest: bool = False) -> int:
    """Signed effect on Spent: a refund lowers it; other roles are in no Spent (an investment
    debit is, when the owner's setting counts investments, D-136)."""
    total, sign = counted(item["role"], item["direction"], invest) or ("", 0)
    return item["amount_paise"] * sign if total == "spent" else 0


def name_of(item: dict) -> str:
    """The name the app shows for a row, also when the bank gave none (common.ts nameOf)."""
    if item["display_name"]:
        return item["display_name"]
    if item["category"] == "cash":
        return "Cash withdrawal"
    return "Bank transfer in" if item["direction"] == "credit" else "Bank transfer"


def _ist_month(time_utc: str) -> str:
    """The IST month of an item's time."""
    return datetime.fromisoformat(time_utc).astimezone(IST).strftime("%Y-%m")


def merchants(items: list[dict], invest: bool = False) -> dict[str, list[dict]]:
    """Category detail, "Paid to": per category, each name's Spent and number of rows."""
    groups: dict[str, dict[str, dict]] = defaultdict(dict)
    for item in items:
        name = name_of(item)
        g = groups[item["category"]].setdefault(name, {"name": name, "total_paise": 0, "count": 0})
        g["total_paise"] += spent_effect(item, invest)
        g["count"] += 1
    return {
        slug: sorted(names.values(), key=lambda g: (-g["total_paise"], g["name"]))
        for slug, names in groups.items()
    }


def is_person_item(item: dict) -> bool:
    """Money sent to a person (People spending) or got back from one (a payback)."""
    people = item["category"] == "people" and spent_effect(item) != 0
    return people or (item["direction"] == "credit" and item["role"] == "payback")


def person_key(item: dict) -> str:
    return item["person_id"] or f"name:{name_of(item)}"


def people(items: list[dict]) -> list[dict]:
    """The People ledger: per person Sent, Got back (confirmed paybacks), To confirm, Net.
    `items` are newest first; a person's name is the one on their newest row."""
    rows: dict[str, dict] = {}
    for item in filter(is_person_item, items):
        key = person_key(item)
        p = rows.setdefault(
            key,
            {"key": key, "name": name_of(item), "sent_paise": 0, "got_back_paise": 0,
             "to_confirm_paise": 0},
        )  # fmt: skip
        if item["role"] != "payback":
            p["sent_paise"] += spent_effect(item)
        elif item["role_basis"] == "owner":
            p["got_back_paise"] += item["amount_paise"]
        else:
            p["to_confirm_paise"] += item["amount_paise"]
    for p in rows.values():
        p["net_paise"] = p["sent_paise"] - p["got_back_paise"]
    return sorted(rows.values(), key=lambda p: (-p["sent_paise"], -p["got_back_paise"], p["name"]))


def chart(categories: list[dict]) -> dict:
    """The ring: the biggest categories above zero, and the rest as one "Other" slice."""
    positive = sorted(
        (c for c in categories if c["amount_paise"] > 0), key=lambda c: -c["amount_paise"]
    )
    shown = positive[:RING_SLICES] if len(positive) > RING_SLICES + 1 else positive
    slices = [
        {"slug": c["slug"], "name": c["name"], "amount_paise": c["amount_paise"]} for c in shown
    ]
    rest = positive[len(shown) :]
    if rest:
        amount = sum(c["amount_paise"] for c in rest)
        slices.append({"slug": None, "name": f"Other ({len(rest)})", "amount_paise": amount})
    return {"total_paise": sum(c["amount_paise"] for c in positive), "slices": slices}


def changes(summary: dict) -> dict:
    """Spent and each category against the month before (summary["previous"])."""
    before = {c["slug"]: c["amount_paise"] for c in summary["previous"]["categories"]}
    return {
        "spent_paise": summary["spent_paise"] - summary["previous"]["spent_paise"],
        "categories": {
            c["slug"]: c["amount_paise"] - before.get(c["slug"], 0) for c in summary["categories"]
        },
    }


def todo_merchants(items: list[dict]) -> tuple[list[dict], int]:
    """Uncategorised spending by merchant name, biggest first, and the rows with no name."""
    groups: dict[str, dict] = {}
    unnamed = 0
    for item in items:
        if item["category"] != UNCATEGORISED or item["role"] not in ("spend", "card_bill_counted"):
            continue
        if not item["display_name"]:
            unnamed += 1
            continue
        g = groups.setdefault(
            item["display_name"],
            {
                "name": item["display_name"],
                "total_paise": 0,
                "count": 0,
                "txn_id": item["id"],
                "last_time_utc": item["time_utc"],
            },  # items are newest first
        )
        g["total_paise"] += item["amount_paise"]
        g["count"] += 1
    # Newest payment first, then the higher id (5B-1): `items` are in that order, so each
    # group was made at its newest payment and the groups are already in order.
    return list(groups.values()), unnamed


def upi_ids(session, owner) -> dict[int, str]:
    """Each transaction's UPI ID, masked or not, from its merchant key (D-145)."""
    rows = session.execute(
        select(TxnDerived.transaction_id, TxnDerived.merchant_key).where(
            TxnDerived.owner_id == owner, TxnDerived.merchant_key.like("vpa:%")
        )
    )
    return {i: key.removeprefix("vpa:") for i, key in rows}


def paybacks(items: list[dict], vpas: dict[int, str] | None = None) -> list[dict]:
    """Which payment each payback pays back (D-134), for the transaction sheet. Display only:
    Paid back is the sum of confirmed paybacks, linked or not. `vpas`: UPI IDs, so a masked
    sender meets the payee whose full UPI ID fits it (D-145)."""
    vpas = vpas or {}
    rows = [
        PaybackRow(
            i["id"], i["direction"], i["amount_paise"], datetime.fromisoformat(i["time_utc"]),
            i["person_id"], i["role"], vpas.get(i["id"]),
        )
        for i in items
    ]  # fmt: skip
    return [{"debit": x.debit, "credit": x.credit, "status": x.status} for x in payback_links(rows)]


def transfers(session, owner) -> list[dict]:
    """Moved between your accounts? (D-115): the engine's self-transfer candidates no owner
    answered yet, newest first. Amount, banks and times: the legs are in `transactions`."""
    answered = {
        (a, b)
        for a, b in session.execute(
            select(OwnerLinkDecision.txn_a, OwnerLinkDecision.txn_b).where(
                OwnerLinkDecision.owner_id == owner, OwnerLinkDecision.kind == "self_transfer"
            )
        )
    }
    links = session.execute(
        select(TxnLink.txn_a, TxnLink.txn_b).where(
            TxnLink.owner_id == owner,
            TxnLink.kind == "self_transfer",
            TxnLink.status == "candidate",
        )
    ).all()
    ids = {i for pair in links for i in pair}
    legs = {
        t.id: t
        for t in session.scalars(select(Transaction).where(Transaction.id.in_(ids)))
    } if ids else {}  # fmt: skip
    out = []
    for a, b in links:
        if (a, b) in answered or a not in legs or b not in legs:
            continue
        debit, credit = (legs[a], legs[b]) if legs[a].direction == "debit" else (legs[b], legs[a])
        out.append({
            "debit": debit.id,
            "credit": credit.id,
            "amount_paise": debit.amount_paise,
            "from_bank": debit.bank,
            "to_bank": credit.bank,
            "debit_time_utc": v1._iso(debit.txn_time_utc),
            "credit_time_utc": v1._iso(credit.txn_time_utc),
        })  # fmt: skip
    when = {x["debit"]: legs[x["debit"]].txn_time_utc for x in out}  # times, not their text
    return sorted(out, key=lambda x: (when[x["debit"]], x["debit"]), reverse=True)


def build(session, owner, caller: Caller | None = None) -> dict:
    """The snapshot document, without `generated_at`. `caller`: whose login asks (5C)."""
    stale, last = v1.freshness(session, owner)
    names = statement.owner_names(session, owner)
    found = v1._suggestions(session, owner, names)
    inv = v1.investments(session, owner, found)
    query = v1._items(owner).order_by(Transaction.txn_time_utc.desc(), Transaction.id.desc())
    items = [v1._item(owner, *row, inv) for row in session.execute(query)]
    by_month: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_month[_ist_month(item["time_utc"])].append(item)
    months = []
    for month in sorted(by_month):
        s = v1.month_summary(session, owner, month, stale, last, inv)
        mine = by_month[month]
        months.append({
            "month": month,
            "summary": s,
            "changes": changes(s),
            "chart": chart(s["categories"]),
            "merchants": merchants(mine, inv.in_spent),
            "people": people(mine),
        })  # fmt: skip
    senders = v1.senders(owner, session, "all")
    todo, unnamed = todo_merchants(items)
    label_ids = session.scalars(
        select(Label.id).where(Label.owner_id == owner).order_by(Label.name)
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "owner_id": str(owner),
        "engine_versions": dict(VERSIONS),
        "months": months,
        "transactions": items,
        "todo": {
            "senders": [s for s in senders if s["status"] == "to_confirm"],
            "answered": [s for s in senders if s["status"] != "to_confirm"],
            "merchants": todo,
            "unnamed": unnamed,
            "transfers": transfers(session, owner),
            "suggestions": v1.suggestions(session, owner, names, found),
        },
        # 5B-1 (D-134): payback -> the payment it pays back, linked or a candidate.
        "paybacks": paybacks(items, upi_ids(session, owner)),
        "profile": {
            "names": list(names),
            "settings": owner_actions.owner_settings(session, owner),  # D-136
            # Premium A.2: how many payments and which days they span (newest first).
            "data": {
                "payments": len(items),
                "first_utc": items[-1]["time_utc"] if items else None,
                "last_utc": items[0]["time_utc"] if items else None,
            },
        },
        # 5A (D-122, D-124): the phones that upload bank SMS, and where a first scan starts.
        "devices": devices.devices_of(session, owner),
        "sms": {"newest_utc": devices.newest_sms(session, owner)},
        "labels": [v1.label_detail(owner, session, i) for i in label_ids],
        "people": v1.people_directory(session, owner),
        "categories": v1.categories(owner),
    } | account(session, caller)


def account(session, caller: Caller | None) -> dict:
    """5C (D-128, D-129): the login's role; for the admin, the invites and the members."""
    if caller is None:
        return {}
    row = session.get(AppUser, caller.auth_uid)
    out: dict = {
        "account": {
            "role": caller.role,
            "email": caller.claims.get("email"),
            "since_utc": users._iso(row.created_at) if row else None,  # premium A.2
        }
    }
    if caller.admin:
        out["admin"] = {
            "invites": users.invites_of(session, caller.owner_id),
            "members": users.members(session),
        }
    return out


def cheap_etag(session, owner, caller: Caller | None) -> str:
    """The snapshot's ETag without building it (5B-2, D-140): the owner's data version (raised
    by every write, upload, import and recompute), the IST day (last month's comparison is
    cut at today), the engine and schema versions, and this login's account block (for the
    admin it holds every member's last sync, which other people's use changes)."""
    parts = {
        "version": version.current(session, owner),
        "day": v1._now().astimezone(IST).strftime("%Y-%m-%d"),
        "engines": dict(VERSIONS),
        "schema": SCHEMA_VERSION,
        "account": account(session, caller),
    }
    return '"v-' + hashlib.sha256(canonical(parts)).hexdigest() + '"'


def canonical(document: dict) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def etag_of(document: dict) -> str:
    return '"' + hashlib.sha256(canonical(document)).hexdigest() + '"'


@router.get("/sync/snapshot", dependencies=v1.Fresh)
def snapshot(
    owner: v1.Owner,
    caller: Annotated[Caller, Depends(current_user)],
    session: v1.Db,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    # 5B-2 (D-140): the ETag comes before the document, so an unchanged copy costs a few
    # small reads (the version, the account block) instead of the whole build.
    etag = cheap_etag(session, owner, caller)
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if if_none_match and etag in (t.strip().removeprefix("W/") for t in if_none_match.split(",")):
        return Response(status_code=304, headers=headers)
    document = build(session, owner, caller)
    body = canonical({**document, "generated_at": v1._iso(v1._now())})
    return Response(body, media_type="application/json", headers=headers)
