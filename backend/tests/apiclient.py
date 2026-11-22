"""Shared by the API tests: a local EC key, a fake JWKS, a test client and FAKE data.

The fixtures (jwks, client, data) are registered in conftest.py.
"""

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import auth
from app.config import settings
from app.db import get_session
from app.main import app
from tests.smsdata import full_rows, write_backup
from tests.test_category_storage import LATER
from tests.test_storage import PAIR

BASE = "https://test.supabase.co"
SUB_A, SUB_B, SUB_X = "user-a", "user-b", "user-x"
OWNER_A, OWNER_B = settings.owner_id, uuid.UUID("00000000-0000-0000-0000-00000000000b")
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def jwk(key, kid: str) -> dict:
    public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    return public | {"kid": kid, "alg": "ES256", "use": "sig"}


def token(sub: str = SUB_A, key=KEY, kid: str = "k1", alg: str = "ES256", **claims) -> str:
    now = int(time.time())
    body = {"sub": sub, "aud": "authenticated", "iss": f"{BASE}/auth/v1", "exp": now + 600}
    return jwt.encode(body | claims, key, algorithm=alg, headers={"kid": kid})


def bearer(value: str) -> dict:
    return {"Authorization": f"Bearer {value}"}


@pytest.fixture
def jwks(monkeypatch: pytest.MonkeyPatch) -> dict:
    """The fake key set, and how often it was fetched."""
    state = {"keys": [jwk(KEY, "k1")], "fetches": 0}

    def fetch(url: str) -> dict:
        assert url == f"{BASE}/auth/v1/.well-known/jwks.json"
        state["fetches"] += 1
        return {"keys": list(state["keys"])}

    monkeypatch.setattr(auth, "fetch_jwks", fetch)
    monkeypatch.setattr(auth, "keys", auth.KeyCache())
    monkeypatch.setattr(settings, "supabase_url", BASE + "/")
    monkeypatch.setattr(settings, "auth_users", f"{SUB_A}:{OWNER_A}, {SUB_B}:{OWNER_B}")
    return state


@pytest.fixture
def client(db_engine, jwks):
    factory = sessionmaker(db_engine, expire_on_commit=False)

    def session():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = session
    yield TestClient(app)
    app.dependency_overrides.clear()


# A payment to the person who later sends test.user@okaxis's credit (fixture H02, 7 Jan):
# since reconcile-1.7.0 that credit is a payback guess only because of it (D-134).
FRIEND_PAID = (
    "HDFCBK",
    "Sent Rs.777.00\nFrom HDFC Bank A/C *0001\nTo test.user@okaxis\nOn 03/01/26\n"
    "Ref 000000000077\nNot You?\nCall 18000000001/SMS BLOCK UPI to 9000000001\n",
    datetime(2026, 1, 3, 6, 30, tzinfo=UTC),
)


@pytest.fixture
def data(run, tmp_path: Path, monkeypatch) -> None:
    """Owner A: the fixture messages, an AutoPay pair and a payment to a friend. Owner B: one
    message of its own."""
    rows = full_rows() + PAIR + [FRIEND_PAID]
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", rows)))
    monkeypatch.setattr(settings, "owner_id", OWNER_B)
    run("import-sms", "--input", str(write_backup(tmp_path / "b.xml", [LATER])))
    monkeypatch.setattr(settings, "owner_id", OWNER_A)


def get(client, path: str, sub: str = SUB_A, **params):
    return client.get(path, headers=bearer(token(sub)), params=params)


def put(client, path: str, body: dict, sub: str = SUB_A):
    return client.put(path, headers=bearer(token(sub)), json=body)


def all_transactions(client, sub: str = SUB_A, **params) -> list[dict]:
    items, cursor = [], None
    while True:
        page = get(
            client,
            "/api/v1/transactions",
            sub,
            limit=7,
            **params,
            **({"cursor": cursor} if cursor else {}),
        )
        assert page.status_code == 200, page.text
        items += page.json()["items"]
        if not (cursor := page.json()["next_cursor"]):
            return items


def find(client, display_name: str) -> list[dict]:
    return [t for t in all_transactions(client) if t["display_name"] == display_name]
