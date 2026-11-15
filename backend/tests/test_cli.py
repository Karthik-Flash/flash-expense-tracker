"""CLI commands and I9: output holds counts only. Synthetic data only."""

import re
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app import cli
from app.engine.merchant import MERCHANT_VERSION
from app.engine.parsers.hdfc import PARSER_VERSION
from app.importers import sms_backup
from tests.smsdata import FIXTURES, NEVER_STORED, SBI_ROW, full_rows, write_backup


@pytest.fixture
def run(db_engine: Engine, capsys: pytest.CaptureFixture):
    factory = sessionmaker(db_engine, expire_on_commit=False)

    def run(*argv: str) -> str:
        assert cli.main(list(argv), session_factory=factory) == 0
        captured = capsys.readouterr()
        return captured.out + captured.err

    return run


@pytest.fixture
def backup(tmp_path: Path) -> Path:
    return write_backup(tmp_path / "backup.xml", full_rows(), mms=2)


def secrets() -> set[str]:
    """Every value from the fake messages that must never be printed."""
    values = set()
    for fx in FIXTURES:
        exp = fx["expected"]
        values |= {exp.get("counterparty_raw"), exp.get("reference"), exp.get("account_last4")}
        values |= set(re.findall(r"(?:Rs\.?|INR) ?[\d,]+(?:\.\d+)?", fx["body"]))
        values |= {line for line in fx["body"].splitlines() if len(line) > 12}
    for _, body, _ in [*NEVER_STORED, SBI_ROW]:
        values.add(body)
    return {v for v in values if v}


def assert_no_values(out: str) -> None:
    leaked = sorted(v for v in secrets() if v in out)
    assert not leaked, leaked


def test_dry_run_then_import_then_stats_print_counts_only(run, backup: Path) -> None:
    dry = run("import-sms", "--input", str(backup), "--dry-run")
    assert "dry run: nothing saved" in dry
    assert re.search(r"read\s+56\b", dry) and re.search(r"otp\s+1\b", dry)
    assert "tables" in run("stats") and re.search(r"raw_messages\s+0\b", run("stats"))

    out = run("import-sms", "--input", str(backup))
    assert "import-sms batch" in out and f"HDFC {PARSER_VERSION}" in out
    again = run("import-sms", "--input", str(backup))
    assert re.search(r"duplicate\s+50\b", again)

    stats = run("stats")
    assert re.search(r"raw_messages\s+50\b", stats)
    assert re.search(r"no_parser_for_bank\s+1\b", stats)
    assert re.search(r"months \(IST\)\s+2026-01 \.\. 2026-01", stats)
    assert re.search(r"#\d+ done .* raw new 0\s+duplicate 50", stats)  # ids: PG skips dry runs
    for out_text in (dry, out, again, stats, run("reparse", "--dry-run"), run("reparse")):
        assert_no_values(out_text)


def test_progress_line_every_5000_messages(run, tmp_path: Path) -> None:
    rows = [("+919000000001", f"hello {i}", SBI_ROW[2]) for i in range(10_000)]
    out = run("import-sms", "--input", str(write_backup(tmp_path / "big.xml", rows)))
    assert out.count("messages, ") == 2 and "10,000 messages" in out
    assert "hello" not in out


def test_failed_import_prints_no_values(run, backup: Path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(sms_backup, "ingest", boom)
    with pytest.raises(RuntimeError, match="simulated crash"):
        run("import-sms", "--input", str(backup))
    stats = run("stats")
    assert re.search(r"#\d+ failed", stats)
    assert_no_values(stats)


def test_missing_input_is_an_error(db_engine: Engine, tmp_path: Path, capsys) -> None:
    factory = sessionmaker(db_engine)
    assert cli.main(["import-sms", "--input", str(tmp_path / "nope.xml")], factory) == 2
    assert "input not found" in capsys.readouterr().err


def snapshot(db_engine: Engine) -> list:
    with db_engine.connect() as conn:
        return [list(conn.execute(select(model))) for model in cli.TABLES]


def test_merchant_stats_prints_counts_only_and_writes_nothing(run, backup: Path, db_engine) -> None:
    run("import-sms", "--input", str(backup))
    before = snapshot(db_engine)
    out = run("merchant-stats")
    assert snapshot(db_engine) == before
    assert f"merchant-stats ({MERCHANT_VERSION}, read-only)" in out
    assert re.search(r"transactions examined\s+\d+", out)
    assert "R4_card" in out and "dictionary hits" in out
    assert re.search(r"kind by direction\n(  .*\n)*  refund business\s+\d+", out)
    assert "distinct merchant keys by kind" in out
    assert re.search(r"  95%\s+\d+", out)
    assert_no_values(out)
    keys = {"brand:", "vpa:", "name:"}
    assert not any(k in out for k in keys)


def test_merchant_review_refuses_without_a_terminal(db_engine, backup: Path, capsys) -> None:
    factory = sessionmaker(db_engine)
    assert cli.main(["import-sms", "--input", str(backup)], factory) == 0
    capsys.readouterr()
    assert cli.main(["merchant-review"], factory) == 2
    out = capsys.readouterr()
    assert out.out == "" and "only to a terminal" in out.err


def test_merchant_review_filters_and_shows_no_amounts(run, backup, db_engine, monkeypatch) -> None:
    run("import-sms", "--input", str(backup))
    monkeypatch.setattr(cli, "is_terminal", lambda: True)
    before = snapshot(db_engine)

    def review(*flags: str) -> list[str]:
        lines = run("merchant-review", *flags).splitlines()
        assert lines[0] == lines[-1] == cli.PRIVATE
        assert lines[-2] == f"{len(lines) - 3} keys"
        return lines[1:-2]

    every = review()
    assert every and all(row.count(" | ") == 5 for row in every)
    assert all(" | business " in row for row in review("--kind", "business"))
    assert all(
        " | person low | " in row for row in review("--kind", "person", "--confidence", "low")
    )
    assert all("R4_card" in row for row in review("--reason", "R4_card"))
    refunds = review("--direction", "refund")
    assert refunds and len(refunds) < len(every)
    assert len(review("--sample", "2", "--seed", "1")) == 2
    assert review("--sample", "2", "--seed", "1") == review("--sample", "2", "--seed", "1")
    assert snapshot(db_engine) == before

    out = "\n".join(every)
    values = set()
    for fx in FIXTURES:
        values.add(fx["expected"].get("reference"))
        values |= set(re.findall(r"(?:Rs\.?|INR) ?[\d,]+(?:\.\d+)?", fx["body"]))
    assert not sorted(v for v in values if v and v in out)
