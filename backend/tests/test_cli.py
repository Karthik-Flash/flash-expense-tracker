"""CLI commands and I9: output holds counts only. Synthetic data only."""

import re
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app import cli
from app.config import settings
from app.engine.merchant import MERCHANT_VERSION
from app.engine.parsers.hdfc import PARSER_VERSION
from app.engine.reconcile import RECONCILE_VERSION, ROLES, RULES
from app.importers import sms_backup
from app.models import DuplicateCandidate, Transaction
from tests.smsdata import FIXTURES, NEVER_STORED, SBI_ROW, WHEN, write_backup


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


def test_reconcile_stats_prints_counts_only_and_writes_nothing(run, backup, db_engine) -> None:
    run("import-sms", "--input", str(backup))
    before = snapshot(db_engine)
    out = run("reconcile-stats")
    assert snapshot(db_engine) == before
    assert f"reconcile-stats ({RECONCILE_VERSION}, {MERCHANT_VERSION}, read-only)" in out
    active = int(re.search(r"transactions \(active\)\s+(\d+)", out).group(1))
    sections = dict(re.findall(r"^(\S[^\n]*)\n((?:  .*\n)+)", out, flags=re.M))
    by_direction = dict(re.findall(r"  (\w+ \w+)\s+(\d+)", sections["role by direction"]))
    by_rule = dict(re.findall(r"  (\w+)\s+(\d+)", sections["role by rule"]))
    assert active > 0 and sum(map(int, by_direction.values())) == active
    assert sum(map(int, by_rule.values())) == active
    assert {key.split()[1] for key in by_direction} <= set(ROLES) and set(by_rule) <= set(RULES)
    assert {"debit spend", "credit refund", "credit payback", "credit fd_move"} <= set(by_direction)
    paybacks = dict(re.findall(r"  (\w+)\s+(\d+)", sections["paybacks by basis"]))
    assert paybacks == {"engine": by_direction["credit payback"], "owner": "0"}
    uncertain = sum(int(n) for key, n in by_direction.items() if key.endswith(" uncertain"))
    assert re.search(rf"uncertain credits\s+{uncertain}\n", out)
    assert re.search(r"not counted yet\n  foreign currency\s+\d+\n  no parser\s+1\n", out)
    assert "debit duplicate" in by_direction  # the line is always there
    assert (
        len(re.findall(r"  \w+ (?:linked|candidate)\s+\d+\n", sections["links by kind and status"]))
        == 8
    )
    assert re.search(r"by time gap\n  up to 10 min\s+\d+\n  10-60 min\s+\d+\n  1-24 h\s+\d+\n", out)
    existing = dict(re.findall(r"  ([a-z ]+?)\s+(\d+)\n", sections["existing candidates"]))
    assert list(existing) == [
        "recorded",
        "linked",
        "still candidate",
        "decided different",
        "not active",
        "lost",
    ]
    assert existing["lost"] == "0"
    assert int(existing["recorded"]) == int(existing["linked"]) + int(existing["still candidate"])
    assert out.rstrip().endswith(cli.NO_INCOME_PARTY)
    assert_no_values(out)
    assert not any(k in out for k in ("brand:", "vpa:", "name:", "R5_"))


def test_reconcile_stats_counts_links_and_existing_candidates(run, db_engine) -> None:
    owner = settings.owner_id

    def row(key: str, channel: str, minute: int, amount: int) -> Transaction:
        return Transaction(
            owner_id=owner,
            dedupe_key=key,
            type="debit",
            direction="debit",
            amount_paise=amount,
            currency="INR",
            account_last4="0002",
            channel=channel,
            counterparty_raw="TEST STREAMING",
            txn_time_utc=WHEN + timedelta(minutes=minute),
            time_inferred=False,
            bank="HDFC",
            hints=[],
            status="active",
        )

    with sessionmaker(db_engine)() as session:
        rows = [
            row("a", "e_mandate", 0, 49_900),
            row("b", "debit_card", 3, 49_900),  # AutoPay + card, 3 minutes: linked
            row("c", "e_mandate", 0, 19_900),
            row("d", "debit_card", 45, 19_900),  # 45 minutes: candidate
            row("e", "upi", 0, 5_000),
            row("f", "upi", 2, 5_000),  # same amount, 2 minutes: candidate
        ]
        session.add_all(rows)
        session.flush()
        ids = [r.id for r in rows]
        for a, b in ((0, 1), (4, 5), (0, 5)):  # the last one: no rule finds it any more
            session.add(
                DuplicateCandidate(
                    txn_a=ids[a], txn_b=ids[b], rule="same_amount_10min", status="open"
                )
            )
        session.commit()
    before = snapshot(db_engine)
    out = run("reconcile-stats")
    assert snapshot(db_engine) == before
    for label, n in {
        "debit duplicate": 1,
        "debit spend": 5,
        "DUP_autopay_card": 1,
        "duplicate candidate": 3,
        "duplicate linked": 1,
        "refund linked": 0,
        "duplicate recorded_at_import": 1,
        "duplicate same_amount": 1,
        "duplicate within_24h": 1,
        "up to 10 min": 1,
        "10-60 min": 1,
        "1-24 h": 0,
        "same merchant key": 2,
        "brand on neither": 2,
        "earlier message is autopay": 2,
        "earlier message is card": 0,
        "recorded": 3,
        "linked": 1,
        "still candidate": 2,
        "decided different": 0,
        "not active": 0,
        "lost": 0,
    }.items():
        assert re.search(rf"^  {re.escape(label)}\s+{n}$", out, flags=re.M), label
    assert "TEST STREAMING" not in out and "0002" not in out and "49" not in out


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
