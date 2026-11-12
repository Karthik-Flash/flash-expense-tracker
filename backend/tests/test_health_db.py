"""/health/db tests. They use throwaway SQLite databases, never a real Postgres."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_session
from app.main import app
from app.models import Heartbeat

TOKEN = "test-token"
GOOD = {"X-Ping-Token": TOKEN}


def use_engine(engine: Engine) -> None:
    factory = sessionmaker(engine)

    def override() -> Iterator:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(settings, "ping_token", TOKEN)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def engine() -> Engine:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    use_engine(engine)
    return engine


def test_correct_token_upserts_one_row_with_db_time(client: TestClient, engine: Engine) -> None:
    for _ in range(2):
        res = client.get("/health/db", headers=GOOD)
        assert res.status_code == 200
        body = res.json()
        assert body["db"] == "ok" and isinstance(body["latency_ms"], int)

    with sessionmaker(engine)() as session:
        rows = session.scalars(select(Heartbeat)).all()
    assert [row.id for row in rows] == [1]
    assert rows[0].last_seen is not None


def test_missing_header_is_401(client: TestClient, engine: Engine) -> None:
    assert client.get("/health/db").status_code == 401


def test_wrong_token_is_401(client: TestClient, engine: Engine) -> None:
    assert client.get("/health/db", headers={"X-Ping-Token": "wrong"}).status_code == 401


def test_query_string_token_is_not_accepted(client: TestClient, engine: Engine) -> None:
    assert client.get("/health/db", params={"token": TOKEN}).status_code == 401


def test_unset_ping_token_is_503(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ping_token", "")
    res = client.get("/health/db", headers={"X-Ping-Token": ""})
    assert res.status_code == 503
    assert res.json() == {"detail": "ping token not configured"}


def test_db_down_is_503_and_health_stays_up(client: TestClient, tmp_path: Path) -> None:
    use_engine(create_engine(f"sqlite:///{(tmp_path / 'missing' / 'x.db').as_posix()}"))

    res = client.get("/health/db", headers=GOOD)
    assert res.status_code == 503
    assert res.json() == {"detail": "database unavailable"}
    assert client.get("/health").status_code == 200  # /health never touches the DB
