"""Dedupe rules as pure functions. See docs/data-model.md and DECISIONS D-046.

- Raw level: content_hash of sender core, body and received_at (epoch ms).
  The source is excluded, so the same SMS arriving later by another route is
  still a duplicate.
- Transaction level (money results only): with a reference, the key is
  ("ref", bank, direction, amount, reference), without the account so email
  and statements can merge later; without one, or when the reference is a
  mandate ID (hint "mandate_reference"), ("raw", content_hash). A generic
  result without a reference (D-101) has ("gen", bank, direction, amount,
  account, event minute), so the same alert arriving twice is one payment.
  No fuzzy merging.
- Fuzzy candidates are only recorded, never merged: Reconcile decides.
"""

import hashlib
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.engine import ParsedMessage
from app.engine.parsers.generic import HINT as GENERIC

SEP = "\x1f"  # unit separator: cannot occur in sender IDs, never ambiguous
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
CANDIDATE_WINDOW = timedelta(minutes=10)
CANDIDATE_RULE = "same_amount_10min"
# Engine hint: the reference identifies a mandate, not one payment (it repeats
# every month), so it must not merge charges. Such results use the raw key.
MANDATE_REFERENCE = "mandate_reference"


def _sha(*parts: object) -> str:
    return hashlib.sha256(SEP.join(str(p) for p in parts).encode("utf-8")).hexdigest()


def epoch_ms(moment: datetime) -> int:
    """Exact integer milliseconds since 1970 (UTC). Rejects naive datetimes."""
    if moment.tzinfo is None:
        raise ValueError("naive datetime: times must be timezone-aware")
    return (moment - EPOCH) // timedelta(milliseconds=1)


def content_hash(sender_core: str, body: str, received_at: datetime) -> str:
    return _sha(sender_core, body, epoch_ms(received_at))


# Whitespace as Python's str.isspace() knows it, written out so the phone's copy of this rule
# (Wire.kt) is the same character for character (5B-2, D-139; tests/fixtures/body_normalise.json).
WHITESPACE = " \t\n\r\x0b\x0c\x1c\x1d\x1e\x1f\x85\xa0                　"
_RUNS = re.compile(f"[{re.escape(WHITESPACE)}]+")


def normal_body(body: str) -> str:
    """A body for comparing two copies of one SMS (the inbox row and the live broadcast): NFC,
    every run of whitespace one space, no space at the ends. Never what is stored or hashed."""
    return _RUNS.sub(" ", unicodedata.normalize("NFC", body)).strip(" ")


def transaction_key(parsed: ParsedMessage, raw_hash: str) -> str | None:
    """Dedupe key, or None when the result creates no transaction."""
    if not parsed.is_money or not parsed.amount_paise or parsed.amount_paise <= 0:
        return None
    if parsed.reference and MANDATE_REFERENCE not in parsed.hints:
        return _sha("ref", parsed.bank, parsed.direction, parsed.amount_paise, parsed.reference)
    if GENERIC in parsed.hints:
        minute = epoch_ms(parsed.txn_time_utc) // 60_000
        return _sha(
            "gen", parsed.bank, parsed.direction, parsed.amount_paise, parsed.account_last4, minute
        )
    return _sha("raw", raw_hash)


class TxnLike(Protocol):
    owner_id: object
    bank: str
    account_last4: str | None
    direction: str
    amount_paise: int
    reference: str | None
    txn_time_utc: datetime
    hints: list[str]


def is_candidate(a: TxnLike, b: TxnLike) -> bool:
    """Same owner, bank, account, direction and amount within 10 minutes.

    Two references of the same kind rule a pair out: equal ones are one mandate (or
    one transaction already), different ones are two payments (D-069). A mandate ID
    and a payment reference are different kinds and rule nothing out (D-072).

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
        and not (
            a.reference
            and b.reference
            and (MANDATE_REFERENCE in a.hints) == (MANDATE_REFERENCE in b.hints)
        )
    )
