import pytest

from app.config import Settings, normalize_database_url

PG = "postgresql+psycopg://u:p@db.example.com:5432/postgres?sslmode=require"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgres://u:p@db.example.com:5432/postgres?sslmode=require", PG),
        ("postgresql://u:p@db.example.com:5432/postgres?sslmode=require", PG),
        (PG, PG),
        ("sqlite:///./flash.db", "sqlite:///./flash.db"),
    ],
)
def test_normalize_database_url(given: str, expected: str) -> None:
    assert normalize_database_url(given) == expected


def test_settings_apply_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    assert Settings(_env_file=None).database_url == "postgresql+psycopg://u:p@h/db"
