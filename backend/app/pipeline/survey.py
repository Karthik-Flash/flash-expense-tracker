"""Counts over the stored messages for the owner's other banks (D-100). Reads only.

bank-survey: sender family x kind x status, plus foreign-currency messages.
  family  the bank of the sender code (VM-SBIINB -> SBI). A sender no bank code matches is
          shown by its own code when one of its messages looks like money, else it is
          folded into "other senders". Sender codes are not private.
  kind    generic.kind_of(): debit, credit, card, atm, balance, otp, promo, bill_due,
          request, other (keyword heuristics, never used for totals)
  status  dedicated (a bank parser read it), generic (the generic parser read it), or
          not parsed, from each message's current parse result.
generic-preview: what the generic parser WOULD do with every stored message of a bank that
has no dedicated parser: accepted by family and kind, refused by reason. Nothing written.
"""

import uuid
from collections import Counter, defaultdict
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import ParsedMessage
from app.engine.parsers import GENERIC_BANKS, generic
from app.engine.senders import SENDER_BANKS, bank_for
from app.models import ParseResult, RawMessage

MONEY_KINDS = frozenset({"debit", "credit", "card", "atm"})
STATUSES = ("dedicated", "generic", "not parsed")
OTHER = "other senders"


def family_of(core: str) -> str:
    return bank_for(core) or core


def _rows(session: Session, owner_id: uuid.UUID) -> Iterator[tuple]:
    query = (
        select(
            RawMessage.sender_core,
            RawMessage.body,
            RawMessage.received_at,
            ParseResult.status,
            ParseResult.parser_version,
        )
        .join(ParseResult, ParseResult.raw_message_id == RawMessage.id)
        .where(RawMessage.owner_id == owner_id, ParseResult.is_current)
        .order_by(RawMessage.id)
        .execution_options(yield_per=2000)
    )
    yield from session.execute(query)


def status_of(status: str, version: str) -> str:
    if status != "parsed":
        return "not parsed"
    return "generic" if version.startswith("generic-") else "dedicated"


def bank_survey(session: Session, owner_id: uuid.UUID) -> dict:
    """{"table": {family: {kind: Counter(status)}}, "foreign": Counter(family)}."""
    table: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    foreign: Counter = Counter()
    banks = set(SENDER_BANKS.values())
    for core, body, _, status, version in _rows(session, owner_id):
        family = family_of(core)
        table[family][generic.kind_of(body)][status_of(status, version)] += 1
        foreign[family] += bool(generic.FOREIGN.search(body))
    folded: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for family, kinds in table.items():
        if family in banks or MONEY_KINDS & kinds.keys():
            folded[family] = kinds
        else:
            for kind, counts in kinds.items():
                folded[OTHER][kind] += counts
    return {"table": folded, "foreign": foreign}


def generic_preview(session: Session, owner_id: uuid.UUID) -> dict[str, dict[str, Counter]]:
    """Per family of GENERIC_BANKS: accepted kinds, refused reasons, unsure reasons."""
    out: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for core, body, received_at, _, _ in _rows(session, owner_id):
        family = bank_for(core)
        if family not in GENERIC_BANKS:
            continue
        result = generic.parse(family, body, received_at)
        if isinstance(result, ParsedMessage):
            out[family]["accepted"][generic.kind_of(body)] += 1
        elif result.reason == "foreign_currency_deferred":
            out[family]["foreign currency"]["kept out"] += 1
        else:
            group = "refused" if result.reason == "not_a_transaction" else "unsure"
            out[family][group][result.detail] += 1
    return out
