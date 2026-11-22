"""The Supabase Auth Admin API, server side only (D-128, D-131).

Per Supabase's docs (guides/api/api-keys, reference auth-admin-createuser / -deleteuser):
the project's secret key (sb_secret_...) is not a JWT and goes on the `apikey` header, never
`Authorization: Bearer`; POST <SUPABASE_URL>/auth/v1/admin/users with `email`, `password` and
`email_confirm: true` makes a confirmed login (no email is sent for a confirmed one) and
answers the user with its `id`; DELETE <SUPABASE_URL>/auth/v1/admin/users/<id> deletes it.
stdlib urllib, like the key fetch in auth.py: no HTTP package at runtime.

Errors carry a short code only: Supabase's own message may name the email and is never
logged or shown.
"""

import json
import urllib.error
import urllib.request

from app.config import settings

TIMEOUT = 10  # seconds


class AdminError(Exception):
    """code: not_configured, refused (4xx), unavailable (5xx or no answer)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """(status, JSON body). Replaced in tests: tests make no network calls."""
    url = settings.supabase_url.rstrip("/") + "/auth/v1" + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)  # noqa: S310 (https from settings)
    req.add_header("apikey", settings.supabase_secret_key)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:  # noqa: S310
            text = response.read()
            return response.status, json.loads(text) if text else {}
    except urllib.error.HTTPError as e:
        return e.code, {}


def _call(method: str, path: str, body: dict | None = None, gone_ok: bool = False) -> dict:
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise AdminError("not_configured")
    try:
        status, answer = request(method, path, body)
    except (OSError, ValueError):
        raise AdminError("unavailable") from None
    if status >= 500:
        raise AdminError("unavailable")
    if status == 404 and gone_ok:
        return {}
    if status >= 400:
        raise AdminError("refused")
    return answer


def create_user(email: str, password: str) -> str:
    """A confirmed login; its Supabase user id."""
    answer = _call(
        "POST", "/admin/users", {"email": email, "password": password, "email_confirm": True}
    )
    uid = answer.get("id")
    if not isinstance(uid, str) or not uid:
        raise AdminError("unavailable")
    return uid


def delete_user(uid: str) -> None:
    """Deletes the login; one already gone (404) counts as deleted."""
    _call("DELETE", f"/admin/users/{uid}", gone_ok=True)
