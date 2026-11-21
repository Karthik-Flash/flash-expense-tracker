"""HDFC parser against fake fixtures, plus every Unknown reason."""

import json
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.engine import ParsedMessage, Unknown, parse_message
from app.engine.parsers import PARSERS
from app.engine.parsers.base import BankParser, Template
from app.engine.parsers.hdfc import PARSER, PARSER_VERSION
from app.pipeline.sample_export import redact

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
    no_template = fx["expected"] == {"type": "foreign_currency"} or "-H_INFO-" in fx["id"]
    assert n == (0 if no_template else 1)


def test_every_template_has_a_fixture() -> None:
    covered = {fx["id"].split("-")[1] for fx in FIXTURES}
    assert {t.id for t in PARSER.templates} <= covered


@pytest.mark.parametrize(
    ("template_id", "hints"),
    [
        ("N02", ("card_bill_payment",)),
        ("H04", ("forex_notice",)),
        ("H08", ("mandate_reference",)),
        ("H13", ("mandate_reference",)),
        ("H17", ("autopay",)),
        ("H19", ("mandate_cancelled",)),
        ("H20", ("fd_closure",)),
        ("H21", ("mf_order",)),
        ("H_INFO", ()),
    ],
)
def test_template_hints(template_id: str, hints: tuple[str, ...]) -> None:
    for fx in (f for f in FIXTURES if f["id"].split("-")[1] == template_id):
        assert parse_message(fx["sender"], fx["body"], received(fx)).hints == hints


# --- Info fallback: amount-free notices only ----------------------------------
def test_amount_free_notice_is_info() -> None:
    result = parse_message("VM-HDFCBK-S", "Hello from a test", WHEN)
    assert isinstance(result, ParsedMessage)
    assert (result.template_id, result.type, result.is_money) == ("H_INFO", "other_info", False)


@pytest.mark.parametrize(
    "body",
    [
        "Rs 33 hello from a test",
        "Paid INR.33 to TEST",
        "Hello, " + chr(0x20B9) + "33 from a test",
        "Txn of USD 12 at TEST STORE",
    ],
)
def test_unmatched_message_with_amount_stays_no_template(body: str) -> None:
    assert parse_message("HDFCBK", body, WHEN) == Unknown("no_template", "HDFC")


def test_parser_without_fallback_keeps_no_template() -> None:
    result = BankParser("TEST", "test-1.0.0", ()).parse("Hello from a test", WHEN)
    assert result == Unknown("no_template", "TEST")


# --- Unknown reasons ----------------------------------------------------------
def test_unknown_sender() -> None:
    assert parse_message("+919000000001", "Rs 33 sent", WHEN) == Unknown("unknown_sender")
    assert parse_message("TEST@RBM.GOOG", "Rs 33 sent", WHEN) == Unknown("unknown_sender")


def test_no_parser_for_bank() -> None:
    no_parser = Unknown("no_parser_for_bank", "PHONEPE")  # an app, never read (D-101)
    assert parse_message("VM-PHONPE", "Rs 33 debited", WHEN) == no_parser


def test_foreign_currency_deferred() -> None:
    body = "Spent EUR 9.99 On HDFC Bank Card 0003 At TEST STORE On 2026-01-05:10:00:00"
    assert parse_message("HDFCBK", body, WHEN).reason == "foreign_currency_deferred"


# The owner's approved sample of the HDFC messages no parser read (4Z, 44 messages, one
# shape): shape tokens only, words outside the bank vocabulary as {WORD}.
UNREAD_SHAPE = (
    "{WORD}!\n"
    "{NUM}. {WORD} {WORD} {WORD} {WORD} to your HDFC Bank Debit Card {WORD} payment\n"
    "{NUM}. {WORD} txn amount may {WORD} {WORD} on {WORD} {WORD} on the {WORD} date"
)


def test_h04_is_the_unread_shape_and_a_notice_with_no_money() -> None:
    """hdfc-1.2.0 (D-127): the forex markup notice was foreign_currency_deferred, counted in
    "not counted yet"; it holds no amount, so it is a notice and never a transaction."""
    forex = [f for f in FIXTURES if f["id"].startswith("hdfc-H04-")]
    assert len(forex) == 3
    assert redact(forex[0]["body"], Counter())[0] == UNREAD_SHAPE
    for fx in forex:
        result = parse_message(fx["sender"], fx["body"], received(fx))
        assert (result.template_id, result.type, result.is_money) == ("H04", "other_info", False)
    # With an amount it is no notice: never read as H04, never guessed.
    with_amount = forex[1]["body"].replace("payment", "payment of Rs.33")
    assert parse_message("HDFCBK", with_amount, WHEN) == Unknown("no_template", "HDFC")


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
