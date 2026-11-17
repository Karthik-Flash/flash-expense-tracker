"""Owner answers from the app or the terminal: one place, used by the API and the CLI.

Each function writes owner rows with the caller's source and does not commit: the caller
runs one recompute, which commits the answer and the derived rows together (or nothing).
Errors never hold a value from the data.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.engine.categorise import CATEGORIES
from app.engine.credits import SENDER_ROLES, CreditRow, Sender, credit_senders
from app.models import (
    Label,
    OwnerCategory,
    OwnerRole,
    Party,
    PartyText,
    Transaction,
    TxnDerived,
    TxnLabel,
)

ANSWERS = ("friend", "income", "ignore")
SCOPES = ("merchant", "transaction")
MAX_NAME = 30  # a label or income label, after trimming and joining spaces (docs/ui-spec.md)
ANSWER_ROLES = ("ignored", "payback", "income")  # the role decisions a sender answer writes


class ActionError(Exception):
    """kind: not_found, invalid or conflict."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def stored_credit_rows(
    session: Session,
    owner_id: uuid.UUID,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[CreditRow]:
    query = (
        select(
            Transaction.id,
            Transaction.amount_paise,
            Transaction.txn_time_utc,
            TxnDerived.merchant_key,
            TxnDerived.display_name,
            TxnDerived.role,
            TxnDerived.role_basis,
            TxnDerived.party_id,
        )
        .join(TxnDerived, TxnDerived.transaction_id == Transaction.id)
        .where(Transaction.owner_id == owner_id, Transaction.status == "active")
        .where(Transaction.direction == "credit", TxnDerived.role.in_(SENDER_ROLES))
    )
    if start is not None:
        query = query.where(Transaction.txn_time_utc >= start, Transaction.txn_time_utc < end)
    return [CreditRow(*row) for row in session.execute(query)]


def senders(session: Session, owner_id: uuid.UUID, start=None, end=None) -> list[Sender]:
    return credit_senders(stored_credit_rows(session, owner_id, start, end), str(owner_id))


def clean_name(name: str | None, what: str) -> str:
    """Trimmed, inner spaces joined, 1 to MAX_NAME characters."""
    name = " ".join((name or "").split())
    if not name or len(name) > MAX_NAME:
        raise ActionError("invalid", f"{what} has 1 to {MAX_NAME} characters")
    return name


def _sender(session: Session, owner_id: uuid.UUID, sender_id: str) -> Sender:
    sender = next((s for s in senders(session, owner_id) if s.id == sender_id), None)
    if sender is None:
        raise ActionError("not_found", "no such sender")
    return sender


def _transaction(session: Session, owner_id: uuid.UUID, txn_id: int) -> Transaction:
    t = session.get(Transaction, txn_id)
    if t is None or t.owner_id != owner_id or t.status != "active":
        raise ActionError("not_found", "no such transaction")
    return t


def party_for(session: Session, owner_id: uuid.UUID, txn_id: int, source: str) -> Party:
    """The party a transaction's merchant matches; made from its text when there is none."""
    t = _transaction(session, owner_id, txn_id)
    d = session.get(TxnDerived, txn_id)
    if d is None:
        raise ActionError("invalid", "the transaction has no derived data yet: recompute first")
    if d.party_id is not None:
        return session.get(Party, d.party_id)
    if not d.merchant_key or not t.counterparty_raw:
        raise ActionError("invalid", "the transaction has no merchant text")
    labels = {
        x.casefold() for x in session.scalars(select(Party.label).where(Party.owner_id == owner_id))
    }
    base = (d.display_name or "Merchant")[:70]
    label, n = base, 1
    while label.casefold() in labels:
        n += 1
        label = f"{base} ({n})"
    party = Party(
        owner_id=owner_id,
        label=label,
        kind="person" if d.merchant_kind == "person" else "business",
        source=source,
    )
    session.add(party)
    session.flush()
    session.add(
        PartyText(
            owner_id=owner_id, party_id=party.id, text=t.counterparty_raw[:200], source=source
        )
    )
    session.flush()
    return party


def _role(session: Session, owner_id: uuid.UUID, txn_id: int, role: str, source: str) -> None:
    row = session.get(OwnerRole, txn_id) or OwnerRole(transaction_id=txn_id, owner_id=owner_id)
    row.role, row.decided_at, row.source = role, datetime.now(UTC), source
    session.add(row)


def answer_sender(
    session: Session,
    owner_id: uuid.UUID,
    sender_id: str,
    answer: str,
    income_label: str | None,
    source: str,
) -> Sender:
    """friend: a person party; income <label>: an income party; ignore: role ignored.

    A sender with no merchant text has no party to hold the answer, so its credits get a
    role decision instead (payback or income).
    """
    if answer not in ANSWERS:
        raise ActionError("invalid", "answer must be friend, income or ignore")
    if answer == "income":
        income_label = clean_name(income_label, "an income label")
    sender = _sender(session, owner_id, sender_id)
    if answer == "ignore":
        for txn_id in sender.txn_ids:
            _role(session, owner_id, txn_id, "ignored", source)
    elif sender.merchant_key is None:
        for txn_id in sender.txn_ids:
            _role(session, owner_id, txn_id, "payback" if answer == "friend" else "income", source)
    else:
        party = party_for(session, owner_id, sender.txn_ids[0], source)
        if answer == "friend":
            party.kind, party.income_label = "person", None
        else:
            party.income_label = income_label
        for txn_id in sender.txn_ids:  # an earlier "ignore" or role answer gives way
            row = session.get(OwnerRole, txn_id)
            if row is not None and row.role in ANSWER_ROLES:
                session.delete(row)
    session.flush()
    return sender


def reset_sender(session: Session, owner_id: uuid.UUID, sender_id: str) -> Sender:
    """Forget the owner's answer, so the sender is "to confirm" again after the recompute.

    Its role decisions go. A party the app made only to hold the answer goes too. A party
    that also holds a default category, or comes from the owner file, keeps that and
    becomes a business: its credits are then to confirm (CR_business).
    """
    sender = _sender(session, owner_id, sender_id)
    for txn_id in sender.txn_ids:
        row = session.get(OwnerRole, txn_id)
        if row is not None and row.role in ANSWER_ROLES:
            session.delete(row)
    party = session.get(Party, sender.party_id) if sender.party_id is not None else None
    if party is not None and party.source == "app" and party.category is None:
        session.execute(delete(PartyText).where(PartyText.party_id == party.id))
        session.execute(
            TxnDerived.__table__.update()
            .where(TxnDerived.party_id == party.id)
            .values(party_id=None)
        )
        session.delete(party)
    elif party is not None:
        party.kind, party.income_label = "business", None
    session.flush()
    return sender


def set_category(
    session: Session, owner_id: uuid.UUID, txn_id: int, slug: str, scope: str, source: str
) -> None:
    """scope merchant: the party default, for every past and future payment; this
    transaction then follows it. scope transaction: a one-off on this transaction only."""
    if slug not in CATEGORIES:
        raise ActionError("invalid", "not a category of the list")
    if scope not in SCOPES:
        raise ActionError("invalid", "scope must be merchant or transaction")
    _transaction(session, owner_id, txn_id)
    one_off = session.get(OwnerCategory, txn_id)
    if scope == "merchant":
        party_for(session, owner_id, txn_id, source).category = slug
        if one_off is not None:
            session.delete(one_off)
    else:
        row = one_off or OwnerCategory(transaction_id=txn_id, owner_id=owner_id)
        row.category, row.decided_at, row.source = slug, datetime.now(UTC), source
        session.add(row)
    session.flush()


def create_label(session: Session, owner_id: uuid.UUID, name: str, source: str) -> Label:
    """A new label. A name the owner already has, in any case, is a conflict."""
    name = clean_name(name, "a label name")
    for label in session.scalars(select(Label).where(Label.owner_id == owner_id)):
        if " ".join(label.name.split()).casefold() == name.casefold():
            raise ActionError("conflict", "a label with this name already exists")
    label = Label(owner_id=owner_id, name=name, source=source)
    session.add(label)
    session.flush()
    return label


def set_label(
    session: Session, owner_id: uuid.UUID, txn_id: int, label_id: int, source: str
) -> None:
    _transaction(session, owner_id, txn_id)
    label = session.get(Label, label_id)
    if label is None or label.owner_id != owner_id:
        raise ActionError("not_found", "no such label")
    row = session.get(TxnLabel, txn_id) or TxnLabel(transaction_id=txn_id, owner_id=owner_id)
    row.label_id, row.source = label_id, source
    session.add(row)
    session.flush()


def clear_label(session: Session, owner_id: uuid.UUID, txn_id: int) -> None:
    _transaction(session, owner_id, txn_id)
    if (row := session.get(TxnLabel, txn_id)) is not None:
        session.delete(row)
        session.flush()
