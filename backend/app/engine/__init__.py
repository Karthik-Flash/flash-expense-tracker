"""SMS parsing engine: pure Python, one message at a time.

parse_message() reports only what a single message literally says. Linking
messages (transfers, refunds, duplicates) belongs to the Reconcile stage.
No FastAPI, SQLAlchemy or app config here, so the engine runs anywhere.
"""

from datetime import datetime

from app.engine.models import MESSAGE_TYPES, MONEY_TYPES, ParsedMessage, Unknown
from app.engine.parsers import GENERIC_BANKS, PARSERS, generic
from app.engine.senders import bank_for, parse_sender

__all__ = ["MESSAGE_TYPES", "MONEY_TYPES", "ParsedMessage", "Unknown", "parse_message"]


def parse_message(sender: str, body: str, received_at: datetime) -> ParsedMessage | Unknown:
    """Parse one SMS. received_at must be timezone-aware."""
    core, _suffix = parse_sender(sender)
    bank = bank_for(core)
    if bank is None:
        return Unknown("unknown_sender")
    parser = PARSERS.get(bank)
    if parser is not None:
        return parser.parse(body, received_at)
    if bank in GENERIC_BANKS:  # no dedicated parser yet (D-101)
        return generic.parse(bank, body, received_at)
    return Unknown("no_parser_for_bank", bank)
