"""Isolation over every route (5C, D-130). FAKE data for two users: A (the admin) and B (a
member). B calls EVERY route of the app, from its own route table, with A's ids in the path
and in the body; nothing of A may come back, and nothing of A may change. A route missing
from CASES fails the test, so a new route cannot be left out.
"""

import json
import re
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.main import app
from app.models import AppUser, Transaction
from tests.apiclient import OWNER_B, SUB_A, SUB_B, bearer, token

A_LABEL = "ALPHA ONLY LABEL"

# (method, path template) -> (body, B may succeed): a body that would work on B's own items;
# "own" routes act on B's data and may answer 2xx, every other one must refuse B.
CASES: dict[tuple[str, str], tuple[object, bool]] = {
    ("GET", "/health"): (None, True),
    ("HEAD", "/health"): (None, True),
    ("GET", "/health/db"): (None, False),
    ("GET", "/api/v1/summary"): (None, True),
    ("GET", "/api/v1/transactions"): (None, True),
    ("GET", "/api/v1/transactions/{txn_id}"): (None, False),
    ("GET", "/api/v1/categories"): (None, True),
    ("GET", "/api/v1/labels"): (None, True),
    ("POST", "/api/v1/labels"): ({"name": "B Own Label"}, True),
    ("GET", "/api/v1/labels/{label_id}"): (None, False),
    ("GET", "/api/v1/senders"): (None, True),
    ("PUT", "/api/v1/senders/{sender_id}"): ({"answer": "friend"}, False),
    ("DELETE", "/api/v1/senders/{sender_id}"): (None, False),
    ("PUT", "/api/v1/transactions/{txn_id}/category"): (
        {"category": "travel", "scope": "transaction"},
        False,
    ),  # noqa: E501
    ("PUT", "/api/v1/transactions/{txn_id}/check"): (None, False),
    ("PUT", "/api/v1/transfers/{txn_a}/{txn_b}"): ({"verdict": "same"}, False),
    ("PUT", "/api/v1/transactions/{txn_id}/ignore"): (None, False),
    ("DELETE", "/api/v1/transactions/{txn_id}/ignore"): (None, False),
    ("PUT", "/api/v1/transactions/{txn_id}/label"): ({"label_id": "A_LABEL_ID"}, False),
    ("DELETE", "/api/v1/transactions/{txn_id}/label"): (None, False),
    ("PUT", "/api/v1/profile/names"): ({"names": ["B Test Name"]}, True),
    ("PUT", "/api/v1/profile/settings"): ({"count_investments_in_spent": True}, True),  # 5B-1
    ("PUT", "/api/v1/people/{txn_id}/kind"): ({"kind": "self"}, False),
    ("DELETE", "/api/v1/people/{txn_id}/kind"): (None, False),
    ("PUT", "/api/v1/people/{txn_id}/suggestion"): ({"kind": "self"}, False),
    ("PUT", "/api/v1/people/{txn_id}/name"): ({"name": "B Renames"}, False),
    ("DELETE", "/api/v1/people/{txn_id}/name"): (None, False),
    ("PUT", "/api/v1/people/{txn_id}/join"): ({"into": "A_TXN_2"}, False),
    ("DELETE", "/api/v1/people/{txn_id}/join"): (None, False),
    ("GET", "/api/v1/sync/snapshot"): (None, True),
    ("POST", "/api/v1/devices"): ({"device_id": str(uuid.uuid4()), "name": "B PHONE"}, True),
    ("GET", "/api/v1/devices"): (None, True),
    ("DELETE", "/api/v1/devices/{device_id}"): (None, False),
    ("POST", "/api/v1/ingest/sms"): ({"messages": []}, False),  # a login token: never
    ("POST", "/api/v1/signup"): (
        {"email": "b@example.invalid", "password": "test-pass-1", "code": "AAAA-AAAA-AAAA"},
        False,
    ),  # noqa: E501
    ("POST", "/api/v1/invites"): (None, False),  # the admin only
    ("GET", "/api/v1/invites"): (None, False),
    ("DELETE", "/api/v1/invites/{invite_id}"): (None, False),
    ("GET", "/api/v1/members"): (None, False),
    ("POST", "/api/v1/account/delete"): ({"confirm": "DELETE"}, False),  # not a fresh sign-in
    ("GET", "/api/v1/export"): (None, True),  # 5F: B's own rows only (markers checked)
    ("GET", "/api/v1/analytics"): (None, True),  # premium B: B's own months only
    ("PUT", "/api/v1/transactions/{txn_id}/payback"): ({"answer": "paid_back"}, False),  # C
    ("DELETE", "/api/v1/transactions/{txn_id}/payback"): (None, False),
    ("DELETE", "/api/v1/rules/{party_id}"): (None, False),
}


# Public routes that hold no one's data: their status depends on the server's settings (the
# ping token), not on the caller; they are still checked to reveal nothing of A.
UNSCOPED = {("GET", "/health"), ("HEAD", "/health"), ("GET", "/health/db")}


def routes() -> set[tuple[str, str]]:
    return {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}


def key() -> dict:
    return {"Idempotency-Key": str(uuid.uuid4())}


def a_view(client) -> str:
    """Everything A owns, as A sees it (the member list moves with B's requests: left out)."""
    snap = client.get("/api/v1/sync/snapshot", headers=bearer(token(SUB_A))).json()
    snap.pop("generated_at")
    snap.pop("admin")
    devices = client.get("/api/v1/devices", headers=bearer(token(SUB_A))).json()
    invites = client.get("/api/v1/invites", headers=bearer(token(SUB_A))).json()
    return json.dumps([snap, devices, invites], sort_keys=True)


@pytest.fixture
def two_users(client, data, db_engine, monkeypatch) -> dict:
    """A: the admin (AUTH_USERS), the fixture messages, a label, a phone, an invite, an
    answer sent with a key. B: a member with one message of its own."""
    monkeypatch.setattr(settings, "auth_users", f"{SUB_A}:{settings.owner_id}")
    with sessionmaker(db_engine)() as s:
        s.add(AppUser(auth_uid=SUB_B, owner_id=OWNER_B, role="member"))
        s.commit()
    a = bearer(token(SUB_A))
    label = client.post("/api/v1/labels", headers=a | key(), json={"name": A_LABEL}).json()["id"]
    device = str(uuid.uuid4())
    client.post("/api/v1/devices", headers=a, json={"device_id": device, "name": "ALPHA PHONE"})
    invite = client.post("/api/v1/invites", headers=a).json()["invite"]["id"]
    first = client.get("/api/v1/sync/snapshot", headers=a).json()["transactions"]
    named = next(t for t in first if t["direction"] == "debit" and t["display_name"])
    rule = {"category": "groceries", "scope": "merchant"}  # D-149: A has a rule
    path = f"/api/v1/transactions/{named['id']}/category"
    assert client.put(path, headers=a | key(), json=rule).status_code == 200
    snap = client.get("/api/v1/sync/snapshot", headers=a).json()
    sender = snap["todo"]["senders"][0]["id"]
    answer_key = key()
    put = client.put(f"/api/v1/senders/{sender}", headers=a | answer_key, json={"answer": "ignore"})
    assert put.status_code == 200
    txns = [t["id"] for t in snap["transactions"]]
    senders = [s["id"] for s in snap["todo"]["senders"] + snap["todo"]["answered"]]
    return {
        "txn_id": txns[0], "txn_a": txns[0], "txn_b": txns[1], "A_TXN_2": txns[1],
        "sender_id": sender, "label_id": label, "A_LABEL_ID": label, "device_id": device,
        "invite_id": invite, "party_id": snap["profile"]["rules"][0]["party_id"],
        "answer_key": answer_key, "answer_path": f"/api/v1/senders/{sender}",
        "markers": [A_LABEL, device, "ALPHA PHONE", *senders],
    }  # fmt: skip


def fill(template: str, ids: dict) -> str:
    return re.sub(r"\{([^}]+)\}", lambda m: str(ids[m.group(1)]), template)


def body_for(body, ids: dict):
    if isinstance(body, dict):
        return {k: ids.get(v, v) if isinstance(v, str) else v for k, v in body.items()}
    return body


def test_b_reaches_nothing_of_a_on_any_route(client, db_engine, two_users) -> None:
    ids = two_users
    found = routes()
    assert found == set(CASES), f"routes without a case: {sorted(found - set(CASES))}"
    assert len(found) == 45
    before = a_view(client)
    b = bearer(token(SUB_B))
    for (method, template), (body, own) in sorted(CASES.items()):
        path = fill(template, ids)
        params = {"month": "2026-01"} if template.endswith("/summary") else None
        if template.endswith("/export"):
            params = {"start": "2025-01-01", "end": "2027-12-31", "format": "csv"}  # plain text
        if template.endswith("/analytics"):
            params = {"start": "2025-12", "end": "2026-11"}
        answer = client.request(
            method, path, headers=b | key(), json=body_for(body, ids), params=params
        )  # noqa: E501
        where = (method, template, answer.status_code)
        if (method, template) not in UNSCOPED:
            assert answer.status_code < 500, where
        if not own and (method, template) not in UNSCOPED:
            assert answer.status_code >= 400, where  # refused: 401, 403, 404, 409, 422
        for marker in ids["markers"]:
            assert marker not in answer.text, (*where, "leaks A")
    assert a_view(client) == before  # nothing of A changed

    # B's reads hold B's rows only: no count, month or total of A.
    with sessionmaker(db_engine)() as s:
        mine = set(s.scalars(select(Transaction.id).where(Transaction.owner_id == OWNER_B)))
    snap = client.get("/api/v1/sync/snapshot", headers=b).json()
    assert {t["id"] for t in snap["transactions"]} <= mine
    assert snap["owner_id"] == str(OWNER_B) and "admin" not in snap
    assert snap["account"]["role"] == "member"
    total = sum(len(m["summary"]["categories"]) for m in snap["months"])
    assert total <= len(mine) + 1


def test_an_idempotency_key_of_a_never_replays_for_b(client, two_users) -> None:
    """client_ops is keyed by owner: A's stored answer is never B's."""
    b = bearer(token(SUB_B)) | two_users["answer_key"]
    again = client.put(two_users["answer_path"], headers=b, json={"answer": "ignore"})
    assert again.status_code == 404
