"""doctor (premium D, D-150): read-only, counts only, exit 1 on a problem. FAKE data."""

import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from app.models import RawMessage, Transaction, TransactionSource, TxnDerived


def counts(db_engine) -> tuple[int, ...]:
    with sessionmaker(db_engine)() as s:
        return tuple(
            s.scalar(select(func.count()).select_from(m))
            for m in (RawMessage, Transaction, TransactionSource, TxnDerived)
        )


def value(out: str, name: str) -> int:
    return int(re.search(rf"^{re.escape(name)}\s+(\d+)$", out, flags=re.M).group(1))


def test_healthy_data_passes_and_nothing_is_written(run, data, db_engine) -> None:
    before = counts(db_engine)
    out = run("doctor")
    assert value(out, "problems") == 0 and "doctor: healthy" in out
    assert value(out, "transactions (active)") > 5 and value(out, "months checked") >= 1
    assert value(out, "months that disagree") == 0
    assert counts(db_engine) == before
    assert "Rs" not in out and "@" not in out  # counts only


def test_a_missing_source_and_stale_tables_are_problems(run, data, db_engine) -> None:
    with sessionmaker(db_engine)() as s:
        txn = s.scalars(select(Transaction.id).order_by(Transaction.id)).first()
        s.execute(delete(TransactionSource).where(TransactionSource.transaction_id == txn))
        s.execute(delete(TxnDerived).where(TxnDerived.transaction_id == txn))
        s.commit()
    out = run("doctor", code=1)
    assert value(out, "without a source message") == 1
    assert value(out, "without derived data") == 1
    assert "PROBLEMS FOUND" in out


def test_a_view_that_disagrees_is_found(run, data, monkeypatch) -> None:
    from app.api import analytics

    real = analytics.build

    def off_by_one(session, owner, months):
        answer = real(session, owner, months)
        answer["months"][0]["spent_paise"] += 1
        return answer

    monkeypatch.setattr(analytics, "build", off_by_one)
    out = run("doctor", code=1)
    assert value(out, "months that disagree") == 1


def test_no_parser_counts_by_sender_code_and_bank(run, tmp_path) -> None:
    """5G (D-158): what no parser reads yet, by sender code and bank; counts only."""
    from tests.smsdata import NO_PARSER_ROW, WHEN, full_rows, write_backup

    extra = [(NO_PARSER_ROW[0], NO_PARSER_ROW[1].replace("33", "44"), WHEN)]
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", full_rows() + extra)))
    out = run("no-parser")
    assert out.startswith("no-parser (read-only, counts only)")
    assert re.search(r"^  PHONPE\s+PHONEPE\s+2  2026-01$", out, flags=re.M)
    assert value(out, "messages") == 2
    assert "debited" not in out and "33" not in out  # never the text
