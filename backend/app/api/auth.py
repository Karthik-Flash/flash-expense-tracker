"""Login: verify a Supabase Auth access token and map its user to an owner (D-078).

Tokens are ES256 only, checked against the project's public keys
(<SUPABASE_URL>/auth/v1/.well-known/jwks.json): signature, exp, issuer
<SUPABASE_URL>/auth/v1 and audience "authenticated". The keys are cached and fetched
again when a token names an unknown key id (at most once a minute).

Since 5C (D-129) the token's sub is looked up in app_users (owner_id, role admin or member);
an AUTH_USERS entry ("<sub>:<owner_id>") with no row yet is added as admin on its first
request. Missing settings (or a malformed AUTH_USERS): 503. Missing or bad token: 401. A
valid token whose user is in neither: 403.
"""

import json
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import AppUser

ALGORITHM = "ES256"
AUDIENCE = "authenticated"
REFRESH_EVERY = 60.0  # seconds between key fetches caused by unknown key ids
LEEWAY = 10  # seconds of clock difference allowed on exp


def fetch_jwks(url: str) -> dict:
    """The project's public keys. Replaced in tests: tests make no network calls."""
    with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 (https URL from settings)
        return json.load(response)


class KeyCache:
    def __init__(self) -> None:
        self.keys: dict[str, object] = {}
        self.url = ""
        self.fetched_at = float("-inf")
        self.lock = threading.Lock()

    def key(self, url: str, kid: str) -> object | None:
        with self.lock:
            if url != self.url:  # a new project: forget the old keys
                self.keys, self.url, self.fetched_at = {}, url, float("-inf")
            if kid not in self.keys and time.monotonic() - self.fetched_at >= REFRESH_EVERY:
                self.fetched_at = time.monotonic()
                found = jwt.PyJWKSet.from_dict(fetch_jwks(url))
                self.keys = {k.key_id: k.key for k in found.keys if k.key_id}
            return self.keys.get(kid)


keys = KeyCache()


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


def verify(token: str, base_url: str) -> dict:
    """The token's claims, or raise HTTPException 401 (503 when the keys cannot be fetched)."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise _unauthorised("malformed token") from None
    if header.get("alg") != ALGORITHM or not isinstance(header.get("kid"), str):
        raise _unauthorised("token must be ES256 with a key id")
    try:
        key = keys.key(f"{base_url}/auth/v1/.well-known/jwks.json", header["kid"])
    except (OSError, ValueError, jwt.PyJWTError):
        raise HTTPException(503, "login keys unavailable") from None
    if key is None:
        raise _unauthorised("unknown signing key")
    try:
        return jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=f"{base_url}/auth/v1",
            leeway=LEEWAY,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError:
        raise _unauthorised("invalid token") from None


@dataclass(frozen=True)
class Caller:
    """Who is asking: the login, the owner_id its data belongs to, its role, its claims."""

    auth_uid: str
    owner_id: uuid.UUID
    role: str
    claims: dict = field(compare=False, repr=False)

    @property
    def admin(self) -> bool:
        return self.role == "admin"


SEEN_EVERY = timedelta(minutes=10)  # app_users.last_seen_at ("last sync") moves in these steps


def _app_user(session: Session, sub: str, claims: dict) -> AppUser | None:
    """The login's app_users row. An AUTH_USERS entry with no row yet becomes one, as admin
    (D-129): the seed on the first request, and a fallback until the owner removes it."""
    row = session.get(AppUser, sub)
    if row is not None:
        return row
    owner = (settings.auth_user_map or {}).get(sub)
    if owner is None:
        return None
    email = claims.get("email") if isinstance(claims.get("email"), str) else None
    session.add(AppUser(auth_uid=sub, owner_id=owner, role="admin", email=email))
    try:
        session.commit()
    except IntegrityError:  # a parallel first request added it
        session.rollback()
    return session.get(AppUser, sub)


def current_user(
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> Caller:
    """FastAPI dependency: the logged-in user, from app_users (D-129)."""
    base_url = settings.supabase_url.rstrip("/")
    if not base_url or settings.auth_user_map is None:
        raise HTTPException(503, "login is not configured")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorised("missing bearer token")
    claims = verify(token.strip(), base_url)
    row = _app_user(session, str(claims["sub"]), claims)
    if row is None:
        raise HTTPException(403, "this user has no access")
    now = datetime.now(UTC)
    if row.last_seen_at is None or now - row.last_seen_at >= SEEN_EVERY:
        row.last_seen_at = now
        session.commit()
    return Caller(row.auth_uid, row.owner_id, row.role, claims)


def current_owner(caller: Annotated[Caller, Depends(current_user)]) -> uuid.UUID:
    """FastAPI dependency: the owner_id of the logged-in user."""
    return caller.owner_id


def require_admin(caller: Annotated[Caller, Depends(current_user)]) -> Caller:
    if not caller.admin:
        raise HTTPException(403, "only the admin can do this")
    return caller


FRESH = timedelta(minutes=10)


def fresh_login(claims: dict, now: datetime | None = None) -> bool:
    """The password was entered in the last 10 minutes: the token's `amr` holds a password
    entry with that timestamp (a refreshed token keeps the sign-in time; D-131)."""
    now = now or datetime.now(UTC)
    for entry in claims.get("amr") or ():
        if isinstance(entry, dict) and entry.get("method") == "password":
            at = entry.get("timestamp")
            if isinstance(at, int | float) and now - datetime.fromtimestamp(at, UTC) <= FRESH:
                return True
    return False
