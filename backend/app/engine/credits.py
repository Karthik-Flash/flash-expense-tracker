"""Credit senders: who sent the paybacks, uncertain credits and income, and what to confirm.

One shared function for the CLI (credit-review) and the API (/senders). Pure.

A sender groups the credits of one owner party (a person the owner named or joined, D-096),
else of one merchant key; a credit with no key is its own sender.
A sender is "to_confirm" while any of its credits is uncertain or a payback the engine
guessed (D-076); "ignored" when the owner ignored every one; otherwise "confirmed". Its
id is opaque and stable: a hash of the key with a per-owner salt, never the key itself. A
party's sender takes the id of the smallest merchant key among its credits, so a party with
one text keeps the id its key had.
"""

import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.engine.reconcile import PAYBACK_WINDOW, masked_fits

SENDER_ROLES = ("payback", "uncertain", "income", "ignored")
STATUSES = ("to_confirm", "confirmed", "ignored")


@dataclass(frozen=True)
class CreditRow:
    """One stored credit with a sender role."""

    id: int
    amount_paise: int
    txn_time_utc: datetime
    merchant_key: str | None
    display_name: str | None
    role: str
    basis: str
    party_id: int | None = None


@dataclass(frozen=True)
class Sender:
    id: str
    display_name: str | None
    total_paise: int
    count: int
    role: str  # the most common role of its credits that are not ignored, else ignored
    basis: str  # owner when every credit is owner-decided, else engine
    status: str  # to_confirm, confirmed or ignored
    last_time_utc: datetime
    txn_ids: tuple[int, ...]
    merchant_key: str | None  # internal: never sent to a client
    party_id: int | None = None  # internal: the owner party its text matches


def sender_id(salt: str, merchant_key: str | None, txn_id: int) -> str:
    """Opaque, stable id. A credit with no merchant key is identified by its transaction."""
    seed = f"key|{merchant_key}" if merchant_key else f"txn|{txn_id}"
    return "s_" + hashlib.sha256(f"{salt}|{seed}".encode()).hexdigest()[:20]


def to_confirm(row: CreditRow) -> bool:
    return row.role == "uncertain" or (row.role == "payback" and row.basis != "owner")


@dataclass(frozen=True)
class PaybackRow:
    """One transaction as payback_links() reads it. `person`: who it is with (a party, else
    one merchant key), as the API's person_id; None with no counterparty text."""

    id: int
    direction: str
    amount_paise: int
    txn_time_utc: datetime
    person: str | None
    role: str
    vpa: str | None = None  # its UPI ID, masked or not (reconcile-1.7.1: a masked credit, D-145)


@dataclass(frozen=True)
class PaybackLink:
    debit: int
    credit: int
    status: str  # linked or candidate
    reason: str  # one_payment, several_payments, more_than_paid


PAID_ROLES = ("spend", "card_bill_counted")


def payback_links(rows: Iterable[PaybackRow]) -> list[PaybackLink]:
    """Which payment a payback pays back (D-134). Display only: a link changes no role and
    no total; Paid back is the sum of confirmed paybacks, linked or not (D-076).

    A credit of role payback and a payment (spend) to the same person (one party, so joined
    names and UPI IDs are one person; else one merchant key), paid at most PAYBACK_WINDOW
    before it. A credit with exactly one such payment is linked to it; with several it is a
    candidate of each (several_payments): the engine never picks the closest in time. A
    payment whose linked credits add up to more than it is makes them all candidates
    (more_than_paid). A split, where friends pay back a payment the owner made to a shop, has
    no person to match and is never linked; its paybacks still count once confirmed.
    """
    rows = sorted(rows, key=lambda r: r.id)
    payments: dict[str, list[PaybackRow]] = {}
    for r in rows:
        if r.direction == "debit" and r.role in PAID_ROLES and r.person:
            payments.setdefault(r.person, []).append(r)

    def before(d: PaybackRow, c: PaybackRow) -> bool:
        return d.txn_time_utc <= c.txn_time_utc <= d.txn_time_utc + PAYBACK_WINDOW

    found: dict[int, list[PaybackRow]] = {}  # credit -> its possible payments
    for c in rows:
        if c.direction == "credit" and c.role == "payback" and c.person:
            mine = [d for d in payments.get(c.person, ()) if before(d, c)]
            if not mine and c.vpa and "*" in c.vpa:
                # A masked sender (HDFC writes "*ahad@oksbi"): the payments to the one person
                # whose full UPI ID fits it, in the window; two such people: no link (D-145).
                fits = [
                    d for ds in payments.values() for d in ds
                    if d.vpa and before(d, c) and masked_fits(c.vpa, d.vpa)
                ]  # fmt: skip
                if len({d.person for d in fits}) == 1:
                    mine = fits
            if mine:
                found[c.id] = mine
    amount = {r.id: r.amount_paise for r in rows}
    back: Counter[int] = Counter()  # payment -> the credits linked to it, in paise
    for c, mine in found.items():
        if len(mine) == 1:
            back[mine[0].id] += amount[c]
    out = []
    for c, mine in found.items():
        for d in mine:
            if len(mine) > 1:
                status, reason = "candidate", "several_payments"
            elif back[d.id] > d.amount_paise:
                status, reason = "candidate", "more_than_paid"
            else:
                status, reason = "linked", "one_payment"
            out.append(PaybackLink(d.id, c, status, reason))
    return sorted(out, key=lambda x: (x.debit, x.credit))


def credit_senders(rows: Iterable[CreditRow], salt: str) -> list[Sender]:
    """Senders of payback, uncertain and income credits, largest total first."""
    groups: dict[tuple, list[CreditRow]] = {}
    for row in sorted(rows, key=lambda r: r.id):
        if row.role in SENDER_ROLES:
            group = (
                ("party", row.party_id)
                if row.party_id is not None
                else ("key", row.merchant_key or row.id)
            )
            groups.setdefault(group, []).append(row)
    out = []
    for mine in groups.values():
        keys = sorted({r.merchant_key for r in mine if r.merchant_key})
        sid = sender_id(salt, keys[0] if keys else None, mine[0].id)
        roles = Counter(r.role for r in mine if r.role != "ignored") or Counter(["ignored"])
        if any(to_confirm(r) for r in mine):
            status = "to_confirm"
        else:
            status = "ignored" if roles.keys() == {"ignored"} else "confirmed"
        out.append(
            Sender(
                id=sid,
                display_name=mine[-1].display_name,
                total_paise=sum(r.amount_paise for r in mine),
                count=len(mine),
                role=max(roles, key=lambda role: (roles[role], role)),
                basis="owner" if all(r.basis == "owner" for r in mine) else "engine",
                status=status,
                last_time_utc=max(r.txn_time_utc for r in mine),
                txn_ids=tuple(r.id for r in mine),
                merchant_key=keys[0] if keys else None,
                party_id=mine[-1].party_id,
            )
        )
    return sorted(out, key=lambda s: (-s.total_paise, s.id))
