"""The owner's bank statement against the app (D-114) and payer names from it (D-116).

The owner runs the commands on their own files. The pure parts live in the engine
(statement_hdfc reads, statement_check matches and gives causes); this module reads the
app's side from the database, writes the approved names, and imports the statement-only
rows (`statement-import --apply`, D-120): each becomes a raw message of source "statement"
with a parse result of the statement reader's version and, through the usual store, a
transaction with hint "statement". Its dedupe key is the SMS key when it has a 12-digit
reference, so the SMS that arrives later merges into it and replaces its fields.
"""

import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import ParsedMessage
from app.engine.merchant import parts
from app.engine.money import AmountError, to_paise
from app.engine.reconcile import COUNTED, IST, inferred_accounts, upi_reference
from app.engine.senders import bank_for
from app.engine.statement_check import AppRow, Context, check
from app.engine.statement_hdfc import STATEMENT_VERSION, Row
from app.models import (
    LABEL_MAX,
    OwnerName,
    ParseResult,
    Party,
    RawMessage,
    Transaction,
    TxnDerived,
)
from app.pipeline.dedupe import content_hash
from app.pipeline.owner_actions import party_for
from app.pipeline.recompute import active_txns
from app.pipeline.store import Counts, link_new

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


# --- statement context and import (D-120) -------------------------------------------------

_AMOUNT = re.compile(r"(?:Rs\.?|INR|\u20b9)\s?(\d[\d,]*(?:\.\d{1,2})?)", re.I)


def owner_names(session: Session, owner_id: uuid.UUID) -> tuple[str, ...]:
    return tuple(
        session.scalars(
            select(OwnerName.name).where(OwnerName.owner_id == owner_id).order_by(OwnerName.id)
        )
    )


def _amounts(body: str) -> frozenset[int]:
    out = set()
    for text in _AMOUNT.findall(body):
        try:
            out.add(to_paise(text.replace(",", "")))
        except AmountError:
            continue
    return frozenset(out)


def context(session: Session, owner_id: uuid.UUID, first: date, last: date) -> Context:
    """Owner names, own last 4s and the unread HDFC messages of these days (in memory only)."""
    own = frozenset(last4 for _, last4 in inferred_accounts(active_txns(session, owner_id)))
    rows = session.execute(
        select(RawMessage.sender_core, RawMessage.body, RawMessage.received_at)
        .join(ParseResult, ParseResult.raw_message_id == RawMessage.id)
        .where(
            RawMessage.owner_id == owner_id,
            RawMessage.source != "statement",
            ParseResult.is_current,
            ParseResult.status == "unknown",
            RawMessage.received_at >= _utc(first - timedelta(days=1)),
            RawMessage.received_at < _utc(last + timedelta(days=2)),
        )
    ).all()
    unread = tuple(
        (when.astimezone(IST).date(), amounts)
        for core, body, when in rows
        if bank_for(core) == BANK and (amounts := _amounts(body))
    )
    return Context(owner_names(session, owner_id), own, unread)


# Causes never imported: the SMS will be read once its template exists; the rest are no
# payment the app should hold (a reversal pair, a foreign charge kept out as today).
NOT_IMPORTED = frozenset({"sms_not_parsed", "reversed_or_failed", "foreign_currency",
                          "month_edge"})  # fmt: skip
ASK = frozenset({"own_or_internal", "investment_or_broking"})  # never spend without an answer
CHECK = frozenset({"likely_spend", "unknown", "no_sms"})  # debits shown with "Looks right?"
_CHANNEL = {"upi": "upi", "neft": "neft", "imps": "imps", "rtgs": "neft", "atm": "atm",
            "pos": "debit_card", "nach": "nach", "netbanking": "netbanking"}  # fmt: skip


@dataclass
class ImportPlan:
    rows: list[tuple[str, Row]] = field(default_factory=list)  # (cause, row) to import
    by_cause: Counter = field(default_factory=Counter)  # (month, cause) -> rows
    skipped: Counter = field(default_factory=Counter)  # cause -> rows not imported
    account_last4: str | None = None


def plan_import(session: Session, owner_id: uuid.UUID, rows: list[Row]) -> ImportPlan:
    """The statement-only rows and what each would become; counts only, nothing written."""
    app = app_rows(session, owner_id, rows[0].date, rows[-1].date)
    ctx = context(session, owner_id, rows[0].date, rows[-1].date)
    months = check(rows, app, ctx)
    plan = ImportPlan()
    on = Counter(a.account_last4 for a in app if a.account_last4)
    plan.account_last4 = on.most_common(1)[0][0] if on else None
    for key, m in months.items():
        for side, cause, row in m.unmatched:
            if side != "statement":
                continue
            plan.by_cause[key, cause] += 1
            if cause in NOT_IMPORTED:
                plan.skipped[cause] += 1
            else:
                plan.rows.append((cause, row))
    return plan


def _parsed(row: Row, cause: str, last4: str | None) -> ParsedMessage:
    hints = ["statement"]
    if row.direction == "debit" and cause in ASK:
        hints.append("statement_ask")
    if row.direction == "debit" and cause in CHECK:
        hints.append("statement_check")
    if row.channel == "charges":
        hints.append("bank_charge")
    channel = "fd" if cause == "fd" else _CHANNEL.get(row.channel)
    if row.channel == "upi":
        counterparty = " ".join(x for x in (row.name, row.vpa) if x) or None
    else:
        counterparty = row.narration[:200] or None
    return ParsedMessage(
        bank=BANK,
        template_id=f"stmt:{row.channel}",
        parser_version=STATEMENT_VERSION,
        type=row.direction,
        direction=row.direction,
        amount_paise=row.amount_paise,
        currency="INR",
        account_last4=last4,
        channel=channel,
        counterparty_raw=counterparty,
        reference=row.ref12,
        balance_paise=row.balance_paise,
        txn_time_utc=_utc(row.date) + timedelta(hours=12),  # the day is known, not the time
        time_inferred=True,
        hints=tuple(hints),
    )


def apply_import(session: Session, owner_id: uuid.UUID, plan: ImportPlan) -> Counts:
    """Write the planned rows; a row already imported is skipped (its content hash). Does
    not commit: the caller's recompute commits it."""
    counts = Counts()
    for cause, row in plan.rows:
        body = "|".join(str(x) for x in (row.date.isoformat(), row.narration, row.debit_paise,
                                         row.credit_paise, row.ref, row.balance_paise))  # fmt: skip
        received = _utc(row.date) + timedelta(hours=12)
        digest = content_hash("STATEMENT", body, received)
        exists = select(RawMessage.id).where(
            RawMessage.owner_id == owner_id, RawMessage.content_hash == digest
        )
        if session.scalar(exists) is not None:
            counts.raw_duplicate += 1
            continue
        raw = RawMessage(owner_id=owner_id, source="statement", sender_raw="HDFC statement",
                         sender_core="STATEMENT", body=body, received_at=received,
                         content_hash=digest)  # fmt: skip
        session.add(raw)
        session.flush()
        counts.raw_new += 1
        parsed = _parsed(row, cause, plan.account_last4)
        result = ParseResult(raw_message_id=raw.id, parser_version=STATEMENT_VERSION,
                             status="parsed", is_current=True, bank=BANK,
                             template_id=parsed.template_id, type=parsed.type,
                             direction=parsed.direction, amount_paise=parsed.amount_paise,
                             currency="INR", account_last4=parsed.account_last4,
                             channel=parsed.channel, counterparty_raw=parsed.counterparty_raw,
                             reference=parsed.reference, balance_paise=parsed.balance_paise,
                             txn_time_utc=parsed.txn_time_utc, time_inferred=True,
                             hints=list(parsed.hints))  # fmt: skip
        session.add(result)
        session.flush()
        link_new(session, owner_id, raw, result, parsed, counts)
    return counts
