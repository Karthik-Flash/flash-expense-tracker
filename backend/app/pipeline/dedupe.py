"""Dedupe rules as pure functions. See docs/data-model.md and DECISIONS D-046.

- Raw level: content_hash of sender core, body and received_at (epoch ms).
  The source is excluded, so the same SMS arriving later by another route is
  still a duplicate.
- Transaction level (money results only): with a reference, the key is
  ("ref", bank, direction, amount, reference), without the account so email
  and statements can merge later; without one, ("raw", content_hash). No
  fuzzy merging.
- Fuzzy candidates are only recorded, never merged: Reconcile decides.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.engine import ParsedMessage

SEP = "\x1f"  # unit separator: cannot occur in sender IDs, never ambiguous
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
CANDIDATE_WINDOW = timedelta(minutes=10)
CANDIDATE_RULE = "same_amount_10min"


def _sha(*parts: object) -> str:
    return hashlib.sha256(SEP.join(str(p) for p in parts).encode("utf-8")).hexdigest()


def epoch_ms(moment: datetime) -> int:
    """Exact integer milliseconds since 1970 (UTC). Rejects naive datetimes."""
    if moment.tzinfo is None:
        raise ValueError("naive datetime: times must be timezone-aware")
    return (moment - EPOCH) // timedelta(milliseconds=1)


def content_hash(sender_core: str, body: str, received_at: datetime) -> str:
    return _sha(sender_core, body, epoch_ms(received_at))


def transaction_key(parsed: ParsedMessage, raw_hash: str) -> str | None:
    """Dedupe key, or None when the result creates no transaction."""
    if not parsed.is_money or not parsed.amount_paise or parsed.amount_paise <= 0:
        return None
    if parsed.reference:
        return _sha("ref", parsed.bank, parsed.direction, parsed.amount_paise, parsed.reference)
    return _sha("raw", raw_hash)


class TxnLike(Protocol):
    owner_id: object
    bank: str
    account_last4: str | None
    direction: str
    amount_paise: int
    reference: str | None
    txn_time_utc: datetime


def is_candidate(a: TxnLike, b: TxnLike) -> bool:
    """Same owner, bank, account, direction and amount within 10 minutes, no shared reference.

    Different directions never match: a self-transfer is a debit and a credit
    for Reconcile to pair.
    """
    return (
        a.owner_id == b.owner_id
        and a.bank == b.bank
        and a.account_last4 == b.account_last4
        and a.direction == b.direction
        and a.amount_paise == b.amount_paise
        and abs(a.txn_time_utc - b.txn_time_utc) <= CANDIDATE_WINDOW
        and not (a.reference and a.reference == b.reference)
    )
