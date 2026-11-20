"""D-106: a tap is never blocked by the engine. A write commits the owner data, its stored
answer and a recompute mark, and answers at once; the next read recomputes. FAKE data."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api import ops
from app.models import ClientOp, OwnerCategory, RecomputeMark
from tests.apiclient import OWNER_A, all_transactions, bearer, get, token


def send(client, method: str, path: str, body=None, key=None):
    headers = bearer(token())
    if key:
        headers["Idempotency-Key"] = str(key)
    return client.request(method, path, headers=headers, json=body)


def test_a_write_is_saved_even_when_the_recompute_fails(client, data, db_engine, monkeypatch):
    t = next(t for t in all_transactions(client) if t["role"] == "spend")
    month = t["time_utc"][:7]
    before = get(client, "/api/v1/summary", month=month).json()

    def broken(*args, **kwargs):
        raise RuntimeError("TEST: the engine broke")

    real = ops.recompute
    monkeypatch.setattr(ops, "recompute", broken)
    key = uuid.uuid4()
    answer = send(client, "PUT", f"/api/v1/transactions/{t['id']}/ignore", None, key)
    assert answer.status_code == 200
    assert answer.json()["recompute"] == {"status": "deferred", "run": None}
    with sessionmaker(db_engine)() as s:
        assert s.scalar(select(func.count()).select_from(ClientOp)) == 1  # stored with its key
        mark = s.get(RecomputeMark, OWNER_A)
        assert mark is not None and mark.failed_at is None
    stale = get(client, "/api/v1/summary", month=month).json()
    assert stale["stale"] is True and stale["net_paise"] == before["net_paise"]  # old rows
    with sessionmaker(db_engine)() as s:
        assert s.get(RecomputeMark, OWNER_A).failure == "RuntimeError"

    monkeypatch.setattr(ops, "recompute", real)  # undo() would also undo the login
    with sessionmaker(db_engine)() as s:  # as if 5 minutes had passed
        s.get(RecomputeMark, OWNER_A).failed_at = None
        s.commit()
    after = get(client, "/api/v1/summary", month=month).json()
    assert after["stale"] is False
    assert after["net_paise"] == before["net_paise"] - t["amount_paise"]  # the write counts now
    with sessionmaker(db_engine)() as s:
        assert s.get(RecomputeMark, OWNER_A) is None


def test_writes_answer_without_a_recompute_and_reads_catch_up(client, data, db_engine):
    t = next(t for t in all_transactions(client) if t["role"] == "spend")
    calls = []
    real = ops.recompute

    def counting(*args, **kwargs):
        calls.append(args[2])
        return real(*args, **kwargs)

    ops.recompute = counting
    try:
        path = f"/api/v1/transactions/{t['id']}/category"
        for slug in ("travel", "health"):
            body = {"category": slug, "scope": "transaction"}
            assert send(client, "PUT", path, body, uuid.uuid4()).status_code == 200
        assert calls == ["owner"]  # only the second write caught up with the first
        item = get(client, f"/api/v1/transactions/{t['id']}").json()
        assert calls == ["owner", "owner"] and item["category"] == "health"
        get(client, "/api/v1/sync/snapshot")
        assert len(calls) == 2  # nothing left to do
    finally:
        ops.recompute = real
    with sessionmaker(db_engine)() as s:
        assert s.get(OwnerCategory, t["id"]).category == "health"
