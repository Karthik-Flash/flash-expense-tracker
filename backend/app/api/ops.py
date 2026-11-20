"""Owner writes, once (D-091, D-092, D-094; docs/design/phase-4b2-outbox.md).

Every owner-write route runs through `write()`. With an `Idempotency-Key` header the
write, its recompute and the stored answer (table client_ops) commit in one transaction;
the same key again gets the stored answer and writes nothing. Without the header nothing
changes. `X-Defer-Recompute: 1` (with a key) skips the recompute and marks the row; every
read runs `ensure_fresh()` first, so derived data never lags owner data. The same first read
also recomputes when the stored rows were made by other engine versions, as after a deploy
(D-102).
"""

import hashlib
import json
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.api.auth import current_owner
from app.db import get_session
from app.models import ClientOp, DeriveRun
from app.pipeline.owner_actions import ActionError
from app.pipeline.recompute import VERSIONS, Outcome, OwnerDataError, owner_lock, recompute

IN_PROGRESS = "in_progress"
KEY_REUSED = "idempotency_key_reused"
STOPPED = "recompute stopped: an engine change needs the owner's check"

_running: set[tuple[uuid.UUID, uuid.UUID]] = set()  # keys being written in this process
_running_guard = threading.Lock()
# Owners whose version refresh failed in this process: not tried again on every read (the
# rows keep their "being updated" notice; the next owner write or a restart tries again).
_refresh_failed: set[uuid.UUID] = set()
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
    session.execute(
        update(ClientOp)
        .where(ClientOp.owner_id == owner, ClientOp.recompute_pending)
        .values(recompute_pending=False)
    )


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
    """Run one owner answer (and its recompute) under the owner's lock, all or nothing."""
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
    """As before 4B-2: no key, nothing stored."""
    with owner_lock(session, owner):
        try:
            result = action()
            if not recomputes:
                session.commit()
                return result
            outcome = recompute(
                session, owner, "owner", before_commit=lambda _: _clear_pending(session, owner)
            )
        except (ActionError, OwnerDataError) as exc:
            session.rollback()
            raise HTTPException(*_error(exc)) from None
    if outcome.status == "stopped":
        raise HTTPException(409, STOPPED)
    return {"result": result, "recompute": {"status": outcome.status, "run": outcome.run_id}}


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
        if not recomputes or op.defer:
            # A write that needs no recompute answers its result as it is (POST /labels).
            response = {"result": result, "recompute": {"status": "deferred", "run": None}}
            response = response if recomputes else result
            finish(status, response, pending=recomputes)
            session.commit()
            return JSONResponse(response, status_code=status)

        def before_commit(outcome: Outcome) -> None:
            _clear_pending(session, owner)
            finish(status, {
                "result": result, "recompute": {"status": outcome.status, "run": outcome.run_id}
            })  # fmt: skip

        outcome = recompute(session, owner, "owner", before_commit=before_commit)
        if outcome.status == "stopped":
            code, detail = 409, STOPPED
        else:
            return JSONResponse(row.response_body, status_code=status)
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
    """Before anything is read: run the recompute a deferred write skipped (D-094), or the
    one a deploy of new engine versions needs (D-102). Either is one transaction.

    A deferred recompute that fails fails the read, as before. A version refresh that fails
    is logged and the read goes on with the stored rows, which say "being updated".
    """
    pending = select(exists().where(ClientOp.owner_id == owner, ClientOp.recompute_pending))
    if session.scalar(pending):
        recompute(session, owner, "owner", before_commit=lambda _: _clear_pending(session, owner))
        return
    if owner in _refresh_failed or not other_versions(session, owner):
        return
    try:
        outcome = recompute(session, owner, "read")
    except Exception as exc:  # the message could hold data: log the type only
        outcome, reason = None, type(exc).__name__
    else:
        reason = "a transaction would lose its owner match" if outcome.status == "stopped" else ""
    if reason:
        session.rollback()
        _refresh_failed.add(owner)
        log.warning("version refresh on read failed (%s); serving stored rows", reason)


def fresh_reads(
    owner: Annotated[uuid.UUID, Depends(current_owner)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    ensure_fresh(session, owner)
