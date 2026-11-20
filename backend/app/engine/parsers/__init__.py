"""Bank code -> parser. Adding a bank: one new module plus one line here.

A bank in the sender registry with no dedicated parser is read by the generic parser
(D-101). Senders that are apps, not banks, are never read: their messages repeat the
bank's own alert for the same payment.
"""

from app.engine.parsers import generic
from app.engine.parsers.base import BankParser
from app.engine.parsers.hdfc import PARSER as HDFC
from app.engine.senders import SENDER_BANKS

PARSERS: dict[str, BankParser] = {p.bank: p for p in (HDFC,)}
NOT_BANKS = frozenset({"PHONEPE"})  # an app's own payment message, not a bank alert
GENERIC_BANKS = frozenset(SENDER_BANKS.values()) - PARSERS.keys() - NOT_BANKS


def parser_version(bank: str | None) -> str | None:
    """The version that reads this bank's messages now, or None when nothing does."""
    if bank in PARSERS:
        return PARSERS[bank].version
    return generic.GENERIC_VERSION if bank in GENERIC_BANKS else None
