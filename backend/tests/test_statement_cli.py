"""statement-check and statement-names against the app (D-114, D-116). FAKE data only."""

import re

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.engine.reconcile import IST, upi_reference
from app.models import Party, Transaction, TxnDerived
from app.pipeline.owner_actions import name_person
from app.pipeline.statement import nameless
from tests.smsdata import full_rows, write_backup
from tests.statements import statement_text, upi


def count(out: str, label: str) -> int:
    return int(re.search(rf"^{re.escape(label)}\s+(\d+)$", out, re.M).group(1))


def hdfc_rows(factory) -> list[tuple]:
    t, d = Transaction, TxnDerived
    with factory() as s:
        return s.execute(
            select(
                t.id,
                t.txn_time_utc,
                t.direction,
                t.amount_paise,
                t.reference,
                t.counterparty_raw,
                d.party_id,
            )  # fmt: skip
            .join(d, d.transaction_id == t.id)
            .where(t.bank == "HDFC", t.status == "active", d.role != "duplicate")
            .order_by(t.txn_time_utc, t.id)
        ).all()


def line_for(row, name: str = "TEST PAYER", extra_narration: str = "") -> tuple:
    _id, when, direction, amount, ref, _raw, _party = row
    day = when.astimezone(IST).strftime("%d/%m/%y")
    money = f"{amount / 100:.2f}"
    ref12 = upi_reference(ref)
    narration = upi(name, "test.x@okaxis", ref12) if ref12 else f"POS 0000 TEST{extra_narration}"
    debit, credit = (money, "") if direction == "debit" else ("", money)
    return (day, narration, debit, credit, f"0000{ref12}" if ref12 else "0")


def test_statement_check_end_to_end(run, db_engine, tmp_path) -> None:
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", full_rows())))
    factory = sessionmaker(db_engine, expire_on_commit=False)
    app = hdfc_rows(factory)
    first = app[0][1].astimezone(IST).strftime("%d/%m/%y")
    lines = [line_for(r) for r in app]
    lines.insert(0, (first, "ACH D- TEST INSURANCE LTD-0000000001", "999.00", "", "0"))
    lines.insert(1, (first, "CREDIT INTEREST CAPITALISED", "", "3.00", "0"))
    path = tmp_path / "statement.txt"
    path.write_text(statement_text(lines), encoding="utf-8")

    out = run("statement-check", "--file", str(path))
    assert "SAFE TO PASTE" in out and "balance breaks 0" in out
    months = re.findall(r"^month (\d{4}-\d{2})$", out, re.M)
    matched = sum(int(n) for n in re.findall(r"^  matched (\d+) ", out, re.M))
    assert matched == len(app) and months
    assert re.search(r"^    no_sms\s+2 ", out, re.M)  # the NACH debit and the interest
    assert re.search(r"^  app only\s+0 ", out, re.M)
    assert "with statement-only debits as spend" in out
    assert "TEST" not in out and "okaxis" not in out  # no narration, name or UPI ID
    # The unmatched rows are PRIVATE: only on a terminal.
    assert "prints only to a terminal" in run("statement-check", "--file", str(path), "--details",
                                              code=2)  # fmt: skip


def test_a_file_that_is_not_a_statement_is_refused(run, db_engine, tmp_path) -> None:
    path = tmp_path / "other.txt"
    path.write_text("TEST NOT A STATEMENT\n", encoding="utf-8")
    assert "no header" in run("statement-check", "--file", str(path), code=2)
    assert "no header" in run("statement-names", "--file", str(path), code=2)


def test_statement_names_dry_run_apply_and_owner_names_kept(run, db_engine, tmp_path) -> None:
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", full_rows())))
    factory = sessionmaker(db_engine, expire_on_commit=False)
    credits = [r for r in hdfc_rows(factory)
               if r[2] == "credit" and upi_reference(r[4]) and nameless(r[5])]  # fmt: skip
    assert len(credits) >= 2  # an unnamed and a masked UPI ID in the fixtures
    one, two = credits[:2]
    path = tmp_path / "statement.txt"
    path.write_text(
        statement_text([line_for(one, "TEST PAYER ONE"), line_for(two, "TEST PAYER TWO")]),
        encoding="utf-8",
    )
    dry = run("statement-names", "--file", str(path))
    assert count(dry, "nameless UPI credits matched") == 2
    assert count(dry, "parties to name") == 2 and "dry run" in dry
    assert "TEST PAYER" not in dry
    with factory() as s:
        assert s.scalars(select(Party).where(Party.display_name.is_not(None))).all() == []
    assert "prints only to a terminal" in run("statement-names", "--file", str(path), "--show",
                                              code=2)  # fmt: skip

    with factory() as s:  # the owner names the first one themselves
        name_person(s, settings.owner_id, one[0], "Test Owner Name", "app")
        s.commit()
    run("recompute")
    applied = run("statement-names", "--file", str(path), "--apply")
    assert count(applied, "already named: left alone") == 1
    assert "named 1 party (source statement)" in applied and "recompute run" in applied
    with factory() as s:
        named = {p.display_name: p.name_source for p in s.scalars(select(Party))
                 if p.display_name}  # fmt: skip
    assert named == {"Test Owner Name": "app", "TEST PAYER TWO": "statement"}
    again = run("statement-names", "--file", str(path), "--apply")
    assert count(again, "parties to name") == 0 and "named 0 parties" in again


def test_one_name_for_two_parties_is_reported_never_joined(run, db_engine, tmp_path) -> None:
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", full_rows())))
    factory = sessionmaker(db_engine, expire_on_commit=False)
    credits = [r for r in hdfc_rows(factory)
               if r[2] == "credit" and upi_reference(r[4]) and nameless(r[5])]  # fmt: skip
    path = tmp_path / "statement.txt"
    path.write_text(
        statement_text([line_for(credits[0], "TEST SAME"), line_for(credits[1], "TEST SAME")]),
        encoding="utf-8",
    )
    out = run("statement-names", "--file", str(path), "--apply")
    assert count(out, "names two parties would share") == 1 and "Same as" in out
    with factory() as s:
        parties = s.scalars(select(Party).where(Party.display_name == "TEST SAME")).all()
    assert len(parties) == 2 and parties[0].id != parties[1].id  # two people, not joined
