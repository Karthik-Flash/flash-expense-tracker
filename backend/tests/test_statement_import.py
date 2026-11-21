"""statement-import and the 4Z causes (D-120). FAKE statements and messages only.

Statement-only rows become transactions of source "statement": a likely spend is spend and
asks "Looks right?"; an FD is fd_move; a transfer to the owner's own name or an investment
is in no total until the owner answers; a credit never lowers Net. An unread HDFC message of
the same amount is counted, never imported. Importing twice adds nothing; the SMS that comes
later merges into the statement row and replaces it.
"""

import re
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.engine.statement_check import Context, stmt_cause
from app.engine.statement_hdfc import read
from app.models import OwnerName, RawMessage, Transaction, TxnDerived
from tests.smsdata import write_backup
from tests.statements import statement_text, upi

DAY = "10/03/26"


def sent(rupees: str, to: str, ref: str) -> tuple:
    body = (f"Sent Rs.{rupees}\nFrom HDFC Bank A/C *0001\nTo {to}\nOn {DAY}\nRef {ref}\n"
            "Not You?\nCall 18000000001/SMS BLOCK UPI to 9000000001\n")  # fmt: skip
    return ("VM-HDFCBK-S", body, datetime(2026, 3, 10, 6, 0, tzinfo=UTC))


UNREAD = ("VM-HDFCBK-S", "TEST NEW SHAPE: Rs.333.00 paid to TEST PERSON via TEST APP",
          datetime(2026, 3, 10, 7, 0, tzinfo=UTC))  # fmt: skip
LINES = [
    (DAY, upi("TEST SHOP KNOWN", "known@okaxis", "612300000001"), "100.00", "", "0"),  # in app
    (DAY, upi("TEST CAFE NEW", "cafe@okaxis", "612300000002"), "250.00", "", "0"),  # likely_spend
    (DAY, "FD THROUGH NET-50300000000009:TEST OWNER NAME", "5000.00", "", "0"),  # fd
    (DAY, "NEFT CR-TEST0000002-TEST OWNER NAME-SELF TRANSFER", "", "7000.00", "0"),  # own
    (DAY, "NEFT DR-TEST0000002-TEST OWNER NAME-TO MY SBI", "1500.00", "", "0"),  # own, debit
    (DAY, "ACH D- ZERODHA BROKING LTD-0000000009", "2000.00", "", "0"),  # investment
    (DAY, "IB BILLPAY DR-HDFC CREDIT CARD-XXXX0004", "900.00", "", "0"),  # card bill
    (DAY, "IMPS-612300000003-TEST VERIFY CO-HDFC-XXXXXX0009-ACC VERIFY", "", "1.00", "0"),  # tiny
    (DAY, "XXXXXXXX0009-TPT-TRF-TEST RELATIVE", "", "3000.00", "0"),  # likely_income
    (DAY, "POS 000000XXXXXX0001 TEST STORE ONLINE", "333.00", "", "0"),  # sms_not_parsed
    (DAY, "CHQ PAID-TEST LANDLORD", "4000.00", "", "0"),  # unknown
]


def load(run, tmp_path, factory) -> str:
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", [
        sent("100.00", "TEST SHOP KNOWN", "612300000001"), UNREAD,
    ])))  # fmt: skip
    with factory() as s:
        s.add(OwnerName(owner_id=settings.owner_id, name="Test Owner Name", source="app"))
        s.commit()
    path = tmp_path / "statement.txt"
    path.write_text(statement_text(LINES), encoding="utf-8")
    return str(path)


def stored(factory) -> dict[str, tuple]:
    t, d = Transaction, TxnDerived
    with factory() as s:
        rows = s.execute(
            select(t.amount_paise, t.direction, d.role, t.hints, t.status)
            .join(d, d.transaction_id == t.id)
            .where(t.owner_id == settings.owner_id)
        ).all()
    return {f"{direction} {amount}": (role, tuple(hints or ()), status)
            for amount, direction, role, hints, status in rows}  # fmt: skip


def test_every_cause_from_the_narration_and_the_stored_messages() -> None:
    rows = read(statement_text(LINES)).rows
    ctx = Context(
        ("Test Owner Name",), frozenset({"0001"}), ((date(2026, 3, 10), frozenset({33300})),)
    )
    causes = [stmt_cause(r, False, ctx) for r in rows]
    assert causes == [
        "likely_spend", "likely_spend", "fd", "own_or_internal", "own_or_internal",
        "investment_or_broking", "card_bill_payment", "verification_or_tiny", "likely_income",
        "sms_not_parsed", "unknown",
    ]  # fmt: skip
    # Without the owner's names a NEFT from the owner is plain income, never a transfer.
    assert stmt_cause(rows[3]) == "likely_income"


def test_dry_run_apply_and_idempotent(run, db_engine, tmp_path) -> None:
    factory = sessionmaker(db_engine, expire_on_commit=False)
    path = load(run, tmp_path, factory)
    before = stored(factory)
    dry = run("statement-import", "--file", path)
    assert "SAFE TO PASTE" in dry and "dry run" in dry
    assert re.search(r"^rows to import\s+9$", dry, re.M)
    assert re.search(r"^not imported: sms_not_parsed\s+1$", dry, re.M)
    assert "TEST" not in dry and "ZERODHA" not in dry
    assert stored(factory) == before

    applied = run("statement-import", "--file", path, "--apply")
    assert re.search(r"^imported\s+9$", applied, re.M) and "recompute run" in applied
    rows = stored(factory)
    assert rows["debit 25000"] == ("spend", ("statement", "statement_check"), "active")
    assert rows["debit 500000"][0] == "fd_move"
    assert rows["debit 150000"][:2] == ("uncertain", ("statement", "statement_ask"))  # own
    assert rows["debit 200000"][:2] == ("uncertain", ("statement", "statement_ask"))  # invest
    assert rows["debit 400000"][0] == "spend"  # unknown: spend, asks "Looks right?"
    assert {rows[k][0] for k in ("credit 700000", "credit 100", "credit 300000")} == {"uncertain"}
    assert "debit 33300" not in rows  # its SMS is stored, only unread: not imported

    again = run("statement-import", "--file", path, "--apply")
    assert re.search(r"^imported\s+0$", again, re.M)
    assert re.search(r"^rows to import\s+0$", again, re.M)  # now matched, nothing left
    with factory() as s:
        assert len(s.scalars(select(RawMessage).where(RawMessage.source == "statement")).all()) == 9


def test_net_never_goes_down_and_a_later_sms_replaces_the_row(run, db_engine, tmp_path) -> None:
    factory = sessionmaker(db_engine, expire_on_commit=False)
    path = load(run, tmp_path, factory)
    run("statement-import", "--file", path, "--apply")
    roles = stored(factory)
    assert not any(role == "payback" for role, *_ in roles.values())  # nothing in Paid back
    # The SMS of the imported likely spend arrives (same reference): one transaction.
    run("import-sms", "--input", str(write_backup(tmp_path / "b.xml", [
        sent("250.00", "TEST CAFE NEW", "612300000002"),
    ])))  # fmt: skip
    after = stored(factory)
    assert after["debit 25000"][1] == () and after["debit 25000"][0] == "spend"  # the SMS's words
    with factory() as s:
        n = s.scalars(select(Transaction).where(Transaction.amount_paise == 25000)).all()
    assert len(n) == 1
