"""The HDFC statement reader (D-114). FAKE statements only."""

from datetime import date
from pathlib import Path

import pytest

from app.engine.statement_hdfc import (
    STATEMENT_VERSION,
    StatementError,
    check_balances,
    narration_parts,
    read,
)
from tests.statements import statement_text, upi

FIXTURE = Path(__file__).parent / "fixtures" / "statements" / "hdfc-fake-nov.txt"


def test_the_fixture_file_in_the_banks_shape() -> None:
    s = read(FIXTURE.read_text(encoding="utf-8"))
    assert STATEMENT_VERSION == "stmt-hdfc-1.0.0"
    assert len(s.rows) == 8 and s.skipped == 11  # preamble, header, footer, blank lines
    assert check_balances(s.rows) == 0
    first, money_in, salary = s.rows[:3]
    assert (first.date, first.direction, first.amount_paise) == (date(2026, 11, 1), "debit", 25000)
    assert (first.channel, first.name, first.vpa, first.ref12) == (
        "upi", "TEST SHOP ONE", "testshop1@okaxis", "631100000001"
    )  # fmt: skip
    assert (money_in.direction, money_in.amount_paise, money_in.name) == (
        "credit", 150000, "TEST PERSON B"
    )  # fmt: skip
    # A comma inside the narration: read from the right, the amounts are still in place.
    assert "STIPEND, HOSTEL" in salary.narration
    assert (salary.channel, salary.credit_paise, salary.balance_paise) == ("neft", 1000000, 6125000)
    assert [r.channel for r in s.rows] == [
        "upi", "upi", "neft", "nach", "atm", "pos", "interest", "charges"
    ]  # fmt: skip
    assert s.rows[5].amount_paise == 45050  # paise kept


def test_an_overdrawn_balance_is_read() -> None:
    rows = read(statement_text([("01/01/26", "ATW-0000-TEST", "100.00", "", "0")], "50.00")).rows
    assert rows[0].balance_paise == -5000 and check_balances(rows) == 0


def test_a_balance_break_is_counted() -> None:
    text = statement_text([
        ("01/01/26", "ATW-0000-TEST", "100.00", "", "0"),
        ("02/01/26", "ATW-0000-TEST", "100.00", "", "0"),
    ])  # fmt: skip
    rows = read(text).rows
    assert check_balances(rows) == 0
    broken = text.replace("49800.00", "49700.00")
    assert check_balances(read(broken).rows) == 1


@pytest.mark.parametrize(
    ("narration", "ref", "expected"),
    [
        (upi("TEST A-B NAME", "a.b@okaxis", "612345678901"), "",
         ("upi", "TEST A-B NAME", "a.b@okaxis", "612345678901")),
        ("IMPS-612345678902-TEST PERSON-HDFC-XXXX0001-NOTE", "0000612345678902",
         ("imps", None, None, "612345678902")),
        ("NEFT DR-TEST0000001-TEST PERSON-NETBANK, MUM-N012345", "N012345",
         ("neft", None, None, None)),
        ("ACH D- TEST INSURANCE LTD-0000000001", "0000000000000000", ("nach", None, None, None)),
        ("CREDIT INTEREST CAPITALISED", "0", ("interest", None, None, None)),
        ("IB BILLPAY DR-TEST POWER", "0", ("netbanking", None, None, None)),
        ("SOMETHING NEW", "000000612345678903", ("other", None, None, "612345678903")),
    ],
)  # fmt: skip
def test_narration_parts(narration: str, ref: str, expected: tuple) -> None:
    assert narration_parts(narration, ref) == expected


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not a statement\n01/01/26,x,01/01/26,1.00,,0,1.00\n", "no header"),
        (statement_text([("01/01/26", "X", "1.00", "2.00", "0")]), "exactly one"),
        (statement_text([("01/01/26", "X", "1.00", "", "0")]).replace(" 1.00 ,", " 1.x0 ,"),
         "not a number"),
    ],
)  # fmt: skip
def test_what_is_not_a_statement_is_refused_without_values(text: str, message: str) -> None:
    with pytest.raises(StatementError, match=message) as exc:
        read(text)
    assert "TEST" not in str(exc.value)
