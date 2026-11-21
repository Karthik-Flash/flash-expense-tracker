"""Write one message through the pipeline: raw -> parse result -> transaction.

Single writer (the CLI). Every step for one message happens in the caller's
transaction, so a commit always holds complete messages: a crash loses only
uncommitted messages, and a re-run picks them up as new.
"""

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import ParsedMessage, Unknown, parse_message
from app.engine.parsers import PARSERS, generic, parser_version
from app.models import DuplicateCandidate, ParseResult, RawMessage, Transaction, TransactionSource
from app.pipeline.dedupe import (
    CANDIDATE_RULE,
    CANDIDATE_WINDOW,
    content_hash,
    is_candidate,
    transaction_key,
)

NO_PARSER = "none"  # parser_version for banks without a parser yet


@dataclass
class Counts:
    """Counts only: never bodies, names, amounts, references or account digits."""

    read: int = 0
    skipped: Counter = field(default_factory=Counter)
    raw_new: int = 0
    raw_duplicate: int = 0
    reparsed: int = 0
    parsed: int = 0
    unknown: Counter = field(default_factory=Counter)
    is_money: int = 0
    transactions: Counter = field(default_factory=Counter)  # new, merged, updated, ...
    candidates: int = 0

    def as_dict(self) -> dict:
        return {
            "read": self.read,
            "skipped": dict(sorted(self.skipped.items())),
            "raw": {"new": self.raw_new, "duplicate": self.raw_duplicate},
            "reparsed": self.reparsed,
            "parsed": self.parsed,
            "unknown": dict(sorted(self.unknown.items())),
            "is_money": self.is_money,
            "transactions": dict(sorted(self.transactions.items())),
            "candidates": self.candidates,
        }


def parser_versions() -> dict[str, str]:
    versions = {bank: p.version for bank, p in sorted(PARSERS.items())}
    return versions | {"other banks": generic.GENERIC_VERSION}


def current_version(bank: str | None) -> str:
    return parser_version(bank) or NO_PARSER


def parse_raw(raw: RawMessage) -> ParsedMessage | Unknown:
    return parse_message(raw.sender_raw, raw.body, raw.received_at)


def result_row(raw: RawMessage, result: ParsedMessage | Unknown, counts: Counts) -> ParseResult:
    """A current parse_results row for this result (not yet added to the session)."""
    if isinstance(result, Unknown):
        counts.unknown[result.reason] += 1
        return ParseResult(
            raw_message_id=raw.id,
            parser_version=current_version(result.bank),
            status="unknown",
            unknown_reason=result.reason,
            unknown_detail=result.detail,
            is_current=True,
            bank=result.bank,
            hints=[],
        )
    counts.parsed += 1
    counts.is_money += result.is_money
    return ParseResult(
        raw_message_id=raw.id,
        parser_version=result.parser_version,
        status="parsed",
        is_current=True,
        **_fields(result),
    )


def _fields(p: ParsedMessage) -> dict:
    return {
        "bank": p.bank,
        "template_id": p.template_id,
        "type": p.type,
        "direction": p.direction,
        "amount_paise": p.amount_paise,
        "currency": p.currency,
        "account_last4": p.account_last4,
        "channel": p.channel,
        "counterparty_raw": p.counterparty_raw,
        "reference": p.reference,
        "balance_paise": p.balance_paise,
        "txn_time_utc": p.txn_time_utc,
        "time_inferred": p.time_inferred,
        "hints": list(p.hints),
    }


def txn_fields(p: ParsedMessage) -> dict:
    fields = _fields(p)
    del fields["template_id"]
    return fields


def ingest(
    session: Session,
    owner_id: uuid.UUID,
    batch_id: int | None,
    source: str,
    sender_raw: str,
    sender_core: str,
    body: str,
    received_at: datetime,
    counts: Counts,
) -> None:
    """Raw insert (skip if duplicate) -> parse -> parse result -> transaction -> candidates."""
    raw_hash = content_hash(sender_core, body, received_at)
    exists = select(RawMessage.id).where(
        RawMessage.owner_id == owner_id, RawMessage.content_hash == raw_hash
    )
    if session.scalar(exists) is not None:
        counts.raw_duplicate += 1
        return
    raw = RawMessage(
        owner_id=owner_id,
        source=source,
        sender_raw=sender_raw,
        sender_core=sender_core,
        body=body,
        received_at=received_at,
        content_hash=raw_hash,
        first_batch_id=batch_id,
    )
    session.add(raw)
    session.flush()
    counts.raw_new += 1
    result = parse_raw(raw)
    row = result_row(raw, result, counts)
    session.add(row)
    session.flush()
    if isinstance(result, ParsedMessage):
        link_new(session, owner_id, raw, row, result, counts)


def find_by_key(session: Session, owner_id: uuid.UUID, key: str) -> Transaction | None:
    return session.scalar(
        select(Transaction).where(Transaction.owner_id == owner_id, Transaction.dedupe_key == key)
    )


def link_new(
    session: Session,
    owner_id: uuid.UUID,
    raw: RawMessage,
    row: ParseResult,
    parsed: ParsedMessage,
    counts: Counts,
) -> None:
    """Link a raw message with no transaction yet: merge on the key, or create one."""
    key = transaction_key(parsed, raw.content_hash)
    if key is None:
        if parsed.is_money:
            counts.transactions["zero_amount"] += 1
        return
    txn = find_by_key(session, owner_id, key) or statement_twin(session, owner_id, parsed, raw)
    if txn is not None:
        txn.status = "active"  # a superseded transaction with a live source is live again
        if STATEMENT in (txn.hints or ()) and raw.source != "statement":
            # The SMS for a row first read from the statement (D-120): its own words win.
            for name, value in txn_fields(parsed).items():
                setattr(txn, name, value)
            counts.transactions["statement_row_replaced"] += 1
        counts.transactions["merged"] += 1
    else:
        txn = Transaction(owner_id=owner_id, dedupe_key=key, status="active", **txn_fields(parsed))
        session.add(txn)
        session.flush()
        counts.transactions["new"] += 1
        counts.candidates += record_candidates(session, txn)
    session.add(
        TransactionSource(transaction_id=txn.id, raw_message_id=raw.id, parse_result_id=row.id)
    )
    session.flush()


STATEMENT = "statement"  # the hint of a transaction read from the bank statement (D-120)


def statement_twin(
    session: Session, owner_id: uuid.UUID, parsed: ParsedMessage, raw: RawMessage
) -> Transaction | None:
    """An SMS with no key match: the one active statement transaction of the same bank,
    direction and amount within a day, if exactly one (D-120). A reference match is the
    dedupe key itself; this covers the rows the statement gave no reference."""
    if raw.source == STATEMENT or not parsed.is_money or parsed.txn_time_utc is None:
        return None
    near = [
        t
        for t in session.scalars(
            select(Transaction).where(
                Transaction.owner_id == owner_id,
                Transaction.status == "active",
                Transaction.bank == parsed.bank,
                Transaction.direction == parsed.direction,
                Transaction.amount_paise == parsed.amount_paise,
            )
        )
        if STATEMENT in (t.hints or ())
        and abs(t.txn_time_utc - parsed.txn_time_utc) <= timedelta(days=1)
    ]
    return near[0] if len(near) == 1 else None


def record_candidates(session: Session, txn: Transaction) -> int:
    """Add duplicate_candidates rows for txn (never merges). Returns how many were new."""
    nearby = session.scalars(
        select(Transaction).where(
            Transaction.owner_id == txn.owner_id,
            Transaction.bank == txn.bank,
            Transaction.direction == txn.direction,
            Transaction.amount_paise == txn.amount_paise,
            Transaction.status == "active",
            Transaction.id != txn.id,
            Transaction.txn_time_utc.between(
                txn.txn_time_utc - CANDIDATE_WINDOW, txn.txn_time_utc + CANDIDATE_WINDOW
            ),
        )
    )
    added = 0
    for other in nearby:
        if not is_candidate(txn, other):
            continue
        a, b = sorted((txn.id, other.id))
        pair = select(DuplicateCandidate.id).where(
            DuplicateCandidate.txn_a == a, DuplicateCandidate.txn_b == b
        )
        if session.scalar(pair) is None:
            session.add(DuplicateCandidate(txn_a=a, txn_b=b, rule=CANDIDATE_RULE, status="open"))
            added += 1
    session.flush()
    return added
