"""The owner's bank statement against the app (D-114) and payer names from it (D-116).

The owner runs both commands on their own files; nothing here keeps a statement. The pure
parts live in the engine (statement_hdfc reads, statement_check matches); this module reads
the app's side from the database and writes the approved names.
"""

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.merchant import parts
from app.engine.reconcile import COUNTED, IST, upi_reference
from app.engine.statement_check import AppRow
from app.engine.statement_hdfc import Row
from app.models import LABEL_MAX, Party, Transaction, TxnDerived
from app.pipeline.owner_actions import party_for

BANK = "HDFC"


def _utc(day: date) -> datetime:
    return datetime.combine(day, time(), IST)


def app_rows(session: Session, owner_id: uuid.UUID, first: date, last: date) -> list[AppRow]:
    """The app's active HDFC transactions on these IST days, any role but duplicate."""
    t, d = Transaction, TxnDerived
    rows = session.execute(
        select(
            t.id,
            t.txn_time_utc,
            t.direction,
            t.amount_paise,
            t.reference,
            t.account_last4,
            t.channel,
        )  # fmt: skip
        .join(d, d.transaction_id == t.id)
        .where(
            t.owner_id == owner_id,
            t.status == "active",
            t.bank == BANK,
            d.role != "duplicate",
            t.txn_time_utc >= _utc(first),
            t.txn_time_utc < _utc(last + timedelta(days=1)),
        )
        .order_by(t.id)
    ).all()
    return [
        AppRow(
            i, when.astimezone(IST).date(), direction, amount, upi_reference(ref), last4, channel
        )
        for i, when, direction, amount, ref, last4, channel in rows
    ]


@dataclass(frozen=True)
class MonthTotals:
    spent_paise: int
    paid_back_paise: int

    @property
    def net_paise(self) -> int:
        return self.spent_paise - self.paid_back_paise


def month_totals(session: Session, owner_id: uuid.UUID, month: str) -> MonthTotals:
    """Spent and Paid back of one IST month as the app shows them (stored roles, D-076)."""
    year, number = int(month[:4]), int(month[5:7])
    start = _utc(date(year, number, 1))
    end = _utc(date(year + number // 12, number % 12 + 1, 1))
    rows = session.execute(
        select(TxnDerived.role, TxnDerived.role_basis, Transaction.amount_paise)
        .join(Transaction, Transaction.id == TxnDerived.transaction_id)
        .where(
            TxnDerived.owner_id == owner_id,
            Transaction.status == "active",
            Transaction.txn_time_utc >= start,
            Transaction.txn_time_utc < end,
        )
    )
    sums = Counter()
    for role, basis, amount in rows:
        if role in COUNTED:
            total, sign = COUNTED[role]
            if total == "paid_back" and basis != "owner":
                continue  # To confirm: shown, never subtracted
            sums[total] += sign * amount
    return MonthTotals(sums["spent"], sums["paid_back"])


# --- statement-names (D-116) ------------------------------------------------------


def nameless(counterparty: str | None) -> bool:
    """A UPI ID with no name beside it, or a masked one ("*k77@okhdfcbank")."""
    p = parts(counterparty)
    return bool(p and p.vpa and (not p.tokens or "*" in p.vpa))


def usable_name(name: str | None) -> str | None:
    """The statement's payer name, tidied, when it can be a name (letters, at most 30)."""
    text = " ".join((name or "").split())
    if not any(c.isalpha() for c in text) or text.casefold() in {"na", "n a", "null", "upi"}:
        return None
    return text[:LABEL_MAX]


@dataclass
class NamePlan:
    credits: int = 0  # app UPI credits with no name, matched to a statement row by reference
    named: int = 0  # of those, the statement gave a usable name
    already_named: int = 0  # parties the owner (or the file) named: left alone
    conflicts: int = 0  # parties that got two different names: left alone
    shared_names: int = 0  # names that two or more parties would get: no join, reported
    # party key -> (name, one transaction of the party): what --apply writes
    proposals: dict[tuple[str, object], tuple[str, int]] = field(default_factory=dict)
    # (counterparty as the bank wrote it, name): for --show only (PRIVATE)
    pairs: list[tuple[str, str]] = field(default_factory=list)


def plan_names(session: Session, owner_id: uuid.UUID, rows: list[Row]) -> NamePlan:
    """Names for nameless UPI credits, from statement rows with the same 12-digit reference."""
    by_ref = {
        r.ref12: r for r in rows if r.channel == "upi" and r.direction == "credit" and r.ref12
    }
    t, d = Transaction, TxnDerived
    found = session.execute(
        select(t.id, t.reference, t.counterparty_raw, d.party_id, d.merchant_key)
        .join(d, d.transaction_id == t.id)
        .where(
            t.owner_id == owner_id,
            t.status == "active",
            t.bank == BANK,
            t.direction == "credit",
            t.channel == "upi",
        )
        .order_by(t.id)
    ).all()
    plan = NamePlan()
    wanted: dict[tuple[str, object], set[str]] = defaultdict(set)
    first_txn: dict[tuple[str, object], int] = {}
    for txn_id, ref, raw, party_id, key in found:
        row = by_ref.get(upi_reference(ref) or "")
        if row is None or not nameless(raw):
            continue
        plan.credits += 1
        name = usable_name(row.name)
        if name is None:
            continue
        plan.named += 1
        party = session.get(Party, party_id) if party_id is not None else None
        if party is not None and party.display_name:
            plan.already_named += 1
            continue
        target = ("party", party_id) if party_id is not None else ("key", key)
        wanted[target].add(name)
        first_txn.setdefault(target, txn_id)
        plan.pairs.append((raw or "", name))
    by_name: Counter[str] = Counter()
    for target, names in wanted.items():
        if len(names) > 1:
            plan.conflicts += 1
            continue
        name = next(iter(names))
        plan.proposals[target] = (name, first_txn[target])
        by_name[name.casefold()] += 1
    plan.shared_names = sum(1 for n in by_name.values() if n > 1)
    return plan


def apply_names(session: Session, owner_id: uuid.UUID, plan: NamePlan) -> int:
    """Write the proposals as owner data (name_source "statement"); never over a name. Does
    not commit: the caller's recompute commits it."""
    changed = 0
    for name, txn_id in plan.proposals.values():
        party = party_for(session, owner_id, txn_id, "terminal")
        if party.display_name:  # named in the meantime: the owner's name stays
            continue
        party.display_name, party.name_source = name, "statement"
        changed += 1
    session.flush()
    return changed
