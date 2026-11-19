"""Owner writes with an Idempotency-Key (D-091, D-092) and deferred recomputes (D-094).
FAKE data only."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api import ops
from app.main import app
from app.models import ClientOp, Label, OwnerCategory, TxnDerived
from app.pipeline import owner_actions
from tests.apiclient import OWNER_A, SUB_B, all_transactions, bearer, get, token


def send(client, method: str, path: str, body=None, key=None, sub="user-a", defer=False):
    headers = bearer(token(sub))
    if key:
        headers["Idempotency-Key"] = str(key)
    if defer:
        headers["X-Defer-Recompute"] = "1"
    return client.request(method, path, headers=headers, json=body)


def count(db_engine, model, *where) -> int:
    with sessionmaker(db_engine)() as s:
        return s.scalar(select(func.count()).select_from(model).where(*where))


def a_spend(client) -> dict:
    return next(t for t in all_transactions(client) if t["role"] == "spend")


def test_same_key_twice_writes_once_and_answers_the_same(client, data, db_engine) -> None:
    key = uuid.uuid4()
    first = send(client, "POST", "/api/v1/labels", {"name": "Test Trip"}, key)
    again = send(client, "POST", "/api/v1/labels", {"name": "Test Trip"}, key)
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json() and set(first.json()) == {"id", "name"}
    assert count(db_engine, Label) == 1 and count(db_engine, ClientOp) == 1

    t = a_spend(client)
    path, body = (
        f"/api/v1/transactions/{t['id']}/category",
        {"category": "travel", "scope": "transaction"},
    )
    key = uuid.uuid4()
    one, two = send(client, "PUT", path, body, key), send(client, "PUT", path, body, key)
    assert one.status_code == two.status_code == 200 and one.json() == two.json()
    assert one.json()["recompute"]["status"] == "done"
    assert count(db_engine, OwnerCategory) == 1


def test_different_keys_are_different_writes(client, data, db_engine) -> None:
    for name in ("Test One", "Test Two"):
        assert (
            send(client, "POST", "/api/v1/labels", {"name": name}, uuid.uuid4()).status_code == 201
        )
    assert count(db_engine, Label) == 2 and count(db_engine, ClientOp) == 2


def test_a_key_in_progress_answers_409_and_writes_nothing(client, data, db_engine) -> None:
    key = uuid.uuid4()
    ops._running.add((OWNER_A, key))
    try:
        busy = send(client, "POST", "/api/v1/labels", {"name": "Test Busy"}, key)
    finally:
        ops._running.discard((OWNER_A, key))
    assert busy.status_code == 409 and busy.json() == {"detail": "in_progress"}
    assert count(db_engine, Label) == 0 and count(db_engine, ClientOp) == 0
    assert send(client, "POST", "/api/v1/labels", {"name": "Test Busy"}, key).status_code == 201


def test_a_key_reused_for_another_request_is_422(client, data, db_engine) -> None:
    key = uuid.uuid4()
    assert send(client, "POST", "/api/v1/labels", {"name": "Test A"}, key).status_code == 201
    other_body = send(client, "POST", "/api/v1/labels", {"name": "Test B"}, key)
    t = a_spend(client)
    other_path = send(client, "DELETE", f"/api/v1/transactions/{t['id']}/label", None, key)
    for response in (other_body, other_path):
        assert response.status_code == 422 and response.json() == {
            "detail": "idempotency_key_reused"
        }
    assert count(db_engine, Label) == 1 and count(db_engine, ClientOp) == 1
    bad = send(client, "POST", "/api/v1/labels", {"name": "Test C"}, "not-a-uuid")
    assert bad.status_code == 422 and count(db_engine, Label) == 1


def test_a_4xx_is_final_and_stored(client, data, db_engine) -> None:
    key = uuid.uuid4()
    body = {"category": "travel", "scope": "transaction"}
    first = send(client, "PUT", "/api/v1/transactions/999999/category", body, key)
    again = send(client, "PUT", "/api/v1/transactions/999999/category", body, key)
    assert first.status_code == again.status_code == 404 and first.json() == again.json()
    with sessionmaker(db_engine)() as s:
        row = s.get(ClientOp, (OWNER_A, key))
        assert (row.status_code, row.response_body) == (404, {"detail": "no such transaction"})
        assert row.completed_at is not None
    send(client, "POST", "/api/v1/labels", {"name": "Test Dup"}, uuid.uuid4())
    clash = send(client, "POST", "/api/v1/labels", {"name": "test  dup"}, uuid.uuid4())
    assert clash.status_code == 409 and count(db_engine, Label) == 1


def test_a_5xx_is_not_stored_and_a_retry_runs_fresh(client, data, db_engine, monkeypatch) -> None:
    t = a_spend(client)
    path, body = (
        f"/api/v1/transactions/{t['id']}/category",
        {"category": "health", "scope": "transaction"},
    )
    key = uuid.uuid4()
    real = owner_actions.set_category

    def broken(*args, **kwargs):
        real(*args, **kwargs)  # the write happens, then the server fails
        raise RuntimeError("TEST failure")

    monkeypatch.setattr(owner_actions, "set_category", broken)
    failing = TestClient(app, raise_server_exceptions=False)
    assert send(failing, "PUT", path, body, key).status_code == 500
    assert count(db_engine, ClientOp) == 0 and count(db_engine, OwnerCategory) == 0
    monkeypatch.setattr(owner_actions, "set_category", real)
    retry = send(client, "PUT", path, body, key)
    assert retry.status_code == 200 and count(db_engine, OwnerCategory) == 1


def test_a_key_belongs_to_its_owner(client, data, db_engine) -> None:
    key = uuid.uuid4()
    a = send(client, "POST", "/api/v1/labels", {"name": "Test Mine"}, key)
    b = send(client, "POST", "/api/v1/labels", {"name": "Test Theirs"}, key, SUB_B)
    assert a.status_code == b.status_code == 201 and a.json()["name"] != b.json()["name"]
    assert count(db_engine, ClientOp) == 2


def test_no_key_writes_no_row_on_every_write_route(client, data, db_engine) -> None:
    t = a_spend(client)
    sender = get(client, "/api/v1/senders").json()[0]["id"]
    label = send(client, "POST", "/api/v1/labels", {"name": "Test Plain"}).json()
    calls = [
        ("PUT", f"/api/v1/senders/{sender}", {"answer": "friend"}),
        ("DELETE", f"/api/v1/senders/{sender}", None),
        (
            "PUT",
            f"/api/v1/transactions/{t['id']}/category",
            {"category": "travel", "scope": "transaction"},
        ),
        ("PUT", f"/api/v1/transactions/{t['id']}/label", {"label_id": label["id"]}),
        ("PUT", f"/api/v1/transactions/{t['id']}/label", {"new_label": "Test Made"}),
        ("DELETE", f"/api/v1/transactions/{t['id']}/label", None),
    ]
    for method, path, body in calls:
        response = send(client, method, path, body, defer=True)  # defer is ignored without a key
        assert response.status_code == 200, (path, response.text)
        assert response.json()["recompute"]["status"] in ("done", "unchanged")
    assert count(db_engine, ClientOp) == 0


def test_new_label_in_one_write(client, data, db_engine) -> None:
    t = a_spend(client)
    path = f"/api/v1/transactions/{t['id']}/label"
    made = send(client, "PUT", path, {"new_label": " Test  Goa "}, uuid.uuid4())
    assert made.status_code == 200
    item = next(x for x in all_transactions(client) if x["id"] == t["id"])
    assert item["label"]["name"] == "Test Goa"
    assert send(client, "PUT", path, {"new_label": "test goa"}, uuid.uuid4()).status_code == 409
    assert send(client, "PUT", path, {"label_id": 1, "new_label": "X"}).status_code == 422
    assert send(client, "PUT", path, {}).status_code == 422
    gone = send(client, "PUT", "/api/v1/transactions/999999/label", {"new_label": "Test Lost"})
    assert gone.status_code == 404 and count(db_engine, Label) == 1


def category_in_db(db_engine, txn_id: int) -> str:
    with sessionmaker(db_engine)() as s:
        return s.get(TxnDerived, txn_id).category


def test_a_deferred_write_is_recomputed_before_any_read(client, data, db_engine) -> None:
    t = a_spend(client)
    path = f"/api/v1/transactions/{t['id']}/category"
    body = {"category": "education", "scope": "transaction"}
    deferred = send(client, "PUT", path, body, uuid.uuid4(), defer=True)
    assert deferred.json()["recompute"] == {"status": "deferred", "run": None}
    assert category_in_db(db_engine, t["id"]) == t["category"]  # derived not written yet
    assert count(db_engine, ClientOp, ClientOp.recompute_pending) == 1

    item = get(client, f"/api/v1/transactions/{t['id']}").json()  # a read runs it first
    assert item["category"] == "education" and category_in_db(db_engine, t["id"]) == "education"
    assert count(db_engine, ClientOp, ClientOp.recompute_pending) == 0

    body = {"category": "health", "scope": "transaction"}
    send(client, "PUT", path, body, uuid.uuid4(), defer=True)
    snapshot = get(client, "/api/v1/sync/snapshot").json()
    mine = next(x for x in snapshot["transactions"] if x["id"] == t["id"])
    assert mine["category"] == "health"
    assert not any(m["summary"]["stale"] for m in snapshot["months"])


def test_a_recompute_through_a_write_clears_deferred_marks(client, data, db_engine) -> None:
    t = a_spend(client)
    path = f"/api/v1/transactions/{t['id']}/category"
    send(
        client,
        "PUT",
        path,
        {"category": "education", "scope": "transaction"},
        uuid.uuid4(),
        defer=True,
    )
    send(client, "PUT", path, {"category": "health", "scope": "transaction"}, uuid.uuid4())
    assert count(db_engine, ClientOp, ClientOp.recompute_pending) == 0
    assert category_in_db(db_engine, t["id"]) == "health"
