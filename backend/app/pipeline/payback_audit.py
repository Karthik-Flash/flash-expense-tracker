"""Silent paybacks (D-099): owner parties of kind person that no owner answer made.

Before 4E, setting a default category ("All from") on a person-like text made a party of
kind person. Kind person is the owner's Friend answer, so that party's credits became
owner-confirmed paybacks (CR_person_party) and lowered Net although the owner never said
who the sender was (D-076 says Paid back is owner-confirmed only).

"Silent" (corrected in 4F-B): kind person, no income label, not from the owner file, a
default category set, and no explicit answer. An explicit answer is either
  - `parties.answered_at` (every Friend or Family answer since 4F-B sets it), or
  - an answer the app sent with an Idempotency-Key since 4B-2: a stored client_ops row
    "PUT /api/v1/senders/<id>" that succeeded, for the sender this party now is.
A Friend answer sets no category, so a Friend party without one is never listed either.
What is left is a party a Friend answer from before 4B-2 (or from the terminal) made and
that also has a category; it cannot be told apart. After the fix its credits are To
confirm again, and one Friend tap brings them back.

The fix sets such a party to kind unsure (no answer): its texts, name and default category
stay, rows are never deleted, and its source becomes "terminal" (this owner command). The
credits then follow the merchant rules: To confirm, never subtracted. Net never goes down.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.reconcile import IST
from app.models import ClientOp, Party, Transaction, TxnDerived
from app.pipeline.owner_actions import senders

RULE = (
    "silent: a person party with no income label, not from the owner file, a default category "
    '(made by "All from" before 4E) and no explicit Friend or Family answer'
)
SENDER_PATH = "/api/v1/senders/"


@dataclass
class Audit:
    parties: list[Party]
    credits: int = 0
    months: list[str] = field(default_factory=list)  # IST month keys of those credits


def answered_in_app(session: Session, owner_id: uuid.UUID) -> set[int]:
    """Parties whose sender got an answer the app stored with its key (PUT, 2xx)."""
    answered = {
        path.removeprefix(SENDER_PATH)
        for path in session.scalars(
            select(ClientOp.path).where(
                ClientOp.owner_id == owner_id,
                ClientOp.method == "PUT",
                ClientOp.path.startswith(SENDER_PATH),
                ClientOp.status_code >= 200,
                ClientOp.status_code < 300,
            )
        )
    }
    if not answered:
        return set()
    return {s.party_id for s in senders(session, owner_id) if s.party_id and s.id in answered}


def silent_parties(session: Session, owner_id: uuid.UUID) -> list[Party]:
    found = session.scalars(
        select(Party)
        .where(
            Party.owner_id == owner_id,
            Party.kind == "person",
            Party.income_label.is_(None),
            Party.source != "file",
            Party.category.is_not(None),
            Party.answered_at.is_(None),
        )
        .order_by(Party.id)
    ).all()
    explicit = answered_in_app(session, owner_id) if found else set()
    return [p for p in found if p.id not in explicit]


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
