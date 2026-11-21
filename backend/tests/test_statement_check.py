"""statement-check matching and causes (D-114). Pure; FAKE statements only."""

from datetime import date

from app.engine.statement_check import CAUSES, AppRow, check, match
from app.engine.statement_hdfc import read
from tests.statements import statement_text, upi

D = date


def app(id: int, day: date, amount: int, direction: str = "debit", ref12: str | None = None,
        last4: str | None = "0001", channel: str | None = "upi") -> AppRow:  # fmt: skip
    return AppRow(id, day, direction, amount, ref12, last4, channel)


def rows(*lines):
    return read(statement_text(list(lines))).rows


def causes(month) -> dict[str, int]:
    return {c: s.count for c, s in month.causes.items() if s.count}


def test_reference_first_then_amount_and_day_never_twice() -> None:
    stmt = rows(
        ("05/01/26", upi("TEST A", "a@okaxis", "600000000001"), "100.00", "", "0000600000000001"),
        ("05/01/26", "POS 0000 TEST STORE", "250.00", "", "0"),
        ("05/01/26", "POS 0000 TEST STORE", "250.00", "", "0"),  # two, but one app row
        ("07/01/26", "POS 0000 TEST OTHER", "80.00", "", "0"),
    )
    found = match(stmt, [
        app(1, D(2026, 1, 9), 100_00, ref12="600000000001"),  # far, but the reference decides
        app(2, D(2026, 1, 5), 100_00),  # same amount and day: never takes the reference's pair
        app(3, D(2026, 1, 6), 250_00),
        app(4, D(2026, 1, 8), 80_00),  # one day later
        app(5, D(2026, 1, 7), 80_00),  # the same day wins over the next day
    ])  # fmt: skip
    assert [(m.stmt.line, m.app.id, m.by) for m in found] == [
        (6, 1, "reference"), (9, 5, "amount_day"), (7, 3, "amount_day")
    ]  # fmt: skip
    assert len({m.app.id for m in found}) == len(found)


def test_an_amount_mismatch_by_reference() -> None:
    stmt = rows(("05/01/26", upi("TEST A", "a@okaxis", "600000000001"), "100.00", "", "0"))
    month = check(stmt, [app(1, D(2026, 1, 5), 90_00, ref12="600000000001")])["2026-01"]
    assert month.matched["reference"] == 1
    assert (month.mismatches.count, month.mismatches.paise) == (1, 10_00)


def test_every_cause() -> None:
    stmt = rows(
        ("02/01/26", "ACH D- TEST INSURANCE-0001", "999.00", "", "0"),  # no_sms
        ("03/01/26", "IMPS-600000000009-TEST PERSON-NOTE", "", "500.00", "0"),  # no_sms
        ("04/01/26", "POS 0000 TEST SHOP USD 12.00 MARKUP", "1100.00", "", "0"),  # foreign
        ("06/01/26", "UPI-TEST SHOP-s@okaxis-X-600000000010-PAY", "300.00", "", "0"),  # reversed
        ("07/01/26", "UPI-REV-TEST SHOP-600000000011", "", "300.00", "0"),  # reversed
        ("10/01/26", "POS 0000 TEST KNOWN", "40.00", "", "0"),  # matched
        ("12/01/26", "SOMETHING ELSE TEST", "70.00", "", "0"),  # unknown
        ("31/01/26", "POS 0000 TEST LATE", "55.00", "", "0"),  # month_edge
        ("31/01/26", "CREDIT INTEREST CAPITALISED", "", "3.00", "0"),  # no_sms
    )
    the_app = [
        app(1, D(2026, 1, 10), 40_00),  # matched
        app(2, D(2026, 1, 10), 40_00),  # duplicate_alert: a second alert for the same row
        app(3, D(2026, 1, 15), 500_00, channel="credit_card", last4="0004"),  # card
        app(4, D(2026, 1, 16), 60_00, last4="0009"),  # another account
        app(5, D(2026, 1, 20), 25_00),  # unknown
        app(6, D(2026, 1, 22), 75_00), app(7, D(2026, 1, 23), 75_00, "credit"),  # reversed
        app(8, D(2026, 2, 1), 55_00),  # month_edge: the statement says 31 Jan
        app(9, D(2026, 1, 3), 1_00, ref12="600000000099"),  # its reference fixes the account
    ]  # fmt: skip
    stmt_9 = rows(("03/01/26", upi("T", "t@okaxis", "600000000099"), "1.00", "", "0"))
    months = check([*stmt, *stmt_9], the_app)
    jan, feb = months["2026-01"], months["2026-02"]
    assert causes(jan) == {
        "no_sms": 3, "foreign_currency": 1, "reversed_or_failed": 4, "unknown": 2,
        "month_edge": 1, "duplicate_alert": 1, "card_or_other_account": 2,
    }  # fmt: skip
    assert causes(feb) == {"month_edge": 1}
    assert sum(jan.matched.values()) == 2  # 40.00 by amount and day, 1.00 by reference
    assert (jan.stmt_only.count, jan.app_only.count) == (8, 6)  # the edge app row is in Feb
    # Statement-only debits that count as spend in the comparison: not reversals, not edges.
    assert jan.stmt_only_debits.paise == 999_00 + 1100_00 + 70_00
    assert set(CAUSES) == set(jan.causes)
    assert {side for side, _, _ in jan.unmatched} == {"statement", "app"}


def test_months_follow_the_statements_days() -> None:
    stmt = rows(
        ("31/12/25", "POS 0000 TEST", "10.00", "", "0"),
        ("01/01/26", "POS 0000 TEST", "20.00", "", "0"),
    )
    months = check(stmt, [app(1, D(2025, 12, 31), 10_00), app(2, D(2026, 1, 1), 20_00)])
    assert list(months) == ["2025-12", "2026-01"]
    assert all(sum(m.matched.values()) == 1 for m in months.values())
    assert months["2025-12"].stmt_debits.paise == 10_00 and months["2026-01"].app_debits.count == 1
