"""Credit senders: who sent the paybacks, uncertain credits and income, and what to confirm.

One shared function for the CLI (credit-review) and the API (/senders). Pure.

A sender groups the credits of one merchant key; a credit with no key is its own sender.
A sender is "to_confirm" while any of its credits is uncertain or a payback the engine
guessed (D-076); "ignored" when the owner ignored every one; otherwise "confirmed". Its
id is opaque and stable: a hash of the key with a per-owner salt, never the key itself.
"""

import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

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


def credit_senders(rows: Iterable[CreditRow], salt: str) -> list[Sender]:
    """Senders of payback, uncertain and income credits, largest total first."""
    groups: dict[str, list[CreditRow]] = {}
    for row in sorted(rows, key=lambda r: r.id):
        if row.role in SENDER_ROLES:
            groups.setdefault(sender_id(salt, row.merchant_key, row.id), []).append(row)
    out = []
    for sid, mine in groups.items():
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
                merchant_key=mine[0].merchant_key,
                party_id=mine[-1].party_id,
            )
        )
    return sorted(out, key=lambda s: (-s.total_paise, s.id))
