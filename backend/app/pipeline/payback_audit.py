"""Silent paybacks (D-099, D-111): owner parties of kind person that no owner answer made.

Before 4E, setting a default category ("All from") on a person-like text made a party of
kind person. Kind person is the owner's Friend answer, so that party's credits became
owner-confirmed paybacks (CR_person_party) and lowered Net although the owner never said
who the sender was (D-076 says Paid back is owner-confirmed only).

"Silent" (D-111): kind person, no income label, not from the owner file, a default
category set, and no owner sender answer (Friend, Family or Income) on record from any
source. On record means one of
  - `parties.answered_at` (every Friend or Family answer since 4F-B, app or terminal);
  - an app answer with an Idempotency-Key (since 4B-2): the newest stored client_ops row
    for "/api/v1/senders/<id>", for the sender this party now is, is a 2xx PUT that is not
    Ignore (an "Ask me again later" DELETE after it forgets it);
  - an owner role decision Paid back or Income on one of its credits (app, terminal or
    owner file).
A Friend answer sets no category, so a Friend party without one is never listed either.
Answers from before 4B-2 (app) or 4F-B (terminal) left no record; such a party is still
listed, and one Friend tap brings its credits back.

The fix sets such a party to kind unsure (no answer): its texts, name and default category
stay, rows are never deleted, and its source becomes "terminal" (this owner command). The
credits then follow the merchant rules: To confirm, never subtracted. Net never goes down.

The restore (--restore) undoes the fix for a party the rule no longer calls silent: kind
unsure with source terminal (what the fix leaves), no income label, a category, and a
Friend answer on record (answered_at, or a stored app Friend answer). The fix only ever
turns kind person into unsure, so person is the kind it had. A party with only role
decisions on some credits is not restored: kind person would count all its credits as
Paid back.
"""

import uuid
from dataclasses import dataclass, field
from urllib.parse import unquote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.ops import request_hash
from app.engine.reconcile import IST
from app.models import ClientOp, OwnerRole, Party, Transaction, TxnDerived
from app.pipeline.owner_actions import senders

RULE = (
    "silent: a person party with no income label, not from the owner file, a default category "
    '(made by "All from" before 4E) and no Friend, Family or Income answer on record'
)
SENDER_PATH = "/api/v1/senders/"
FRIEND = {"answer": "friend", "label": None}
IGNORE = {"answer": "ignore", "label": None}


@dataclass
class Audit:
    parties: list[Party]
    credits: int = 0
    months: list[str] = field(default_factory=list)  # IST month keys of those credits


def app_answers(session: Session, owner_id: uuid.UUID) -> dict[int, str]:
    """Party id -> "friend" or "answer": the newest stored app write for its sender (2xx) is
    a PUT that is not Ignore. A later DELETE ("Ask me again later") forgets it."""
    rows = session.execute(
        select(ClientOp.method, ClientOp.path, ClientOp.request_hash)
        .where(
            ClientOp.owner_id == owner_id,
            ClientOp.path.startswith(SENDER_PATH),
            ClientOp.status_code >= 200,
            ClientOp.status_code < 300,
        )
        .order_by(ClientOp.completed_at, ClientOp.received_at)
    ).all()
    newest: dict[str, tuple[str, str, str]] = {}
    for method, path, digest in rows:
        newest[unquote(path.removeprefix(SENDER_PATH))] = (method, path, digest)
    found: dict[str, str] = {}
    for sender_id, (method, path, digest) in newest.items():
        if method != "PUT" or digest == request_hash("PUT", path, IGNORE):
            continue
        found[sender_id] = "friend" if digest == request_hash("PUT", path, FRIEND) else "answer"
    if not found:
        return {}
    return {
        s.party_id: found[s.id] for s in senders(session, owner_id) if s.party_id and s.id in found
    }


def answered(session: Session, owner_id: uuid.UUID) -> set[int]:
    """Parties with a Friend, Family or Income answer on record, from any source."""
    on_record = set(
        session.scalars(
            select(Party.id).where(Party.owner_id == owner_id, Party.answered_at.is_not(None))
        )
    )
    on_record |= set(
        session.scalars(
            select(TxnDerived.party_id)
            .join(OwnerRole, OwnerRole.transaction_id == TxnDerived.transaction_id)
            .where(
                OwnerRole.owner_id == owner_id,
                OwnerRole.role.in_(("payback", "income")),
                TxnDerived.party_id.is_not(None),
            )
        )
    )
    return on_record | set(app_answers(session, owner_id))


def silent_parties(session: Session, owner_id: uuid.UUID) -> list[Party]:
    found = session.scalars(
        select(Party)
        .where(
            Party.owner_id == owner_id,
            Party.kind == "person",
            Party.income_label.is_(None),
            Party.source != "file",
            Party.category.is_not(None),
        )
        .order_by(Party.id)
    ).all()
    explicit = answered(session, owner_id) if found else set()
    return [p for p in found if p.id not in explicit]


def restorable(session: Session, owner_id: uuid.UUID) -> list[Party]:
    """Parties as an earlier --fix --apply left them that have a Friend answer on record."""
    found = session.scalars(
        select(Party)
        .where(
            Party.owner_id == owner_id,
            Party.kind == "unsure",
            Party.source == "terminal",
            Party.income_label.is_(None),
            Party.category.is_not(None),
        )
        .order_by(Party.id)
    ).all()
    if not found:
        return []
    friends = {i for i, how in app_answers(session, owner_id).items() if how == "friend"}
    return [p for p in found if p.answered_at is not None or p.id in friends]


def credits_of(session: Session, owner_id: uuid.UUID, ids: list[int]) -> int:
    """Active credits matched to these parties."""
    if not ids:
        return 0
    return len(
        session.scalars(
            select(Transaction.id)
            .join(TxnDerived, TxnDerived.transaction_id == Transaction.id)
            .where(
                Transaction.owner_id == owner_id,
                Transaction.status == "active",
                Transaction.type == "credit",
                TxnDerived.party_id.in_(ids),
            )
        ).all()
    )


def audit(session: Session, owner_id: uuid.UUID) -> Audit:
    """Counts only: the silent parties, their credits counted as Paid back, and the months."""
    parties = silent_parties(session, owner_id)
    ids = [p.id for p in parties]
    times = session.scalars(
        select(Transaction.txn_time_utc)
        .join(TxnDerived, TxnDerived.transaction_id == Transaction.id)
        .where(
            Transaction.owner_id == owner_id,
            Transaction.status == "active",
            TxnDerived.party_id.in_(ids),
            TxnDerived.role == "payback",
            TxnDerived.role_rule == "CR_person_party",
        )
    ).all()
    months = sorted({t.astimezone(IST).strftime("%Y-%m") for t in times})
    return Audit(parties, len(times), months)


def fix(session: Session, owner_id: uuid.UUID) -> int:
    """Each silent party becomes kind unsure, written by this owner command. Does not
    commit: the caller's recompute commits it with the derived rows."""
    parties = silent_parties(session, owner_id)
    for party in parties:
        party.kind, party.source = "unsure", "terminal"
    session.flush()
    return len(parties)


def restore(session: Session, owner_id: uuid.UUID) -> int:
    """Each restorable party gets kind person back (the Friend answer on record). Does not
    commit: the caller's recompute commits it."""
    parties = restorable(session, owner_id)
    for party in parties:
        party.kind = "person"
    session.flush()
    return len(parties)
