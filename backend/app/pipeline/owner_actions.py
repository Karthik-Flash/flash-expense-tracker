"""Owner answers from the app or the terminal: one place, used by the API and the CLI.

Each function writes owner rows with the caller's source and does not commit: the caller
runs one recompute, which commits the answer and the derived rows together (or nothing).
Errors never hold a value from the data.

People (D-096): a person is a party. Naming sets its display name; "same as" moves texts
from one party to another, ending the old rows; "separate" ends one text's row. Rows are
never deleted for a join, and texts from the owner file are left to the file.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.engine.categorise import CATEGORIES
from app.engine.credits import SENDER_ROLES, CreditRow, Sender, credit_senders
from app.engine.merchant import normalise_merchant
from app.engine.parsers.generic import HINT as GENERIC
from app.models import (
    LABEL_MAX,
    Label,
    OwnerCategory,
    OwnerRole,
    Party,
    PartyText,
    Transaction,
    TxnCheck,
    TxnDerived,
    TxnLabel,
)

ANSWERS = ("friend", "income", "ignore")
SCOPES = ("merchant", "transaction")
MAX_NAME = LABEL_MAX  # a label, income label or name, trimmed, spaces joined (D-097)
ANSWER_ROLES = ("ignored", "payback", "income")  # the role decisions a sender answer writes
PERSON_ROLES = ("friend", "income", "ignore", "none")  # a person's answer; none: to confirm
FROM_FILE = "this identifier is set in the owner file: change it there"


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
    # No role answer yet (D-096): the merchant rules keep deciding its credits until the
    # owner answers. (Before 4E a person-like text got kind person here, which silently
    # confirmed its credits as paybacks when only a category was set.)
    party = Party(owner_id=owner_id, label=label, kind="unsure", source=source)
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
        party.answered_at = datetime.now(UTC)  # an explicit answer (D-099 as corrected)
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
    if party is not None and _plain(session, party):
        session.execute(delete(PartyText).where(PartyText.party_id == party.id))
        session.execute(
            TxnDerived.__table__.update()
            .where(TxnDerived.party_id == party.id)
            .values(party_id=None)
        )
        session.delete(party)
    elif party is not None:  # named, joined, with a category, or from a file: it stays
        party.kind, party.income_label = ("business" if party.source == "file" else "unsure"), None
        party.answered_at = None
    session.flush()
    return sender


def _plain(session: Session, party: Party) -> bool:
    """A party the app made only to hold an answer: one text ever, no name, no category."""
    texts = session.scalar(select(func.count()).where(PartyText.party_id == party.id))
    return (
        party.source == "app" and party.category is None and not party.display_name and texts <= 1
    )


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


# The checked transaction, for a route that must fail before writing anything else.
transaction_of = _transaction


# --- Checks of generic-parsed payments (D-101, D-103) -----------------------------------


def looks_right(session: Session, owner_id: uuid.UUID, txn_id: int, source: str) -> None:
    """The owner checked a payment the generic parser read: its "check" flag goes. No total
    changes. Only a generic payment has a flag to clear."""
    t = _transaction(session, owner_id, txn_id)
    if GENERIC not in (t.hints or ()):
        raise ActionError("invalid", "only a payment read automatically needs a check")
    row = session.get(TxnCheck, txn_id) or TxnCheck(transaction_id=txn_id, owner_id=owner_id)
    row.checked_at, row.source = datetime.now(UTC), source
    session.add(row)
    session.flush()


def not_a_payment(session: Session, owner_id: uuid.UUID, txn_id: int, source: str) -> None:
    """D-103: any transaction can be left out of every total (role ignored), by the owner."""
    _transaction(session, owner_id, txn_id)
    _role(session, owner_id, txn_id, "ignored", source)
    session.flush()


def count_again(session: Session, owner_id: uuid.UUID, txn_id: int) -> None:
    """Undo "Not a payment": the engine decides again. Another role the owner set stays: that
    is a conflict, not something to undo here."""
    _transaction(session, owner_id, txn_id)
    row = session.get(OwnerRole, txn_id)
    if row is None:
        return
    if row.role != "ignored":
        raise ActionError("conflict", "this payment is not marked as not a payment")
    session.delete(row)
    session.flush()


# --- People: names and joins (D-096) ---------------------------------------------------


def _derived(session: Session, owner_id: uuid.UUID, txn_id: int) -> tuple[Transaction, TxnDerived]:
    t = _transaction(session, owner_id, txn_id)
    d = session.get(TxnDerived, txn_id)
    if d is None:
        raise ActionError("invalid", "the transaction has no derived data yet: recompute first")
    return t, d


def _active(session: Session, party_id: int) -> list[PartyText]:
    query = select(PartyText).where(PartyText.party_id == party_id, PartyText.ended_at.is_(None))
    return list(session.scalars(query.order_by(PartyText.id)))


def text_key(text: str) -> str | None:
    """How the engine matches a text to transactions (reconcile._text_index)."""
    return normalise_merchant(text, "other").merchant_key


def person_role(sender: Sender | None) -> str | None:
    """friend, income, ignore or none (to confirm); None with no credits."""
    if sender is None:
        return None
    if sender.status == "ignored":
        return "ignore"
    if sender.status == "to_confirm":
        return "none"
    return "income" if sender.role == "income" else "friend"


def sender_of(everyone: list[Sender], d: TxnDerived) -> Sender | None:
    """The sender of a transaction's person, if any: by party, else by merchant key."""
    for s in everyone:
        if d.party_id is not None and s.party_id == d.party_id:
            return s
        unpartied = d.party_id is None and s.party_id is None
        if unpartied and d.merchant_key and s.merchant_key == d.merchant_key:
            return s
    return None


def name_person(
    session: Session, owner_id: uuid.UUID, txn_id: int, name: str, source: str
) -> Party:
    """The owner's name for the person of this transaction, shown everywhere it appears."""
    name = clean_name(name, "a name")
    party = party_for(session, owner_id, txn_id, source)
    party.display_name = name
    session.flush()
    return party


def clear_name(session: Session, owner_id: uuid.UUID, txn_id: int) -> None:
    _, d = _derived(session, owner_id, txn_id)
    party = session.get(Party, d.party_id) if d.party_id is not None else None
    if party is None or party.display_name is None:
        raise ActionError("not_found", "this person has no name to clear")
    party.display_name = None
    session.flush()


def join_person(
    session: Session,
    owner_id: uuid.UUID,
    txn_id: int,
    into_txn_id: int,
    role: str | None,
    source: str,
) -> Party:
    """Same as: the person of `txn_id` becomes the person of `into_txn_id`. Every active text
    moves (the old rows end). When both sides have an answer and they differ, `role` must
    say which one the person keeps; nothing is chosen silently."""
    if role is not None and role not in PERSON_ROLES:
        raise ActionError("invalid", "role must be friend, income, ignore or none")
    t, d = _derived(session, owner_id, txn_id)
    _, into = _derived(session, owner_id, into_txn_id)
    if not d.merchant_key or not t.counterparty_raw:
        raise ActionError("invalid", "the transaction has no merchant text")
    one_party = d.party_id is not None and d.party_id == into.party_id
    one_key = d.party_id is None and into.party_id is None and d.merchant_key == into.merchant_key
    if one_party or one_key:
        raise ActionError("conflict", "these are already the same person")
    moving = _active(session, d.party_id) if d.party_id is not None else []
    if any(row.source == "file" for row in moving):
        raise ActionError("conflict", FROM_FILE)

    everyone = senders(session, owner_id)
    mine, theirs = sender_of(everyone, d), sender_of(everyone, into)
    rs, rt = person_role(mine), person_role(theirs)
    if rs is not None and rt is not None and rs != rt:
        if role is None:
            raise ActionError(
                "conflict", "the two have different answers: choose the one the person keeps"
            )
        if role not in (rs, rt):
            raise ActionError("invalid", "role must be the answer of one of the two")
        chosen = role
    else:
        chosen = rt if rt is not None else rs

    target = party_for(session, owner_id, into_txn_id, source)
    old = session.get(Party, d.party_id) if d.party_id is not None else None
    income = target.income_label or (old.income_label if old else None)
    texts = [row.text for row in moving] or [t.counterparty_raw[:200]]
    now = datetime.now(UTC)
    for row in moving:
        row.ended_at = now
    if old is not None:
        target.display_name = target.display_name or old.display_name
        target.category = target.category or old.category
    if not target.display_name and target.source != "file" and into.display_name:
        # "Same as Rohit V": the person keeps the name it is shown by (the owner's words).
        target.display_name = into.display_name[:MAX_NAME]
    session.flush()
    for text in texts:
        session.add(PartyText(owner_id=owner_id, party_id=target.id, text=text, source=source))
    session.flush()

    if chosen is None:
        return target
    if chosen != rt:  # the person takes the joined side's answer, on every credit
        if chosen == "friend":
            target.kind, target.income_label = "person", None
        elif chosen == "income":
            target.income_label = income
        else:
            target.kind, target.income_label = "unsure", None
        fix = [*(mine.txn_ids if mine else ()), *(theirs.txn_ids if theirs else ())]
    else:  # the person keeps its answer; the joined credits follow it
        fix = list(mine.txn_ids if mine else ())
    if chosen in ("friend", "income") and (role is not None or (old and old.answered_at)):
        target.answered_at = datetime.now(UTC)  # the owner chose it, or it had an answer
    for txn in fix:
        row = session.get(OwnerRole, txn)
        if chosen == "ignore":
            _role(session, owner_id, txn, "ignored", source)
        elif row is not None and row.role in ANSWER_ROLES:
            session.delete(row)
    session.flush()
    return target


def separate_person(session: Session, owner_id: uuid.UUID, txn_id: int) -> None:
    """End the join of this transaction's identifier: it is on its own again. Its row stays,
    with an end time. A person's only identifier, or one from the owner file, stays."""
    _, d = _derived(session, owner_id, txn_id)
    if d.party_id is None:
        raise ActionError("not_found", "this identifier is not part of a person")
    active = _active(session, d.party_id)
    mine = [row for row in active if text_key(row.text) == d.merchant_key]
    if not mine:
        raise ActionError("not_found", "this identifier is not part of a person")
    if any(row.source == "file" for row in mine):
        raise ActionError("conflict", FROM_FILE)
    if len(mine) == len(active):
        raise ActionError("conflict", "this is the person's only identifier")
    now = datetime.now(UTC)
    for row in mine:
        row.ended_at = now
    session.flush()
