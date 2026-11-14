"""Engine building blocks: sender IDs, money, time, result models. Fake data only."""

import dataclasses
import json
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.engine.filters import is_otp, is_promotional
from app.engine.models import ParsedMessage
from app.engine.money import AmountError, to_paise
from app.engine.senders import SENDER_BANKS, bank_for, parse_sender
from app.engine.timeparse import parse_date, parse_ist_datetime, txn_time

FIXTURES = Path(__file__).parent / "fixtures"
SENDER_CASES = json.loads((FIXTURES / "sender_ids.json").read_text(encoding="utf-8"))


# --- Sender IDs (shared table; scripts/test_redact_sms.py runs it too) -------
@pytest.mark.parametrize("case", SENDER_CASES, ids=[c["address"] for c in SENDER_CASES])
def test_shared_sender_table(case: dict) -> None:
    assert parse_sender(case["address"]) == (case["core"], case["suffix"])


def test_bank_registry() -> None:
    assert bank_for("HDFCBK") == bank_for("HDFCBN") == "HDFC"
    assert bank_for("SBIBNK") == "SBI"
    assert bank_for("ABC123@RBM.GOOG") is None
    assert bank_for("+919876543210") is None
    assert len(SENDER_BANKS) == 14


# --- Money --------------------------------------------------------------------
RUPEE = chr(0x20B9)


@pytest.mark.parametrize(
    ("text", "paise"),
    [
        ("Rs.1,25,000.00", 12500000),
        ("INR 2,22,222", 22222200),
        (f"{RUPEE}555", 55500),
        (f"{RUPEE} 6,666", 666600),
        ("Rs. 33", 3300),
        ("Rs.1.5", 150),
        ("INR.444.67", 44467),
        ("INR14.07", 1407),
        ("rs.12,345", 1234500),
        ("12,34,567.89", 123456789),
        ("Rs.0.75", 75),
    ],
)
def test_to_paise(text: str, paise: int) -> None:
    assert to_paise(text) == paise
    assert isinstance(to_paise(text), int)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Rs.",
        "100,000",  # western grouping above 99,999: ambiguous
        "1,234,567",
        "1,00,00",
        "12,34",
        "Rs.1.234",  # three decimals
        "1,000.5.5",
        "-5",
        "1e3",
        "USD 12",
        "007",
        ".50",
    ],
)
def test_to_paise_rejects_ambiguous(text: str) -> None:
    with pytest.raises(AmountError):
        to_paise(text)


# --- Time ---------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("31-03-26", date(2026, 3, 31)),
        ("09/04/26", date(2026, 4, 9)),
        ("03/04/2026", date(2026, 4, 3)),
        ("19-OCT-2026", date(2026, 10, 19)),
        ("18-JAN-26", date(2026, 1, 18)),
        ("12-Nov-26", date(2026, 11, 12)),
        ("2026-01-17", date(2026, 1, 17)),
    ],
)
def test_parse_date_formats(text: str, expected: date) -> None:
    assert parse_date(text) == expected


@pytest.mark.parametrize(
    "text", ["31-02-26", "09/13/26", "01-ABC-2026", "2026/01/01", "1-1-26", "2026-02-30"]
)
def test_parse_date_rejects_invalid(text: str) -> None:
    with pytest.raises(ValueError):
        parse_date(text)


def test_ist_datetime_to_utc_crosses_midnight() -> None:
    assert parse_ist_datetime("2026-01-01:02:00:00") == datetime(2025, 12, 31, 20, 30, tzinfo=UTC)
    assert parse_ist_datetime("2026-01-08:10:00:00") == datetime(2026, 1, 8, 4, 30, tzinfo=UTC)


def test_txn_time_infers_from_received_at() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    received = datetime(2026, 1, 5, 12, 0, tzinfo=ist)
    assert txn_time(None, received) == (datetime(2026, 1, 5, 6, 30, tzinfo=UTC), True)
    assert txn_time("2026-01-05:11:00:00", received)[1] is False
    with pytest.raises(ValueError):
        txn_time(None, datetime(2026, 1, 5, 12, 0))  # naive


# --- Models -------------------------------------------------------------------
def _msg(**changes: object) -> ParsedMessage:
    base = dict(
        bank="HDFC",
        template_id="H01",
        parser_version="hdfc-1.0.0",
        type="debit",
        direction="debit",
        amount_paise=3300,
        currency="INR",
        account_last4="0001",
        channel="upi",
        counterparty_raw="TEST MERCHANT",
        reference="000000000001",
        balance_paise=None,
        txn_time_utc=datetime(2026, 1, 5, tzinfo=UTC),
        time_inferred=True,
    )
    return ParsedMessage(**{**base, **changes})


def test_parsed_message_is_frozen_and_flags_money() -> None:
    msg = _msg()
    assert msg.is_money and msg.hints == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        msg.amount_paise = 1  # type: ignore[misc]
    info = _msg(type="other_info", direction=None, amount_paise=None, txn_time_utc=None)
    assert not info.is_money


def test_parsed_message_validates() -> None:
    with pytest.raises(ValueError):
        _msg(type="spend")
    with pytest.raises(ValueError):
        _msg(amount_paise=None)  # money without an amount


# --- Filters ------------------------------------------------------------------
OTP_CASES = json.loads((FIXTURES / "otp_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", OTP_CASES, ids=[c["body"][:30] for c in OTP_CASES])
def test_shared_otp_table(case: dict) -> None:
    """Same table as scripts/test_redact_sms.py: both OTP rules agree."""
    assert is_otp(case["body"]) is case["otp"]


def test_promotional_suffix() -> None:
    assert is_promotional(parse_sender("VM-HDFCBK-P")[1])
    assert not is_promotional(parse_sender("VM-HDFCBK-S")[1])
