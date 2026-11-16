"""Login: verify a Supabase Auth access token and map its user to an owner (D-078).

Tokens are ES256 only, checked against the project's public keys
(<SUPABASE_URL>/auth/v1/.well-known/jwks.json): signature, exp, issuer
<SUPABASE_URL>/auth/v1 and audience "authenticated". The keys are cached and fetched
again when a token names an unknown key id (at most once a minute).

AUTH_USERS maps the token's sub to an owner_id. Missing settings: 503. Missing or bad
token: 401. A valid token whose user is not in the map: 403.
"""

import json
import threading
import time
import urllib.request
import uuid
from typing import Annotated

import jwt
from fastapi import Header, HTTPException

from app.config import settings

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


def current_owner(authorization: Annotated[str | None, Header()] = None) -> uuid.UUID:
    """FastAPI dependency: the owner_id of the logged-in user."""
    base_url, users = settings.supabase_url.rstrip("/"), settings.auth_user_map
    if not base_url or not users:
        raise HTTPException(503, "login is not configured")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorised("missing bearer token")
    claims = verify(token.strip(), base_url)
    owner = users.get(str(claims["sub"]))
    if owner is None:
        raise HTTPException(403, "this user has no access")
    return owner
