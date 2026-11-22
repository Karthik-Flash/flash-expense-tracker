"""Several users (5C, D-128 to D-131). docs/api.md, "Users, invites and the account".

- POST /api/v1/signup (no login): an invite code, an email and a password make a member: a
  confirmed Supabase login (Admin API), a new owner_id and its app_users row, the code
  marked used; all or nothing. Rate-limited per IP, per code and overall. Errors are
  generic: never whether an email exists, never why a code failed.
- POST/GET/DELETE /api/v1/invites and GET /api/v1/members: the admin only. A code is shown
  once (only its SHA-256 is stored), lasts 7 days and is used once.
- POST /api/v1/account/delete: a fresh sign-in (password in the last 10 minutes) and
  {"confirm": "DELETE"}; every row of the owner goes (pipeline/account.py), then the login.
  The admin cannot delete their own account from the app.
"""

import hashlib
import logging
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import ops, supabase_admin
from app.api.auth import Caller, current_user, fresh_login, require_admin
from app.db import get_session
from app.models import AppUser, Device, Invite, Transaction
from app.pipeline import account

router = APIRouter(prefix="/api/v1")
Db = Annotated[Session, Depends(get_session)]
Admin = Annotated[Caller, Depends(require_admin)]
log = logging.getLogger(__name__)

INVITE_DAYS = 7
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I: read aloud or typed by hand
CODE_LENGTH = 12  # 60 random bits
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BAD_CODE = "This invite code doesn't work. Check it, or ask for a new one."
NO_ACCOUNT = "Could not create the account. Check the details, or ask for a new invite."
TOO_MANY = "Too many tries. Wait a few minutes and try again."


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z") if moment else None


def normal_code(code: str) -> str:
    """As typed or pasted: case, spaces and dashes do not matter."""
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def code_hash(code: str) -> str:
    return hashlib.sha256(normal_code(code).encode()).hexdigest()


def new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i : i + 4] for i in range(0, CODE_LENGTH, 4))


# --- rate limits -------------------------------------------------------------------------


class Limiter:
    """At most `limit` attempts per key in `window` seconds.
    ponytail: in this process only (Render runs one); a shared store when it runs more."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit, self.window = limit, window
        self.hits: defaultdict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            hits = self.hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


PER_IP = Limiter(10, 15 * 60)
PER_CODE = Limiter(5, 60 * 60)
OVERALL = Limiter(60, 60 * 60)
_signup_lock = threading.Lock()


def client_ip(request: Request) -> str:
    """The first X-Forwarded-For hop (Render's proxy sets it), else the socket's address."""
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")


class SignUp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=72)
    code: str = Field(max_length=40)


@router.post("/signup", status_code=201)
def signup(body: SignUp, request: Request, session: Db) -> dict:
    ip_ok = PER_IP.allow(client_ip(request))
    code_ok = PER_CODE.allow(code_hash(body.code))
    if not (ip_ok and code_ok and OVERALL.allow("all")):
        raise HTTPException(429, TOO_MANY)
    email = body.email.strip().lower()
    if not EMAIL.fullmatch(email):
        raise HTTPException(422, "Enter an email address.")
    now = datetime.now(UTC)
    with _signup_lock:
        invite = session.scalar(
            select(Invite).where(Invite.code_hash == code_hash(body.code)).with_for_update()
        )
        if (
            invite is None
            or invite.used_at is not None
            or invite.revoked_at is not None
            or invite.expires_at <= now
        ):
            session.rollback()
            raise HTTPException(400, BAD_CODE)
        try:
            uid = supabase_admin.create_user(email, body.password)
        except supabase_admin.AdminError as exc:
            session.rollback()
            log.warning("signup: login not created (%s)", exc.code)
            raise HTTPException(503 if exc.code != "refused" else 400, NO_ACCOUNT) from None
        owner = uuid.uuid4()
        try:
            session.add(AppUser(auth_uid=uid, owner_id=owner, role="member", email=email))
            invite.used_by, invite.used_at = owner, now
            session.commit()
        except Exception:
            session.rollback()
            try:  # all or nothing: the login goes again
                supabase_admin.delete_user(uid)
            except supabase_admin.AdminError as exc:
                log.warning("signup: login left after a failed save (%s)", exc.code)
            raise HTTPException(503, NO_ACCOUNT) from None
    return {"ok": True}


# --- invites and members (the admin) ------------------------------------------------------


def invite_item(i: Invite) -> dict:
    return {
        "id": i.id,
        "created_utc": _iso(i.created_at),
        "expires_utc": _iso(i.expires_at),
        "used_utc": _iso(i.used_at),
        "revoked_utc": _iso(i.revoked_at),
    }


def invites_of(session: Session, admin: uuid.UUID) -> list[dict]:
    rows = session.scalars(select(Invite).where(Invite.created_by == admin).order_by(Invite.id))
    return [invite_item(i) for i in rows]


def members(session: Session) -> list[dict]:
    """Everyone who uses Flash: email, role, joined, last sync; counts only, never data."""
    txns = dict(
        session.execute(
            select(Transaction.owner_id, func.count())
            .where(Transaction.status == "active")
            .group_by(Transaction.owner_id)
        ).all()
    )
    phones = dict(
        session.execute(
            select(Device.owner_id, func.count())
            .where(Device.revoked_at.is_(None))
            .group_by(Device.owner_id)
        ).all()
    )
    rows = session.scalars(
        select(AppUser).order_by(AppUser.role, AppUser.created_at, AppUser.auth_uid)
    )
    return [
        {
            "email": u.email,
            "role": u.role,
            "joined_utc": _iso(u.created_at),
            "last_seen_utc": _iso(u.last_seen_at),
            "transactions": txns.get(u.owner_id, 0),
            "phones": phones.get(u.owner_id, 0),
        }
        for u in rows
    ]


@router.post("/invites", status_code=201)
def create_invite(caller: Admin, session: Db) -> dict:
    """A new code, shown only in this answer. Not an outbox write (the answer is a secret)."""
    code = new_code()
    row = Invite(
        code_hash=code_hash(code), created_by=caller.owner_id,
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_DAYS),
    )  # fmt: skip
    session.add(row)
    session.commit()
    return {"invite": invite_item(row), "code": code}


@router.get("/invites")
def list_invites(caller: Admin, session: Db) -> dict:
    return {"invites": invites_of(session, caller.owner_id)}


@router.delete("/invites/{invite_id}")
def revoke_invite(caller: Admin, session: Db, op: ops.OpDep, invite_id: int):
    """Revoke an unused invite (an outbox write). A used one: 409."""

    def action() -> dict:
        row = session.get(Invite, invite_id)
        if row is None or row.created_by != caller.owner_id:
            raise ops.ActionError("not_found", "no such invite")
        if row.used_at is not None:
            raise ops.ActionError("conflict", "this invite was used")
        row.revoked_at = row.revoked_at or datetime.now(UTC)
        session.flush()
        return invite_item(row)

    return ops.write(session, caller.owner_id, op, action, recomputes=False)


@router.get("/members")
def list_members(caller: Admin, session: Db) -> dict:
    return {"members": members(session)}


# --- delete my account ---------------------------------------------------------------------


class DeleteAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: str


@router.post("/account/delete")
def delete_account(
    body: DeleteAccount, caller: Annotated[Caller, Depends(current_user)], session: Db
) -> dict:
    """Every row of this account, then its login. Never through the outbox."""
    if body.confirm != "DELETE":
        raise HTTPException(422, "type DELETE to confirm")
    if caller.admin:
        raise HTTPException(409, "admin_cannot_delete")
    if not fresh_login(caller.claims):
        raise HTTPException(409, "fresh_login_required")
    counts = account.delete_owner(session, caller.owner_id, caller.auth_uid)
    gone = account.finish_auth(session, caller.auth_uid, supabase_admin.delete_user)
    if not gone:
        log.warning("account deleted; login deletion pending (auth-cleanup)")
    return {"deleted": sum(counts.values()), "login_deleted": gone}
