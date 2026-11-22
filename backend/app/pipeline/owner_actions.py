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
    SUGGESTIONS,
    VERDICTS,
    Label,
    OwnerCategory,
    OwnerLinkDecision,
    OwnerName,
    OwnerRole,
    OwnerSetting,
    Party,
    PartyText,
    Transaction,
    TxnCheck,
    TxnDerived,
    TxnLabel,
    TxnLink,
)

ANSWERS = ("friend", "income", "ignore")
SCOPES = ("merchant", "transaction")
MAX_NAME = LABEL_MAX  # a label, income label or name, trimmed, spaces joined (D-097)
ANSWER_ROLES = ("ignored", "payback", "income")  # the role decisions a sender answer writes
ONE = "one"  # owner_roles.scope of a per-credit Paid back / Not paid back answer (D-149)
CREDIT_ANSWERS = {"paid_back": "payback", "not_paid_back": "ignored"}
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


def _role(
    session: Session,
    owner_id: uuid.UUID,
    txn_id: int,
    role: str,
    source: str,
    scope: str | None = None,
) -> None:
    """The owner's role for one transaction. A person-level answer (scope None) leaves a
    per-credit answer (scope "one", D-149) as it is: the per-credit answer wins."""
    row = session.get(OwnerRole, txn_id)
    if row is not None and row.scope == ONE and scope != ONE:
        return
    row = row or OwnerRole(transaction_id=txn_id, owner_id=owner_id)
    row.role, row.decided_at, row.source, row.scope = role, datetime.now(UTC), source, scope
    session.add(row)


def _person_level(row: OwnerRole | None) -> bool:
    """A role answer a person-level answer may replace: not a per-credit one (D-149)."""
    return row is not None and row.role in ANSWER_ROLES and row.scope != ONE


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
            if _person_level(row):
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
        if _person_level(row):
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


def answer_credit(
    session: Session, owner_id: uuid.UUID, txn_id: int, answer: str | None, source: str
) -> None:
    """Paid back or Not paid back for this one credit (D-149); None: forget it, so the
    person-level answer (or the engine) decides again. Beats the person-level answer."""
    t = _transaction(session, owner_id, txn_id)
    if t.direction != "credit":
        raise ActionError("invalid", "only money in can be paid back")
    row = session.get(OwnerRole, txn_id)
    if answer is None:
        if row is not None and row.scope == ONE:
            session.delete(row)
    elif answer not in CREDIT_ANSWERS:
        raise ActionError("invalid", "answer must be paid_back or not_paid_back")
    else:
        _role(session, owner_id, txn_id, CREDIT_ANSWERS[answer], source, ONE)
    session.flush()


def credit_answers(session: Session, owner_id: uuid.UUID) -> dict[str, str]:
    """Per-credit answers: transaction id (as text, a JSON key) -> paid_back/not_paid_back."""
    back = {v: k for k, v in CREDIT_ANSWERS.items()}
    rows = session.scalars(
        select(OwnerRole).where(OwnerRole.owner_id == owner_id, OwnerRole.scope == ONE)
    )
    return {str(r.transaction_id): back.get(r.role, r.role) for r in rows}


def category_rules(session: Session, owner_id: uuid.UUID) -> list[dict]:
    """ "Your rules" (D-149): each party with a default category, its name and how many
    active payments it covers now. The party holds every text joined to it, never a
    masked-suffix guess (those only feed payback links, D-145)."""
    count = dict(
        session.execute(
            select(TxnDerived.party_id, func.count())
            .join(Transaction, Transaction.id == TxnDerived.transaction_id)
            .where(Transaction.owner_id == owner_id, Transaction.status == "active")
            .group_by(TxnDerived.party_id)
        ).all()
    )
    parties = session.scalars(
        select(Party)
        .where(Party.owner_id == owner_id, Party.category.is_not(None))
        .order_by(Party.id)
    )
    return [
        {
            "party_id": p.id,
            "name": p.display_name or p.label,
            "category": p.category,
            "category_name": CATEGORIES.get(p.category, p.category),
            "payments": count.get(p.id, 0),
        }
        for p in parties
    ]


def undo_rule(session: Session, owner_id: uuid.UUID, party_id: int) -> None:
    """Forget a party's default category: its payments go back to the engine's category
    (one-off answers on single payments stay)."""
    party = session.get(Party, party_id)
    if party is None or party.owner_id != owner_id:
        raise ActionError("not_found", "no such rule")
    party.category = None
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


def label_named(session: Session, owner_id: uuid.UUID, name: str, source: str) -> Label:
    """The owner's label of this name (any case, spaces tidied), made when there is none."""
    wanted = clean_name(name, "a label name")
    for label in session.scalars(select(Label).where(Label.owner_id == owner_id)):
        if " ".join(label.name.split()).casefold() == wanted.casefold():
            return label
    return create_label(session, owner_id, wanted, source)


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


def answer_transfer(
    session: Session, owner_id: uuid.UUID, txn_a: int, txn_b: int, verdict: str, source: str
) -> tuple[int, int]:
    """ "Moved between your accounts?" (D-115): same makes both legs self_transfer; different
    removes the pair for good. Only a pair the engine proposed (or one already answered).
    One leg can be "same" with one other leg only."""
    if verdict not in VERDICTS:
        raise ActionError("invalid", "verdict must be same or different")
    a, b = sorted((txn_a, txn_b))
    if a == b:
        raise ActionError("invalid", "a transfer needs two different payments")
    for i in (a, b):
        _transaction(session, owner_id, i)
    kind = "self_transfer"
    proposed = session.scalar(
        select(TxnLink.id).where(
            TxnLink.owner_id == owner_id, TxnLink.kind == kind, TxnLink.txn_a == a,
            TxnLink.txn_b == b,
        )
    )  # fmt: skip
    d = OwnerLinkDecision
    row = session.scalar(
        select(d).where(d.owner_id == owner_id, d.kind == kind, d.txn_a == a, d.txn_b == b)
    )
    if proposed is None and row is None:
        raise ActionError("not_found", "these two payments are not a possible transfer")
    if verdict == "same":
        other = session.scalar(
            select(d.id).where(
                d.owner_id == owner_id,
                d.kind == kind,
                d.verdict == "same",
                (d.txn_a.in_((a, b))) | (d.txn_b.in_((a, b))),
                ~((d.txn_a == a) & (d.txn_b == b)),
            )
        )
        if other is not None:
            raise ActionError("conflict", "one of these payments is already a transfer")
    if row is None:
        row = OwnerLinkDecision(owner_id=owner_id, kind=kind, txn_a=a, txn_b=b)
        session.add(row)
    row.verdict, row.decided_at, row.source = verdict, datetime.now(UTC), source
    session.flush()
    return a, b


def owner_settings(session: Session, owner_id: uuid.UUID) -> dict:
    """The owner's settings (D-136); every default when the owner never changed one."""
    row = session.get(OwnerSetting, owner_id)
    return {"count_investments_in_spent": bool(row and row.count_investments_in_spent)}


def set_owner_settings(
    session: Session, owner_id: uuid.UUID, count_investments_in_spent: bool, source: str
) -> dict:
    """ "Count investments in Spent" (D-136): owner data, read when totals are worked out."""
    row = session.get(OwnerSetting, owner_id) or OwnerSetting(owner_id=owner_id)
    row.count_investments_in_spent = count_investments_in_spent
    row.updated_at, row.source = datetime.now(UTC), source
    session.add(row)
    session.flush()
    return owner_settings(session, owner_id)


MAX_OWNER_NAMES = 6
KINDS = ("self", "investment")  # "It's me" (D-117) and Investments (D-118)


def set_owner_names(
    session: Session, owner_id: uuid.UUID, names: list[str], source: str
) -> list[str]:
    """ "Your name as banks show it": the whole list, replaced (D-117). Owner data."""
    clean = []
    for name in names:
        text = " ".join((name or "").split())
        if not 2 <= len(text) <= 2 * LABEL_MAX or not any(c.isalpha() for c in text):
            raise ActionError("invalid", f"a name has 2 to {2 * LABEL_MAX} characters")
        if text.casefold() not in {c.casefold() for c in clean}:
            clean.append(text)
    if len(clean) > MAX_OWNER_NAMES:
        raise ActionError("invalid", f"at most {MAX_OWNER_NAMES} names")
    session.execute(delete(OwnerName).where(OwnerName.owner_id == owner_id))
    session.add_all(OwnerName(owner_id=owner_id, name=n, source=source) for n in clean)
    session.flush()
    return clean


def set_party_kind(
    session: Session, owner_id: uuid.UUID, txn_id: int, kind: str, source: str
) -> Party:
    """It's me (self) or Investments for the person of this transaction: every payment of
    the party, both ways, becomes a transfer or an investment. The kind it had is kept, so
    an undo restores it."""
    if kind not in KINDS:
        raise ActionError("invalid", "kind must be self or investment")
    party = party_for(session, owner_id, txn_id, source)
    if party.source == "file":
        raise ActionError("conflict", FROM_FILE)
    if party.kind not in KINDS:
        party.dismissed = [d for d in party.dismissed or [] if not d.startswith("was:")] + [
            f"was:{party.kind}"
        ]
    party.kind = kind
    session.flush()
    return party


def clear_party_kind(session: Session, owner_id: uuid.UUID, txn_id: int) -> Party:
    """Undo It's me or Investments: the party gets back the kind it had before."""
    _, d = _derived(session, owner_id, txn_id)
    party = session.get(Party, d.party_id) if d.party_id is not None else None
    if party is None or party.kind not in KINDS:
        raise ActionError("not_found", "this person is not marked as you or an investment")
    was = [x for x in party.dismissed or [] if x.startswith("was:")]
    party.kind = was[-1].removeprefix("was:") if was else "unsure"
    party.dismissed = [x for x in party.dismissed or [] if not x.startswith("was:")]
    session.flush()
    return party


def dismiss_suggestion(
    session: Session, owner_id: uuid.UUID, txn_id: int, kind: str, source: str
) -> Party:
    """No to "Is this you?" or "Is this an investment?": never asked again for this party."""
    if kind not in SUGGESTIONS:
        raise ActionError("invalid", "kind must be self or investment")
    party = party_for(session, owner_id, txn_id, source)
    if kind not in (party.dismissed or []):
        party.dismissed = [*(party.dismissed or []), kind]
    session.flush()
    return party


# The checked transaction, for a route that must fail before writing anything else.
transaction_of = _transaction


# --- Checks of generic-parsed payments (D-101, D-103) -----------------------------------


def looks_right(session: Session, owner_id: uuid.UUID, txn_id: int, source: str) -> None:
    """The owner checked a payment the generic parser read: its "check" flag goes. No total
    changes. Only a generic payment has a flag to clear."""
    t = _transaction(session, owner_id, txn_id)
    if GENERIC not in (t.hints or ()) and "statement_check" not in (t.hints or ()):
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
    party.display_name, party.name_source = name, source
    session.flush()
    return party


def clear_name(session: Session, owner_id: uuid.UUID, txn_id: int) -> None:
    _, d = _derived(session, owner_id, txn_id)
    party = session.get(Party, d.party_id) if d.party_id is not None else None
    if party is None or party.display_name is None:
        raise ActionError("not_found", "this person has no name to clear")
    party.display_name = party.name_source = None
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
        if not target.display_name and old.display_name:
            target.display_name, target.name_source = old.display_name, old.name_source
        target.category = target.category or old.category
    if not target.display_name and target.source != "file" and into.display_name:
        # "Same as Rohit V": the person keeps the name it is shown by (the owner's words).
        target.display_name, target.name_source = into.display_name[:MAX_NAME], source
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
        elif _person_level(row):
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
