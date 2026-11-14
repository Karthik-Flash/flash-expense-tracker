"""Migration 0002 on an empty database: tables, RLS (Postgres), model parity."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings
from app.db import Base

NEW_TABLES = {
    "import_batches",
    "raw_messages",
    "parse_results",
    "transactions",
    "transaction_sources",
    "duplicate_candidates",
}
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture
def url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = TEST_DATABASE_URL or f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()
    monkeypatch.setattr(settings, "database_url", url)  # alembic/env.py reads this
    return url


def alembic_config() -> Config:
    cfg = Config()  # no ini file: keeps the test's logging setup
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_check_downgrade_upgrade(url: str) -> None:
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    assert NEW_TABLES | {"heartbeat"} <= tables(url)
    command.check(cfg)  # models and migrations agree

    command.downgrade(cfg, "0001")
    assert not NEW_TABLES & tables(url) and "heartbeat" in tables(url)
    command.upgrade(cfg, "head")
    assert tables(url) >= NEW_TABLES


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="Postgres only")
def test_row_level_security_enabled_on_new_tables(url: str) -> None:
    command.upgrade(alembic_config(), "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT relname, relrowsecurity FROM pg_class WHERE relname = ANY(:t)"),
            {"t": list(NEW_TABLES)},
        ).all()
    engine.dispose()
    assert dict(rows) == dict.fromkeys(NEW_TABLES, True)
