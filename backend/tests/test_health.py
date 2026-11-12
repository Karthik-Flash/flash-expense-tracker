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
