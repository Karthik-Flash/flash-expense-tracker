"""Shared test setup. Tests never touch a real database.

DATABASE_URL is forced to a throwaway SQLite file before app.config loads, so
backend/.env can never point a test at Supabase. TEST_DATABASE_URL is set only
by the CI Postgres job (a disposable service container).
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.gettempdir(), 'flash-never.db').as_posix()}"

import pytest  # noqa: E402
from sqlalchemy import Engine, create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.models  # noqa: E402,F401  (registers tables)
from app import cli  # noqa: E402
from app.db import Base  # noqa: E402
from tests.apiclient import client, data, jwks  # noqa: E402,F401  (API fixtures)
from tests.smsdata import full_rows, write_backup  # noqa: E402

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def db_engine(tmp_path: Path) -> Iterator[Engine]:
    """Empty schema on SQLite (default) or the CI Postgres container."""
    if TEST_DATABASE_URL:
        engine = create_engine(TEST_DATABASE_URL)
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def run(db_engine: Engine, capsys: pytest.CaptureFixture):
    """Run a CLI command against the test database; returns stdout plus stderr."""
    factory = sessionmaker(db_engine, expire_on_commit=False)

    def run(*argv: str, code: int = 0) -> str:
        assert cli.main(list(argv), session_factory=factory) == code
        captured = capsys.readouterr()
        return captured.out + captured.err

    return run


@pytest.fixture
def backup(tmp_path: Path) -> Path:
    """A synthetic SMS backup built from the fake parser fixtures."""
    return write_backup(tmp_path / "backup.xml", full_rows(), mms=2)
