"""Migrations up and down, empty and with data: tables, RLS, keepalive.ping() (Postgres)."""

import os
from pathlib import Path

import pytest
import sqlalchemy.exc
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app import cli
from app.config import settings
from app.db import Base
from app.importers.sms_backup import import_sms
from app.models import RawMessage, Transaction, TransactionSource

PIPELINE_TABLES = {
    "import_batches",
    "raw_messages",
    "parse_results",
    "transactions",
    "transaction_sources",
    "duplicate_candidates",
}
OWNER_TABLES = {
    "own_accounts",
    "own_identifiers",
    "parties",
    "party_texts",
    "owner_link_decisions",
    "owner_roles",
}
DERIVED_TABLES = {"derive_runs", "txn_derived", "txn_links"}
CATEGORY_TABLES = {"owner_categories", "labels", "txn_labels"}  # owner tables of 0006
CLIENT_TABLES = {"client_ops"}  # 0007: answers to Idempotency-Key writes
CHECK_TABLES = {"txn_checks"}  # 0009: the owner's "Looks right" (D-101)
MARK_TABLES = {"recompute_marks"}  # 0010: writes before recompute (D-106)
NAME_TABLES = {"owner_names"}  # 0013: "Your name as banks show it" (D-117)
DEVICE_TABLES = {"devices"}  # 0014: phones that upload bank SMS (D-122)
USER_TABLES = {"app_users", "invites", "auth_deletions"}  # 0015: several users (D-128, D-129)
SETTING_TABLES = {"owner_settings"}  # 0016: "Count investments in Spent" (D-136)
VERSION_TABLES = {"data_versions"}  # 0017: the snapshot's data version (D-140)
NEW_TABLES = (
    PIPELINE_TABLES
    | OWNER_TABLES
    | DERIVED_TABLES
    | CATEGORY_TABLES
    | CLIENT_TABLES
    | CHECK_TABLES
    | MARK_TABLES
    | NAME_TABLES
    | DEVICE_TABLES
    | USER_TABLES
    | SETTING_TABLES
    | VERSION_TABLES
)  # every app table but heartbeat
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
NEWER_COLUMNS = {"origin"}  # Phase 2 tables' columns added later (0017: raw_messages.origin)
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

    command.downgrade(cfg, "0016")  # one step at a time: each downgrade works alone
    assert not VERSION_TABLES & tables(url) and tables(url) >= SETTING_TABLES
    assert "origin" not in {
        c["name"] for c in inspect(create_engine(url)).get_columns("raw_messages")
    }
    command.upgrade(cfg, "head")
    assert tables(url) >= VERSION_TABLES
    command.downgrade(cfg, "0015")
    assert not SETTING_TABLES & tables(url) and tables(url) >= USER_TABLES
    command.upgrade(cfg, "head")
    assert tables(url) >= SETTING_TABLES
    command.downgrade(cfg, "0014")
    assert not USER_TABLES & tables(url) and tables(url) >= DEVICE_TABLES
    command.upgrade(cfg, "head")
    assert tables(url) >= USER_TABLES
    command.downgrade(cfg, "0013")
    assert not DEVICE_TABLES & tables(url) and tables(url) >= NAME_TABLES
    command.upgrade(cfg, "head")
    assert tables(url) >= DEVICE_TABLES
    command.downgrade(cfg, "0009")
    assert not MARK_TABLES & tables(url) and tables(url) >= CHECK_TABLES
    command.upgrade(cfg, "head")
    assert tables(url) >= MARK_TABLES
    command.downgrade(cfg, "0008")
    assert not CHECK_TABLES & tables(url) and tables(url) >= CLIENT_TABLES
    command.upgrade(cfg, "head")
    assert tables(url) >= CHECK_TABLES
    command.downgrade(cfg, "0006")
    assert not CLIENT_TABLES & tables(url) and tables(url) >= CATEGORY_TABLES
    command.upgrade(cfg, "head")
    assert tables(url) >= CLIENT_TABLES
    command.downgrade(cfg, "0005")
    assert not (CATEGORY_TABLES | CLIENT_TABLES) & tables(url) and tables(url) >= DERIVED_TABLES
    command.downgrade(cfg, "0004")
    assert not DERIVED_TABLES & tables(url) and tables(url) >= OWNER_TABLES | PIPELINE_TABLES
    command.downgrade(cfg, "0003")
    assert not (OWNER_TABLES | DERIVED_TABLES) & tables(url) and tables(url) >= PIPELINE_TABLES
    command.downgrade(cfg, "0001")
    assert not NEW_TABLES & tables(url) and "heartbeat" in tables(url)
    command.upgrade(cfg, "head")
    assert tables(url) >= NEW_TABLES


def test_up_and_down_on_a_database_holding_data(url: str, backup: Path) -> None:
    """Every migration since 0003 is additive: Phase 2 data is untouched by downgrade and
    upgrade. (Imported at head: the importer writes 5B-2's raw_messages.origin, D-139.)"""
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        import_sms(s, backup, settings.owner_id)
    with engine.begin() as conn:  # an import ends with a recompute: back to Phase 2 data only
        for table in ("txn_links", "txn_derived", "derive_runs", "data_versions"):
            conn.execute(text(f"DELETE FROM {table}"))
    command.downgrade(cfg, "0003")

    def old_data() -> list:
        """The Phase 2 columns (0002) of the Phase 2 tables."""
        with factory() as s:
            return [
                sorted(
                    tuple(r)
                    for r in s.execute(
                        select(*(col for col in model.__table__.c if col.name not in NEWER_COLUMNS))
                    )
                )  # fmt: skip
                for model in (RawMessage, Transaction, TransactionSource)
            ]

    def rows(table: str) -> int:
        with engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(text(table))).scalar_one()

    before = old_data()
    assert all(before)
    command.upgrade(cfg, "head")
    assert old_data() == before and not any(rows(t) for t in OWNER_TABLES | DERIVED_TABLES)
    example = BACKEND.parent / "docs" / "owner.example.json"
    assert cli.main(["owner-load", str(example)], factory) == 0  # ends with a recompute
    assert rows("parties") == 3 and rows("txn_derived") == len(before[1])
    assert rows("derive_runs") == 1 and old_data() == before

    command.downgrade(cfg, "0005")  # category columns and tables go; the rows stay
    assert rows("txn_derived") == len(before[1]) and rows("parties") == 3
    assert not CATEGORY_TABLES & tables(url) and old_data() == before
    command.downgrade(cfg, "0004")  # derived data goes; owner data and Phase 2 data stay
    assert not DERIVED_TABLES & tables(url) and rows("parties") == 3 and old_data() == before
    command.downgrade(cfg, "0003")
    assert not (OWNER_TABLES | DERIVED_TABLES) & tables(url) and old_data() == before
    command.upgrade(cfg, "head")
    assert old_data() == before and not any(rows(t) for t in OWNER_TABLES | DERIVED_TABLES)
    assert cli.main(["recompute"], factory) == 0  # derived data is rebuilt from nothing
    assert rows("txn_derived") == len(before[1])
    command.check(cfg)
    engine.dispose()


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


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="Postgres only")
def test_no_policy_opens_a_table_and_keepalive_holds_only_ping(url: str) -> None:
    command.upgrade(alembic_config(), "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        policies = conn.execute(text("SELECT count(*) FROM pg_policies")).scalar_one()
        in_keepalive = conn.execute(
            text("SELECT count(*) FROM pg_tables WHERE schemaname = 'keepalive'")
        ).scalar_one()
    engine.dispose()
    assert policies == 0 and in_keepalive == 0
    for table in sorted(OWNER_TABLES | DERIVED_TABLES):
        assert blocked(url, f"SELECT * FROM public.{table}"), table


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


def test_0008_stops_on_a_long_label_then_keeps_one_active_row_per_text(url: str) -> None:
    """D-097: a label over 30 characters stops 0008 before it changes anything. D-096: a
    text has one active row; ended rows are history (dropped only by a downgrade)."""
    cfg = alembic_config()
    command.upgrade(cfg, "0007")
    engine = create_engine(url)
    owner = "0000000000000000000000000000000a"
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO labels (owner_id, name, source) VALUES (:o, :n, 'app')"),
            {"o": owner, "n": "T" * 31},
        )
    with pytest.raises(RuntimeError, match=r"1 label\(s\) are longer than 30"):
        command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0007"
    with engine.begin() as conn:
        conn.execute(text("UPDATE labels SET name = :n"), {"n": "T" * 30})
    command.upgrade(cfg, "head")

    insert = text(
        "INSERT INTO party_texts (owner_id, party_id, text, source, ended_at)"
        " VALUES (:o, 1, 'TEST FRIEND', 'app', :e)"
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO parties (id, owner_id, label, kind, source)"
                " VALUES (1, :o, 'T', 'unsure', 'app')"
            ),
            {"o": owner},
        )
        conn.execute(insert, {"o": owner, "e": "2026-11-20T00:00:00+00:00"})  # an ended join
        conn.execute(insert, {"o": owner, "e": None})  # the same text, active again
    with pytest.raises(sqlalchemy.exc.IntegrityError), engine.begin() as conn:
        conn.execute(insert, {"o": owner, "e": None})  # a second active row: refused
    command.downgrade(cfg, "0007")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM party_texts")).scalar() == 1
        assert conn.execute(text("SELECT kind FROM parties")).scalar() == "business"
        assert conn.execute(text("SELECT name FROM labels")).scalar() == "T" * 30
    command.upgrade(cfg, "head")
    command.check(cfg)
    engine.dispose()


def test_0009_checks_table_and_read_trigger(url: str) -> None:
    """D-101: txn_checks holds the owner's "Looks right". D-102: a recompute a read ran is
    recorded with trigger "read"; going back to 0008 records it as "owner"."""
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    owner = "0000000000000000000000000000000a"
    run = text(
        "INSERT INTO derive_runs (owner_id, started_at, status, trigger, versions, counts)"
        " VALUES (:o, '2026-11-20T00:00:00+00:00', 'done', :t, '{}', '{}')"
    )
    with engine.begin() as conn:
        conn.execute(run, {"o": owner, "t": "read"})
    with pytest.raises(sqlalchemy.exc.IntegrityError), engine.begin() as conn:
        conn.execute(run, {"o": owner, "t": "later"})
    with pytest.raises(sqlalchemy.exc.IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO txn_checks (transaction_id, owner_id, checked_at, source)"
                " VALUES (1, :o, '2026-11-20T00:00:00+00:00', 'robot')"
            ),
            {"o": owner},
        )
    command.downgrade(cfg, "0008")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT trigger FROM derive_runs")).scalar() == "owner"
    assert "txn_checks" not in tables(url)
    command.upgrade(cfg, "head")
    command.check(cfg)
    engine.dispose()
