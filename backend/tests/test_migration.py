"""Migrations on an empty database: tables, RLS and keepalive.ping() (Postgres), parity."""

import os
from pathlib import Path

import pytest
import sqlalchemy.exc
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
    "own_accounts",
    "own_identifiers",
    "parties",
    "party_texts",
    "owner_link_decisions",
    "owner_roles",
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
        if engine.dialect.name == "postgresql":
            conn.execute(text("DROP SCHEMA IF EXISTS keepalive CASCADE"))
            # Supabase's Data API role; created here so 0003 grants to it.
            conn.execute(
                text(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')"
                    " THEN CREATE ROLE anon NOLOGIN; END IF; END $$"
                )
            )
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


def as_anon(url: str, sql: str) -> list:
    """Run one statement as the anon role (what the publishable key maps to)."""
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL ROLE anon"))
            return list(conn.execute(text(sql)).all())
    finally:
        engine.dispose()


def blocked(url: str, sql: str) -> bool:
    """True if anon gets permission denied or sees no rows."""
    try:
        return as_anon(url, sql) == []
    except sqlalchemy.exc.ProgrammingError as exc:
        return "permission denied" in str(exc)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="Postgres only")
def test_keepalive_ping_as_anon(url: str) -> None:
    command.upgrade(alembic_config(), "head")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO heartbeat (id, last_seen) VALUES (1, '2000-01-01T00:00:00Z')")
        )
        conn.execute(
            text(
                "INSERT INTO transactions (owner_id, dedupe_key, type, direction,"
                " amount_paise, currency, txn_time_utc, time_inferred, bank, hints, status)"
                " VALUES ('00000000-0000-0000-0000-000000000009', 'fake-key', 'debit',"
                " 'debit', 100, 'INR', now(), false, 'HDFC', '[]', 'active')"
            )
        )
    assert as_anon(url, "SELECT keepalive.ping()") == [({"ok": True},)]
    with engine.connect() as conn:
        moved = conn.execute(text("SELECT last_seen > now() - interval '1 minute' FROM heartbeat"))
        assert moved.scalar_one() is True

    tables_sql = ("SELECT * FROM public.heartbeat", "SELECT * FROM public.transactions")
    for sql in tables_sql:
        assert blocked(url, sql), sql
    # Supabase grants anon SELECT on public tables by default; RLS still hides every row.
    with engine.begin() as conn:
        conn.execute(text("GRANT SELECT ON public.heartbeat, public.transactions TO anon"))
    for sql in tables_sql:
        assert as_anon(url, sql) == [], sql
    engine.dispose()

    command.check(alembic_config())  # schema, function and RLS add no model drift
    command.downgrade(alembic_config(), "0002")
    engine = create_engine(url)
    with engine.connect() as conn:
        gone = conn.execute(text("SELECT to_regnamespace('keepalive') IS NULL"))
        assert gone.scalar_one() is True
    engine.dispose()
