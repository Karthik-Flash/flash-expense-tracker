"""D-102: after a deploy of new engine versions, the first read recomputes, once. FAKE data."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api import ops
from app.models import DeriveRun, TxnDerived
from app.pipeline.recompute import VERSIONS
from tests.apiclient import OWNER_A, get


def runs(db_engine) -> list[tuple[str, dict]]:
    with sessionmaker(db_engine)() as s:
        rows = s.execute(
            select(DeriveRun.trigger, DeriveRun.versions)
            .where(DeriveRun.owner_id == OWNER_A)
            .order_by(DeriveRun.id)
        )
        return [(t, dict(v)) for t, v in rows]


def age_last_run(db_engine) -> None:
    """As after a deploy: the stored rows were made by an older reconcile."""
    with sessionmaker(db_engine)() as s:
        last = s.scalar(
            select(DeriveRun).where(DeriveRun.owner_id == OWNER_A).order_by(DeriveRun.id.desc())
        )
        last.versions = VERSIONS | {"reconcile": "reconcile-0.0.1"}
        s.commit()


@pytest.fixture(autouse=True)
def _forget_failures():
    ops._refresh_failed.clear()
    yield
    ops._refresh_failed.clear()


def test_the_first_read_recomputes_once_and_serves_fresh_totals(client, data, db_engine) -> None:
    age_last_run(db_engine)
    before = len(runs(db_engine))
    first = get(client, "/api/v1/summary", month="2026-01")
    assert first.status_code == 200 and first.json()["stale"] is False
    after = runs(db_engine)
    assert len(after) == before + 1 and after[-1] == ("read", VERSIONS)
    for path in ("/api/v1/sync/snapshot", "/api/v1/transactions", "/api/v1/senders"):
        assert get(client, path).status_code == 200
    assert len(runs(db_engine)) == before + 1  # the second read finds nothing to do


def test_a_failed_refresh_keeps_the_stored_rows_with_the_notice(
    client, data, db_engine, monkeypatch, caplog
) -> None:
    age_last_run(db_engine)
    with sessionmaker(db_engine)() as s:
        stored = sorted(tuple(r) for r in s.execute(select(TxnDerived.__table__)))
    calls = []

    def broken(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("TEST: the database went away")

    monkeypatch.setattr(ops, "recompute", broken)
    first = get(client, "/api/v1/summary", month="2026-01")
    assert first.status_code == 200 and first.json()["stale"] is True  # "being updated"
    assert "version refresh on read failed (RuntimeError)" in caplog.text
    assert "went away" not in caplog.text  # the message could hold data: never logged
    assert get(client, "/api/v1/sync/snapshot").status_code == 200
    assert len(calls) == 1  # not tried again on every read
    with sessionmaker(db_engine)() as s:
        assert sorted(tuple(r) for r in s.execute(select(TxnDerived.__table__))) == stored
    assert runs(db_engine)[-1][1]["reconcile"] == "reconcile-0.0.1"


def test_no_run_yet_or_same_versions_reads_without_a_recompute(client, data, db_engine) -> None:
    before = runs(db_engine)
    assert before and before[-1][1] == VERSIONS
    assert get(client, "/api/v1/summary", month="2026-01").status_code == 200
    assert runs(db_engine) == before
