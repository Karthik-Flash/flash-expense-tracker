"""Owner writes, once (D-091, D-092, D-094; docs/design/phase-4b2-outbox.md).

Every owner-write route runs through `write()`. A write commits the owner data, its
stored answer (table client_ops, with an `Idempotency-Key`) and a recompute mark (table
recompute_marks) in one transaction, and answers at once: the engine never blocks a tap
(D-106). The same key again gets the stored answer and writes nothing. Every read runs
`ensure_fresh()` first: it recomputes when a write marked the owner, when an older deferred
write did (D-094), or when the stored rows were made by other engine versions (D-102). A
recompute that fails keeps the mark, logs the error type, and is not tried again for 5
minutes; reads meanwhile serve the stored rows with the "being updated" notice.
`X-Defer-Recompute` is still accepted; every write is deferred now.
"""

import hashlib
import json
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.api.auth import current_owner
from app.db import get_session
from app.models import ClientOp, DeriveRun, RecomputeMark
from app.pipeline.owner_actions import ActionError
from app.pipeline.recompute import VERSIONS, OwnerDataError, owner_lock, recompute

IN_PROGRESS = "in_progress"
KEY_REUSED = "idempotency_key_reused"
RETRY_AFTER = timedelta(minutes=5)  # a failed recompute is tried again after this
DEFERRED = {"status": "deferred", "run": None}

_running: set[tuple[uuid.UUID, uuid.UUID]] = set()  # keys being written in this process
_running_guard = threading.Lock()
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Op:
    """An owner write as the client sent it."""

    method: str
    path: str
    key: uuid.UUID | None
    defer: bool


def client_op(
    request: Request,
    idempotency_key: Annotated[str | None, Header()] = None,
    x_defer_recompute: Annotated[str | None, Header()] = None,
) -> Op:
    key = None
    if idempotency_key is not None:
        try:
            key = uuid.UUID(idempotency_key)
        except ValueError:
            raise HTTPException(422, "Idempotency-Key must be a UUID") from None
    return Op(request.method, request.url.path, key, key is not None and x_defer_recompute == "1")


OpDep = Annotated[Op, Depends(client_op)]


def _hash(op: Op, body: dict | None) -> str:
    text = json.dumps([op.method, op.path, body], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _clear_pending(session: Session, owner: uuid.UUID) -> None:
    """Inside a recompute's transaction: the derived rows now match the owner data."""
    session.execute(
        update(ClientOp)
        .where(ClientOp.owner_id == owner, ClientOp.recompute_pending)
        .values(recompute_pending=False)
    )
    if (mark := session.get(RecomputeMark, owner)) is not None:
        session.delete(mark)


def mark(session: Session, owner: uuid.UUID) -> None:
    """Inside a write's transaction: the next read recomputes (D-106)."""
    row = session.get(RecomputeMark, owner) or RecomputeMark(owner_id=owner)
    row.marked_at, row.failed_at, row.failure = datetime.now(UTC), None, None
    session.add(row)


def _error(exc: ActionError | OwnerDataError) -> tuple[int, str]:
    if isinstance(exc, OwnerDataError):
        return 409, str(exc)
    return {"not_found": 404, "conflict": 409}.get(exc.kind, 422), str(exc)


def write(
    session: Session,
    owner: uuid.UUID,
    op: Op,
    action: Callable[[], dict],
    body: dict | None = None,
    *,
    recomputes: bool = True,
    status: int = 200,
) -> dict | JSONResponse:
    """Commit one owner answer, its stored answer and a recompute mark, all or nothing.

    Owner actions read derived rows (the party a transaction matches), so the recompute the
    writes before this one left runs first, as a read would; if it fails, the answer is still
    saved (D-106). This answer's own recompute is left to the next read.
    """
    ensure_fresh(session, owner)
    if op.key is None:
        return _plain(session, owner, action, recomputes)
    slot = (owner, op.key)
    with _running_guard:
        if slot in _running:
            return JSONResponse({"detail": IN_PROGRESS}, status_code=409)
        _running.add(slot)
    try:
        with owner_lock(session, owner):
            return _keyed(session, owner, op, action, _hash(op, body), recomputes, status)
    finally:
        with _running_guard:
            _running.discard(slot)


def _plain(session: Session, owner: uuid.UUID, action, recomputes: bool) -> dict:
    """No key: nothing stored about the request; the owner data and the mark commit."""
    with owner_lock(session, owner):
        try:
            result = action()
            if recomputes:
                mark(session, owner)
            session.commit()
        except (ActionError, OwnerDataError) as exc:
            session.rollback()
            raise HTTPException(*_error(exc)) from None
    return {"result": result, "recompute": DEFERRED} if recomputes else result


def _keyed(session, owner, op: Op, action, request_hash: str, recomputes: bool, status: int):
    found = session.get(ClientOp, (owner, op.key))
    if found is not None:
        session.rollback()
        if found.request_hash != request_hash:
            return JSONResponse({"detail": KEY_REUSED}, status_code=422)
        return JSONResponse(found.response_body, status_code=found.status_code)

    now = datetime.now(UTC)
    row = ClientOp(
        owner_id=owner, op_id=op.key, received_at=now, method=op.method, path=op.path,
        request_hash=request_hash,
    )  # fmt: skip

    def finish(code: int, response: dict, pending: bool = False) -> None:
        row.status_code, row.response_body = code, response
        row.completed_at, row.recompute_pending = datetime.now(UTC), pending

    try:
        session.add(row)
        session.flush()
        result = action()
        # A write that needs no recompute answers its result as it is (POST /labels).
        response = {"result": result, "recompute": DEFERRED} if recomputes else result
        finish(status, response, pending=recomputes)
        if recomputes:
            mark(session, owner)
        session.commit()
        return JSONResponse(response, status_code=status)
    except (ActionError, OwnerDataError) as exc:
        session.rollback()
        code, detail = _error(exc)
    # A final 4xx: the write is rolled back; store the answer on its own.
    stored = ClientOp(
        owner_id=owner, op_id=op.key, received_at=now, method=op.method, path=op.path,
        request_hash=request_hash, status_code=code, response_body={"detail": detail},
        completed_at=datetime.now(UTC),
    )  # fmt: skip
    session.add(stored)
    session.commit()
    return JSONResponse({"detail": detail}, status_code=code)


def other_versions(session: Session, owner: uuid.UUID) -> bool:
    """The last done run was made by other engine versions than the running ones."""
    versions = session.scalar(
        select(DeriveRun.versions)
        .where(DeriveRun.owner_id == owner, DeriveRun.status == "done")
        .order_by(DeriveRun.id.desc())
        .limit(1)
    )
    return versions is not None and dict(versions) != VERSIONS


def ensure_fresh(session: Session, owner: uuid.UUID) -> None:
    """Before anything is read: recompute when a write marked the owner (D-106), an older
    deferred write left a mark (D-094), or new engine versions run (D-102). One transaction.

    A recompute that fails (or stops for an engine change) is logged by error type only; the
    mark keeps `failed_at`, so reads serve the stored rows ("being updated") and only a read
    5 minutes later tries again. The owner data is never touched here.
    """
    found = session.get(RecomputeMark, owner)
    pending = select(exists().where(ClientOp.owner_id == owner, ClientOp.recompute_pending))
    stale = found is not None or bool(session.scalar(pending)) or other_versions(session, owner)
    if not stale:
        return
    failed_at = found.failed_at if found is not None else None
    if failed_at is not None and datetime.now(UTC) - failed_at < RETRY_AFTER:
        return
    trigger = "read" if found is None else "owner"
    try:
        outcome = recompute(
            session, owner, trigger, before_commit=lambda _: _clear_pending(session, owner)
        )
    except Exception as exc:  # the message could hold data: keep the type only
        reason = type(exc).__name__
    else:
        reason = "StoppedForEngineChange" if outcome.status == "stopped" else ""
    if not reason:
        return
    session.rollback()
    row = session.get(RecomputeMark, owner) or RecomputeMark(
        owner_id=owner, marked_at=datetime.now(UTC)
    )
    row.failed_at, row.failure = datetime.now(UTC), reason[:40]
    session.add(row)
    session.commit()
    log.warning("recompute on read failed (%s); serving stored rows", reason)


def fresh_reads(
    owner: Annotated[uuid.UUID, Depends(current_owner)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    ensure_fresh(session, owner)
