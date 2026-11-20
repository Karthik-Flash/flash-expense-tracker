"""SBI parser (D-108) against FAKE fixtures (tests/fixtures/sms/sbi.json), plus the notices it
refuses with a reason. HDFC and the generic banks are unchanged (other tests)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.engine import ParsedMessage, Unknown, parse_message
from app.engine.parsers import GENERIC_BANKS, PARSERS
from app.engine.parsers.sbi import PARSER, TEMPLATES

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "sms" / "sbi.json").read_text(encoding="utf-8")
)
WHEN = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)


def value(result: ParsedMessage, name: str):
    v = getattr(result, name)
    return v.isoformat().replace("+00:00", "Z") if isinstance(v, datetime) else v


@pytest.mark.parametrize("fx", FIXTURES, ids=[f["id"] for f in FIXTURES])
def test_fixture_parses_to_expected_fields(fx: dict) -> None:
    result = parse_message(fx["sender"], fx["body"], datetime.fromisoformat(fx["received_at"]))
    assert isinstance(result, ParsedMessage), result
    assert (result.bank, result.parser_version) == ("SBI", "sbi-1.0.0")
    assert {k: value(result, k) for k in fx["expected"]} == fx["expected"]
    assert result.hints == ()  # a dedicated parser: no "check" flag in the app
    assert len(PARSER.matching(fx["body"])) == 1


def test_every_template_has_a_fixture_and_sbi_is_not_generic() -> None:
    assert {f["id"].split("-")[1] for f in FIXTURES} == {t.id for t in TEMPLATES}
    assert PARSERS["SBI"] is PARSER and "SBI" not in GENERIC_BANKS


REFUSED = [
    (
        "Dear Customer, hold for Rs.2,000.00 created in deposit Ac XXXXX2468 on 10Mar26. If not "
        "consented, pl contact branch-SBI",
        "not_a_transaction",
        "hold",
    ),
    (
        "Dear customer, hold for Rs.2,000.00 has been removed from account no. XXXXX2468. If not "
        "requested, please contact your branch-SBI",
        "not_a_transaction",
        "hold",
    ),
    (
        "Dear Customer, TDR/STDR No XXXXX9001 for Rs.10,000.00 has been created on 10Mar26. Please "
        "submit form 15G/H, if eligible. Thank you for your patronage. Download YONO - SBI",
        "not_a_transaction",
        "deposit_notice",
    ),
    (
        "UPI-Mandate successfully created towards TEST STREAM for Rs.199.00 -SBI",
        "not_a_transaction",
        "mandate_notice",
    ),
    (
        "Dear UPI User, UPI AutoPay for TEST STREAM debit of Rs.199.00 is scheduled on 12-03-26, "
        "test.stream@oksbi. Please ensure sufficient balance in your account. -SBI",
        "not_a_transaction",
        "mandate_notice",
    ),
    (
        "SBI Carnival is back! Earn 5x Bonus Points with your SBI Debit Card. Offer valid till "
        "30Nov. T&C- SBI",
        "not_a_transaction",
        "promo",
    ),
    (
        "Dear SBI Customer, Beware of frauds. Never share OTP/PIN or click links. Report to 1930.",
        "not_a_transaction",
        "other",
    ),
    (
        "Rs.499.00 spent on your SBI Credit Card ending 7733 at TESTMART on 10/03/26.",
        "generic_unsure",
        "card_no_template",
    ),
    (
        "Rs.499.00 spent on your SBI Debit Card ending 4821 at TESTMART on 10/03/26.",
        "generic_unsure",
        "card_no_template",
    ),
    (
        "Amount of Rs.50,000.00 disbursed from SBI Loan A/c No XXXXX9001 on 10Mar26. For TEST "
        "COLLEGE",
        "generic_unsure",
        "no_template",
    ),
]


@pytest.mark.parametrize(("body", "reason", "detail"), REFUSED)
def test_what_no_template_reads_is_refused_with_a_reason(body, reason, detail) -> None:
    assert parse_message("VM-SBIINB", body, WHEN) == Unknown(reason, "SBI", detail)


def test_foreign_currency_and_a_naive_time() -> None:
    body = "USD 25.00 spent on SBI Debit Card ending 4821 at TEST SHOP on 10-03-26."
    assert parse_message("VM-SBIINB", body, WHEN).reason == "foreign_currency_deferred"
    with pytest.raises(ValueError):
        PARSER.parse(FIXTURES[0]["body"], datetime(2026, 3, 10))


def test_a_credit_card_spend_is_never_a_debit_card_spend() -> None:
    for body, *_ in REFUSED:
        result = parse_message("VM-SBIINB", body, WHEN)
        assert not (isinstance(result, ParsedMessage) and result.channel == "debit_card")
