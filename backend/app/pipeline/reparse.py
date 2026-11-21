"""Re-parse stored messages whose current result is not at their bank's parser version.

Never deletes raw messages or parse results: a new result is added and
is_current moves to it. The linked transaction is updated in place (its id
stays stable), or the source moves to the transaction its new dedupe key
already belongs to. Running it twice changes nothing the second time.
"""

import uuid
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import ParsedMessage, Unknown
from app.engine.senders import bank_for
from app.models import ParseResult, RawMessage, Transaction, TransactionSource
from app.pipeline.dedupe import transaction_key
from app.pipeline.store import (
    Counts,
    current_version,
    find_by_key,
    link_new,
    parse_raw,
    record_candidates,
    result_row,
    txn_fields,
)


def stale(session: Session, owner_id: uuid.UUID) -> list[int]:
    """Ids of raw messages whose current result is behind their bank's parser version."""
    rows = session.execute(
        select(RawMessage.id, RawMessage.sender_core, ParseResult.parser_version)
        .join(ParseResult, ParseResult.raw_message_id == RawMessage.id)
        .where(
            RawMessage.owner_id == owner_id,
            ParseResult.is_current,
            RawMessage.source != "statement",  # read by the statement reader, not an SMS parser
        )
        .order_by(RawMessage.id)
    )
    return [rid for rid, core, version in rows if version != current_version(bank_for(core))]


def reparse(
    session: Session,
    owner_id: uuid.UUID,
    *,
    dry_run: bool = False,
    commit_every: int = 500,
    progress: Callable[[int], None] | None = None,
) -> Counts:
    counts = Counts()
    for n, raw_id in enumerate(stale(session, owner_id), 1):
        reparse_one(session, owner_id, session.get(RawMessage, raw_id), counts)
        if n % commit_every == 0:
            session.flush() if dry_run else session.commit()
        if progress and n % 5000 == 0:
            progress(n)
    if dry_run:
        session.rollback()
    else:
        session.commit()
    return counts


def reparse_one(session: Session, owner_id: uuid.UUID, raw: RawMessage, counts: Counts) -> None:
    result = parse_raw(raw)
    old = session.scalar(
        select(ParseResult).where(ParseResult.raw_message_id == raw.id, ParseResult.is_current)
    )
    old.is_current = False
    session.flush()  # the partial unique index allows one current row at a time

    row = result_row(raw, result, counts)
    earlier = session.scalar(
        select(ParseResult).where(
            ParseResult.raw_message_id == raw.id,
            ParseResult.parser_version == row.parser_version,
        )
    )
    if earlier is not None:  # back to a version seen before: reuse its row
        earlier.is_current = True
        row = earlier
    else:
        session.add(row)
    session.flush()
    counts.reparsed += 1
    relink(session, owner_id, raw, row, result, counts)


def relink(
    session: Session,
    owner_id: uuid.UUID,
    raw: RawMessage,
    row: ParseResult,
    result: ParsedMessage | Unknown,
    counts: Counts,
) -> None:
    link = session.scalar(
        select(TransactionSource).where(TransactionSource.raw_message_id == raw.id)
    )
    parsed = result if isinstance(result, ParsedMessage) else None
    key = transaction_key(parsed, raw.content_hash) if parsed else None

    if link is None:
        if parsed:
            link_new(session, owner_id, raw, row, parsed, counts)
        return
    old = session.get(Transaction, link.transaction_id)
    if key is None:  # no longer a transaction
        session.delete(link)
        session.flush()
        supersede_if_orphan(session, old, counts)
        return

    target = find_by_key(session, owner_id, key)
    if target is None or target.id == old.id:  # same event: update in place, id stays
        for name, value in txn_fields(parsed).items():
            setattr(old, name, value)
        old.dedupe_key, old.status = key, "active"
        link.parse_result_id = row.id
        session.flush()
        counts.transactions["updated"] += 1
        counts.candidates += record_candidates(session, old)
        return
    # The new key belongs to another transaction: move the source there.
    link.transaction_id, link.parse_result_id = target.id, row.id
    target.status = "active"
    session.flush()
    counts.transactions["merged"] += 1
    supersede_if_orphan(session, old, counts)


def supersede_if_orphan(session: Session, txn: Transaction, counts: Counts) -> None:
    sources = session.scalar(
        select(func.count())
        .select_from(TransactionSource)
        .where(TransactionSource.transaction_id == txn.id)
    )
    if not sources:
        txn.status = "superseded"
        counts.transactions["superseded"] += 1
        session.flush()
