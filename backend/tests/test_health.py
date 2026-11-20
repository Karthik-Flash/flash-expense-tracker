from fastapi.testclient import TestClient

from app import __version__
from app.config import settings
from app.main import app


def test_health_ok_with_cors() -> None:
    origin = settings.cors_origin_list[0]
    res = TestClient(app).get("/health", headers={"Origin": origin})

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "version": __version__}
    assert res.headers["access-control-allow-origin"] == origin


def test_health_head_is_200_with_no_body_and_no_database(monkeypatch) -> None:
    """D-098: the warm job may send HEAD; nothing is read or written."""
    from app.db import get_session

    def no_db():
        raise AssertionError("HEAD /health must not open a session")

    app.dependency_overrides[get_session] = no_db
    try:
        res = TestClient(app).head("/health")
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 200 and res.content == b""
