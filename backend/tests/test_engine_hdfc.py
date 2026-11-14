"""HDFC parser against fake fixtures, plus every Unknown reason."""

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.engine import ParsedMessage, Unknown, parse_message
from app.engine.parsers import PARSERS
from app.engine.parsers.base import BankParser, Template
from app.engine.parsers.hdfc import PARSER, PARSER_VERSION

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "sms" / "hdfc.json").read_text(encoding="utf-8")
)
WHEN = datetime(2026, 1, 5, 6, 30, tzinfo=UTC)


def received(fx: dict) -> datetime:
    return datetime.fromisoformat(fx["received_at"])


def utc_iso(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


@pytest.mark.parametrize("fx", FIXTURES, ids=[f["id"] for f in FIXTURES])
def test_fixture_parses_to_expected_fields(fx: dict) -> None:
    result = parse_message(fx["sender"], fx["body"], received(fx))
    expected = fx["expected"]
    if expected == {"type": "foreign_currency"}:
        assert result == Unknown("foreign_currency_deferred", "HDFC")
        return
    assert isinstance(result, ParsedMessage), result
    got = {k: getattr(result, k) for k in expected}
    got["txn_time_utc"] = utc_iso(result.txn_time_utc)
    assert got == expected
    assert result.bank == "HDFC" and result.parser_version == PARSER_VERSION
    assert result.template_id == fx["id"].split("-")[1]  # hdfc-H01-... -> H01
    assert result.currency == ("INR" if result.amount_paise is not None else None)


@pytest.mark.parametrize("fx", FIXTURES, ids=[f["id"] for f in FIXTURES])
def test_fixture_matches_exactly_one_template(fx: dict) -> None:
    n = len(PARSER.matching(fx["body"]))
    assert n == (0 if fx["expected"] == {"type": "foreign_currency"} else 1)


def test_every_template_has_a_fixture() -> None:
    covered = {fx["id"].split("-")[1] for fx in FIXTURES}
    assert {t.id for t in PARSER.templates} <= covered


def test_card_bill_payment_hint() -> None:
    fx = next(f for f in FIXTURES if f["id"].startswith("hdfc-N02"))
    assert parse_message(fx["sender"], fx["body"], received(fx)).hints == ("card_bill_payment",)


# --- Unknown reasons ----------------------------------------------------------
def test_unknown_sender() -> None:
    assert parse_message("+919000000001", "Rs 33 sent", WHEN) == Unknown("unknown_sender")
    assert parse_message("TEST@RBM.GOOG", "Rs 33 sent", WHEN) == Unknown("unknown_sender")


def test_no_parser_for_bank() -> None:
    assert parse_message("VM-SBIBNK", "Rs 33 debited", WHEN) == Unknown("no_parser_for_bank", "SBI")


def test_no_template() -> None:
    assert parse_message("VM-HDFCBK-S", "Hello from a test", WHEN) == Unknown("no_template", "HDFC")


def test_foreign_currency_deferred() -> None:
    body = "Spent EUR 9.99 On HDFC Bank Card 0003 At TEST STORE On 2026-01-05:10:00:00"
    assert parse_message("HDFCBK", body, WHEN).reason == "foreign_currency_deferred"


def test_two_matching_templates_are_ambiguous() -> None:
    a = Template("A1", re.compile(r"Paid (?P<amount>Rs\.\d+)"), "debit", "upi")
    b = Template("B1", re.compile(r"Paid Rs\.\d+"), "other_info")
    result = BankParser("TEST", "test-1.0.0", (a, b)).parse("Paid Rs.33", WHEN)
    assert isinstance(result, Unknown) and result.reason == "ambiguous"
    assert "A1" in result.detail and "B1" in result.detail


@pytest.mark.parametrize(
    "body",
    [
        # card number differs inside one message
        "Spent Rs.33 From HDFC Bank Card x0002 At TEST STORE On 2026-01-05:10:00:00 "
        "Bal Rs.44 Not You? Call 18000000001/SMS BLOCK DC 0009 to 9000000001",
        # invalid calendar date
        "Credit Alert!\nRs.33.00 credited to HDFC Bank A/c XX0001 on 31-02-26 from VPA "
        "test.user@okaxis (UPI 000000000001)",
        # western grouping above 99,999
        "Credit Alert!\nRs.100,000.00 credited to HDFC Bank A/c XX0001 on 05-01-26 from VPA "
        "test.user@okaxis (UPI 000000000001)",
    ],
)
def test_invalid_fields_are_ambiguous(body: str) -> None:
    result = parse_message("HDFCBK", body, WHEN)
    assert isinstance(result, Unknown) and result.reason == "ambiguous"


def test_naive_received_at_raises() -> None:
    with pytest.raises(ValueError):
        parse_message("HDFCBK", FIXTURES[0]["body"], datetime(2026, 1, 5))


def test_registry_and_template_ids() -> None:
    assert PARSERS["HDFC"] is PARSER
    ids = [t.id for t in PARSER.templates]
    assert len(ids) == len(set(ids))


def test_engine_imports_no_web_db_or_config() -> None:
    code = (
        "import sys, app.engine\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in ('fastapi', 'sqlalchemy', "
        "'pydantic_settings') or m == 'app.config']\n"
        "assert not bad, bad\n"
    )
    backend = Path(__file__).resolve().parent.parent
    subprocess.run([sys.executable, "-c", code], cwd=backend, check=True)
