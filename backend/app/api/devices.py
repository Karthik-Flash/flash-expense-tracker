"""Phones that upload bank SMS (D-122) and the SMS ingest route (D-123). docs/api.md.

- POST/GET/DELETE /api/v1/devices take the login token, like every /api/v1 route. POST makes
  a random 256-bit device token, stores only its SHA-256 and returns it once; registering the
  same device_id again replaces the token (a lost answer is repaired by asking again). POST is
  not an outbox write: its answer is a secret that a stored replay would have to keep.
- POST /api/v1/ingest/sms takes the device token and nothing else: the device token is no
  login token, so every other route refuses it (401), and no login token is a device token.
  Each message from a bank sender (shared/bank_senders.json, minus the non-banks) goes
  through store.ingest() exactly as import-sms stores it, source live_sms: one SMS imported on
  the laptop and uploaded by the phone is one raw message (the same content hash). Anything
  else is refused and never stored. A new message marks the owner for a recompute (D-106).

Bodies, senders and tokens are never logged; the request log has the route template only.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import __version__
from app.api import ops
from app.api.auth import current_owner
from app.api.v1 import engine_name
from app.config import settings
from app.db import get_session
from app.engine.categorise import CATEGORIES
from app.engine.filters import is_otp, is_promotional
from app.engine.senders import is_bank, parse_sender
from app.models import (
    DEVICE_NAME_MAX,
    AppUser,
    Device,
    ImportBatch,
    RawMessage,
    Transaction,
    TxnDerived,
)
from app.pipeline import version
from app.pipeline.dedupe import content_hash
from app.pipeline.owner_actions import ActionError
from app.pipeline.recompute import owner_lock
from app.pipeline.store import Counts, ingest, parser_versions

router = APIRouter(prefix="/api/v1")
Owner = Annotated[uuid.UUID, Depends(current_owner)]
Db = Annotated[Session, Depends(get_session)]
SOURCE = "live_sms"
MAX_BATCH = 500
MAX_BODY_BYTES = 2048
SMS_SOURCES = ("sms_backup", SOURCE)  # where the newest SMS the server has comes from
Status = Literal["stored", "duplicate", "refused_not_bank", "refused_filtered"]


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z") if moment else None


def device_item(d: Device) -> dict:
    """What the app sees of a device: never the token or its hash."""
    return {
        "device_id": str(d.device_id),
        "name": d.name,
        "created_utc": _iso(d.created_at),
        "last_seen_utc": _iso(d.last_seen_at),
        "revoked_utc": _iso(d.revoked_at),
    }


def devices_of(session: Session, owner: uuid.UUID) -> list[dict]:
    rows = session.scalars(select(Device).where(Device.owner_id == owner).order_by(Device.id))
    return [device_item(d) for d in rows]


def newest_sms(session: Session, owner: uuid.UUID) -> str | None:
    """When the newest SMS the server has for this owner arrived (UTC), from any route."""
    return _iso(
        session.scalar(
            select(func.max(RawMessage.received_at)).where(
                RawMessage.owner_id == owner, RawMessage.source.in_(SMS_SOURCES)
            )
        )
    )


class NewDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: uuid.UUID
    name: str = Field(max_length=200)


@router.post("/devices", status_code=201)
def register(owner: Owner, session: Db, body: NewDevice) -> dict:
    """This phone, with a new device token (shown only in this answer)."""
    name = " ".join(body.name.split())[:DEVICE_NAME_MAX]
    if not name:
        raise HTTPException(422, "a device name has 1 to 60 characters")
    token = secrets.token_urlsafe(32)  # 256 random bits
    row = session.scalar(
        select(Device).where(Device.owner_id == owner, Device.device_id == body.device_id)
    )
    if row is None:
        row = Device(owner_id=owner, device_id=body.device_id)
        session.add(row)
    row.name, row.token_hash, row.revoked_at = name, token_hash(token), None
    version.bump(session, owner)  # the phones list (D-140)
    session.commit()
    return {"device": device_item(row), "token": token}


@router.get("/devices")
def list_devices(owner: Owner, session: Db) -> dict:
    return {"devices": devices_of(session, owner)}


@router.delete("/devices/{device_id}")
def revoke(owner: Owner, session: Db, op: ops.OpDep, device_id: uuid.UUID):
    """Its token stops working at once. Revoking twice is the same answer (an outbox write)."""

    def action() -> dict:
        row = session.scalar(
            select(Device).where(Device.owner_id == owner, Device.device_id == device_id)
        )
        if row is None:
            raise ActionError("not_found", "no such device")
        row.revoked_at = row.revoked_at or datetime.now(UTC)
        session.flush()
        return device_item(row)

    return ops.write(session, owner, op, action, recomputes=False)


# --- ingest --------------------------------------------------------------------------------


def current_device(session: Db, authorization: Annotated[str | None, Header()] = None) -> Device:
    """The device whose token this is. 401 for no token, an unknown one or a revoked device."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "missing device token", headers={"WWW-Authenticate": "Bearer"})
    row = session.scalar(select(Device).where(Device.token_hash == token_hash(token.strip())))
    if row is None:
        raise HTTPException(401, "invalid device token", headers={"WWW-Authenticate": "Bearer"})
    if row.revoked_at is not None or not is_user(session, row.owner_id):
        # A revoked phone, or the phone of a removed or deleted user (5C): it stops for good.
        raise HTTPException(401, "device_revoked", headers={"WWW-Authenticate": "Bearer"})
    return row


def is_user(session: Session, owner: uuid.UUID) -> bool:
    """The owner still has a login: an app_users row, or an AUTH_USERS entry (the fallback)."""
    found = session.scalar(select(AppUser.auth_uid).where(AppUser.owner_id == owner))
    return found is not None or owner in (settings.auth_user_map or {}).values()


class Sms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender: str = Field(min_length=1, max_length=64)
    body: str = Field(min_length=1, max_length=MAX_BODY_BYTES)
    received_at_utc: AwareDatetime  # the inbox row's date: what an SMS backup holds
    device_msg_id: str = Field(min_length=1, max_length=64)
    # 5B-2 (D-139): "live" when the phone sends the SMS_RECEIVED copy because its inbox row
    # never came; "inbox" (also when absent: phones from before 5B-2) for an inbox row.
    origin: Literal["inbox", "live"] = "inbox"

    @field_validator("body")
    @classmethod
    def at_most_2_kb(cls, body: str) -> str:
        if len(body.encode("utf-8")) > MAX_BODY_BYTES:
            raise ValueError(f"a body has at most {MAX_BODY_BYTES} bytes")
        return body


class SmsBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[Sms] = Field(min_length=1, max_length=MAX_BATCH)


def refusal(sender: str, body: str) -> Status | None:
    """Why the server will not store this message, as import-sms would skip it."""
    core, suffix = parse_sender(sender)
    if not is_bank(core):
        return "refused_not_bank"
    if is_promotional(suffix) or is_otp(body):
        return "refused_filtered"
    return None


@router.post("/ingest/sms")
def ingest_sms(
    batch: SmsBatch, session: Db, device: Annotated[Device, Depends(current_device)]
) -> dict:
    owner, now = device.owner_id, datetime.now(UTC)
    counts = Counts()
    results: list[dict] = []
    with owner_lock(session, owner):
        hashes = sorted(
            content_hash(parse_sender(m.sender)[0], m.body, m.received_at_utc)
            for m in batch.messages
        )
        run = ImportBatch(
            owner_id=owner, source=SOURCE, started_at=now, status="running",
            input_fingerprint=hashlib.sha256("".join(hashes).encode()).hexdigest(),
            app_version=__version__, parser_versions=parser_versions(), counts={},
        )  # fmt: skip
        session.add(run)
        session.flush()
        created: dict[int, str] = {}  # new transaction -> the device_msg_id it came from
        for m in batch.messages:
            status = refusal(m.sender, m.body)
            if status is None:
                before, made = counts.raw_new, len(counts.new_ids)
                received = m.received_at_utc.astimezone(UTC)
                core = parse_sender(m.sender)[0]
                ingest(session, owner, run.id, SOURCE, m.sender, core, m.body, received,
                       counts, origin=m.origin)  # fmt: skip
                status = "stored" if counts.raw_new > before else "duplicate"
                created |= dict.fromkeys(counts.new_ids[made:], m.device_msg_id)
            else:
                counts.skipped[status] += 1
            counts.read += 1
            results.append({"device_msg_id": m.device_msg_id, "status": status})
        if counts.raw_new:
            ops.mark(session, owner)  # the next read recomputes (D-106)
        device.last_seen_at = now
        run.status, run.finished_at = "done", datetime.now(UTC)
        run.counts = counts.as_dict()
        version.bump(session, owner)  # the phone's last upload and maybe payments (D-140)
        session.commit()
    tally = {s: 0 for s in Status.__args__}
    for r in results:
        tally[r["status"]] += 1
    return {
        "results": results,
        "counts": tally,
        "new_transactions": new_items(session, owner, created),
    }


def new_items(session: Session, owner: uuid.UUID, created: dict[int, str]) -> list[dict]:
    """5B-2 (D-141): the transactions this request created, for the phone's notification:
    never a duplicate, a notice, a refused message or anything else of the owner. Their
    category and role need the recompute, which runs here (as a read would); if it fails, the
    engine's name alone is sent."""
    if not created:
        return []
    ops.ensure_fresh(session, owner)
    rows = session.execute(
        select(Transaction, TxnDerived)
        .outerjoin(TxnDerived, TxnDerived.transaction_id == Transaction.id)
        .where(Transaction.owner_id == owner, Transaction.id.in_(created))
        .order_by(Transaction.txn_time_utc, Transaction.id)
    ).all()
    out = []
    for t, d in rows:
        person_credit = t.direction == "credit" and d is not None and d.merchant_kind == "person"
        waiting = d is not None and (
            d.role == "uncertain" or (d.role, d.role_basis) == ("payback", "engine")
        )
        out.append({
            "device_msg_id": created[t.id],
            "id": t.id,
            "direction": t.direction,
            "amount_paise": t.amount_paise,
            # 5G-A: when it was, so the phone's notification can open its sheet at once.
            "time_utc": _iso(t.txn_time_utc),
            "display_name": d.display_name if d else engine_name(t),
            "category": d.category if d else None,
            "category_name": CATEGORIES.get(d.category) if d else None,
            "role": d.role if d else None,
            # "Paid back?": a credit from a person waiting for the owner's answer.
            "paid_back_question": person_credit and waiting,
        })  # fmt: skip
    return out
