"""Derived storage: read the inputs, call the pure derive(), write only what changed.

    derived = f(active transactions, owner tables, recorded pairs, engine versions)

Reconcile gives every transaction a role and the links; Categorise then gives it a
category.

txn_derived, txn_links and derive_runs are written only here. The owner tables are
only read. Everything happens in one database transaction, so a failure leaves the
previous state whole. A run that would change nothing writes nothing, not even a
derive_runs row: the derived tables always match the last done run.

A changed row is replaced, and rows are written 1000 to a statement, so the number
of statements barely grows with the data or with how much changed: eleven reads
and, up to 1000 changed rows, five writes. Against a remote database that is a few
round trips.
A link is identified by its kind and its two transactions; its id changes when it does.
"""

import threading
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, insert, select, text
from sqlalchemy.orm import Session

from app.engine import reconcile
from app.engine.categorise import CATEGORISE_VERSION, Categorised, categorise
from app.engine.merchant import MERCHANT_VERSION
from app.engine.reconcile import OwnerData, Result, Txn, derive
from app.models import (
    DeriveRun,
    DuplicateCandidate,
    OwnAccount,
    OwnerCategory,
    OwnerLinkDecision,
    OwnerRole,
    OwnIdentifier,
    Party,
    PartyText,
    Transaction,
    TxnDerived,
    TxnLink,
)

# The engine versions a run is made with; a run records them (derive_runs.versions).
VERSIONS = reconcile.VERSIONS | {"categorise": CATEGORISE_VERSION}
CHUNK = 5000  # ids per DELETE ... IN (...)
_LOCKS: defaultdict[uuid.UUID, threading.RLock] = defaultdict(threading.RLock)
_GUARD = threading.Lock()
ROWS = 1000  # rows per INSERT ... VALUES (...), (...): one statement, one round trip

Changes = tuple[list[dict], list[dict], list[int]]  # rows to insert, rows to update, ids to delete


class OwnerDataError(Exception):
    """The owner data cannot hold. The message is the engine's and never holds a value."""


@dataclass
class Plan:
    """A fresh derive next to what is stored. Building it reads only."""

    txns: list[Txn]
    owner: OwnerData
    legacy: set[tuple[int, int]]
    result: Result
    categories: dict[int, Categorised]
    last_run_id: int | None  # the last done run, if any
    last_versions: dict | None  # the engine versions that run was made with
    derived: Changes
    links: Changes
    lost_matches: int  # transactions whose stored party or own account would go or change

    @property
    def changes(self) -> int:
        return sum(len(part) for group in (self.derived, self.links) for part in group)

    @property
    def merchant_changed(self) -> bool:
        """The stored rows were made by another merchant engine version."""
        return (
            self.last_versions is not None
            and self.last_versions.get("merchant") != MERCHANT_VERSION
        )


@dataclass
class Outcome:
    status: str  # done, unchanged, dry_run or stopped
    plan: Plan
    run_id: int | None
    seconds: float


def active_txns(session: Session, owner_id: uuid.UUID) -> list[Txn]:
    """The owner's active transactions as Reconcile input."""
    t = Transaction
    rows = session.execute(
        select(
            t.id,
            t.bank,
            t.type,
            t.direction,
            t.amount_paise,
            t.account_last4,
            t.channel,
            t.counterparty_raw,
            t.txn_time_utc,
            t.hints,
            t.reference,
        ).where(t.owner_id == owner_id, t.status == "active")
    )
    return [Txn(*row[:9], tuple(row[9] or ()), row[10]) for row in rows]


def load_owner(
    session: Session, owner_id: uuid.UUID
) -> tuple[OwnerData, list[OwnAccount], list[Party]]:
    """The owner tables as engine input, plus the rows behind each position."""
    accounts = list(
        session.scalars(
            select(OwnAccount).where(OwnAccount.owner_id == owner_id).order_by(OwnAccount.id)
        )
    )
    parties = list(
        session.scalars(select(Party).where(Party.owner_id == owner_id).order_by(Party.id))
    )
    last4: dict[int, list[str]] = {}
    texts: dict[int, list[str]] = {}
    for row in session.execute(
        select(OwnIdentifier.own_account_id, OwnIdentifier.kind, OwnIdentifier.value)
        .where(OwnIdentifier.owner_id == owner_id)
        .order_by(OwnIdentifier.id)
    ):
        (last4 if row.kind == "last4" else texts).setdefault(row.own_account_id, []).append(
            row.value
        )
    party_texts: dict[int, list[str]] = {}
    for row in session.execute(
        select(PartyText.party_id, PartyText.text)
        .where(PartyText.owner_id == owner_id)
        .order_by(PartyText.id)
    ):
        party_texts.setdefault(row.party_id, []).append(row.text)
    roles = dict(
        session.execute(
            select(OwnerRole.transaction_id, OwnerRole.role).where(OwnerRole.owner_id == owner_id)
        ).all()
    )
    d = OwnerLinkDecision
    links = {
        (kind, a, b): verdict
        for kind, a, b, verdict in session.execute(
            select(d.kind, d.txn_a, d.txn_b, d.verdict).where(d.owner_id == owner_id)
        )
    }
    owner = OwnerData(
        accounts=tuple(
            reconcile.OwnAccount(
                a.kind, a.bank, tuple(last4.get(a.id, ())), tuple(texts.get(a.id, ()))
            )
            for a in accounts
        ),
        parties=tuple(
            reconcile.Party(
                p.kind, p.income_label is not None, tuple(party_texts.get(p.id, ())), p.category
            )
            for p in parties
        ),
        roles=roles,
        links=links,
        categories=dict(
            session.execute(
                select(OwnerCategory.transaction_id, OwnerCategory.category).where(
                    OwnerCategory.owner_id == owner_id
                )
            ).all()
        ),
    )
    return owner, accounts, parties


def plan(session: Session, owner_id: uuid.UUID) -> Plan:
    """Derive afresh and compare with the stored rows. Reads only."""
    txns = active_txns(session, owner_id)
    owner, accounts, parties = load_owner(session, owner_id)
    recorded = session.execute(select(DuplicateCandidate.txn_a, DuplicateCandidate.txn_b))
    legacy = {(min(a, b), max(a, b)) for a, b in recorded}
    try:
        result = derive(txns, owner, legacy)
        categories = categorise(txns, owner, result)
    except ValueError as exc:  # owner data that cannot hold: engine messages hold no values
        raise OwnerDataError(str(exc)) from None

    fresh = {}
    for t in txns:
        d, m, c = result.roles[t.id], result.merchants[t.id], categories[t.id]
        party = None if d.party is None else parties[d.party]
        fresh[t.id] = {
            "transaction_id": t.id,
            "owner_id": owner_id,
            "merchant_key": m.merchant_key,
            "merchant_kind": party.kind if party else m.kind,
            "merchant_confidence": "high" if party else m.confidence,
            "display_name": party.label if party else m.display_name,
            "brand_id": m.brand_id,
            "merchant_reasons": list(m.reasons),
            "party_id": party.id if party else None,
            "own_account_id": None if d.own_account is None else accounts[d.own_account].id,
            "role": d.role,
            "role_rule": d.rule,
            "role_basis": d.basis,
            "role_reasons": list(d.reasons),
            "duplicate_of": d.duplicate_of,
            "category": c.category,
            "category_rule": c.rule,
            "category_basis": c.basis,
        }
    stored = {
        row.transaction_id: dict(row._mapping)
        for row in session.execute(
            select(TxnDerived.__table__).where(TxnDerived.owner_id == owner_id)
        )
    }
    lost = sum(
        any(old[c] is not None and old[c] != fresh[i][c] for c in ("party_id", "own_account_id"))
        for i, old in stored.items()
        if i in fresh
    )
    derived: Changes = (
        [row for i, row in fresh.items() if i not in stored],
        [row for i, row in fresh.items() if i in stored and stored[i] != row],
        [i for i in stored if i not in fresh],
    )

    fresh_links = {
        (x.kind, x.txn_a, x.txn_b): {
            "owner_id": owner_id,
            "kind": x.kind,
            "txn_a": x.txn_a,
            "txn_b": x.txn_b,
            "status": x.status,
            "rule": x.rule,
            "reason": x.reason,
            "decided_by": x.decided_by,
        }
        for x in result.links
    }
    stored_links = {
        (row.kind, row.txn_a, row.txn_b): dict(row._mapping)
        for row in session.execute(select(TxnLink.__table__).where(TxnLink.owner_id == owner_id))
    }
    links: Changes = (
        [row for key, row in fresh_links.items() if key not in stored_links],
        [
            row | {"id": stored_links[key]["id"]}
            for key, row in fresh_links.items()
            if key in stored_links and stored_links[key] != row | {"id": stored_links[key]["id"]}
        ],
        [row["id"] for key, row in stored_links.items() if key not in fresh_links],
    )
    last_run = session.scalar(
        select(DeriveRun)
        .where(DeriveRun.owner_id == owner_id, DeriveRun.status == "done")
        .order_by(DeriveRun.id.desc())
        .limit(1)
    )
    return Plan(
        txns,
        owner,
        legacy,
        result,
        categories,
        last_run.id if last_run else None,
        dict(last_run.versions) if last_run else None,
        derived,
        links,
        lost,
    )


@contextmanager
def owner_lock(session: Session, owner_id: uuid.UUID) -> Iterator[None]:
    """One writer per owner: a lock in this process, and on Postgres an advisory lock
    held until the session's transaction ends, so two processes queue as well.
    """
    with _GUARD:
        lock = _LOCKS[owner_id]
    with lock:
        if session.get_bind().dialect.name == "postgresql":
            key = int.from_bytes(owner_id.bytes[:8], "big", signed=True)
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        yield


def last_run_time(session: Session, owner_id: uuid.UUID) -> datetime | None:
    """When the last done recompute for this owner finished."""
    return session.scalar(
        select(DeriveRun.finished_at)
        .where(DeriveRun.owner_id == owner_id, DeriveRun.status == "done")
        .order_by(DeriveRun.id.desc())
        .limit(1)
    )


def stale_reason(p: Plan) -> str | None:
    """Why the stored rows do not match a fresh derive, or None."""
    if p.last_run_id is None:
        return "no recompute has run yet"
    if p.last_versions != VERSIONS:
        return "the stored rows were made by another engine version"
    if p.changes:
        return f"{p.changes} stored row(s) differ from the current data"
    return None


def recompute(
    session: Session,
    owner_id: uuid.UUID,
    trigger: str,
    *,
    dry_run: bool = False,
    accept_key_changes: bool = False,
) -> Outcome:
    """Bring the derived tables up to date in one transaction. Never writes an owner table.

    Stops without writing when the merchant engine changed since the stored run and a
    transaction would lose or change its owner match, unless accept_key_changes.
    """
    with owner_lock(session, owner_id):
        return _recompute(session, owner_id, trigger, dry_run, accept_key_changes)


def _recompute(
    session: Session, owner_id: uuid.UUID, trigger: str, dry_run: bool, accept_key_changes: bool
) -> Outcome:
    started, clock = datetime.now(UTC), time.monotonic()
    try:
        p = plan(session, owner_id)
        if p.merchant_changed and p.lost_matches and not accept_key_changes:
            status = "stopped"
        elif dry_run:
            status = "dry_run"
        elif not p.changes and p.last_versions == VERSIONS:
            status = "unchanged"
        else:
            status = "done"
        if status != "done":
            # Nothing derived to write. An owner answer written in this session still
            # commits (it may change nothing derived); a dry run or a stop writes nothing.
            session.commit() if status == "unchanged" else session.rollback()
            return Outcome(status, p, None, time.monotonic() - clock)

        for model, key, (inserts, updates, deletes) in (
            (TxnDerived, TxnDerived.transaction_id, p.derived),
            (TxnLink, TxnLink.id, p.links),
        ):
            stale = deletes + [row[key.name] for row in updates]
            for start in range(0, len(stale), CHUNK):
                session.execute(delete(model).where(key.in_(stale[start : start + CHUNK])))
            rows = inserts + [
                {k: v for k, v in row.items() if not (model is TxnLink and k == "id")}
                for row in updates
            ]
            for start in range(0, len(rows), ROWS):
                # One multi-row statement; an ORM bulk insert would split the rows by
                # which columns are null and so grow with the data.
                session.execute(insert(model.__table__).values(rows[start : start + ROWS]))
        run = DeriveRun(
            owner_id=owner_id,
            started_at=started,
            finished_at=datetime.now(UTC),
            status="done",
            trigger=trigger,
            versions=dict(VERSIONS),
            counts=run_counts(p),
        )
        session.add(run)
        session.flush()
        run_id = run.id
        session.commit()
        return Outcome("done", p, run_id, time.monotonic() - clock)
    except BaseException:
        session.rollback()
        raise


def run_counts(p: Plan) -> dict:
    """Counts only: what a run changed and what the derived data holds after it."""
    changed = ("inserted", "updated", "deleted")
    return {
        "transactions": len(p.txns),
        "txn_derived": dict(zip(changed, map(len, p.derived), strict=True)),
        "txn_links": dict(zip(changed, map(len, p.links), strict=True)),
        "roles": dict(sorted(Counter(d.role for d in p.result.roles.values()).items())),
        "categories": dict(sorted(Counter(c.category for c in p.categories.values()).items())),
        "links": dict(sorted(Counter(f"{x.kind} {x.status}" for x in p.result.links).items())),
    }
