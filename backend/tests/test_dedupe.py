"""Dedupe rules (pure functions). Fake values only."""

import dataclasses
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.engine import ParsedMessage
from app.pipeline.dedupe import content_hash, epoch_ms, is_candidate, transaction_key

T = datetime(2026, 1, 5, 6, 30, 0, 123000, tzinfo=UTC)
IST = timezone(timedelta(hours=5, minutes=30))
MONEY = ParsedMessage(
    bank="HDFC",
    template_id="H01",
    parser_version="hdfc-1.1.0",
    type="debit",
    direction="debit",
    amount_paise=3300,
    currency="INR",
    account_last4="0001",
    channel="upi",
    counterparty_raw="TEST STORE",
    reference="000000000001",
    balance_paise=None,
    txn_time_utc=T,
    time_inferred=True,
)


def test_epoch_ms_is_exact_and_needs_a_time_zone() -> None:
    assert epoch_ms(T) == 1767594600123
    assert epoch_ms(T.astimezone(IST)) == epoch_ms(T)
    with pytest.raises(ValueError):
        epoch_ms(datetime(2026, 1, 5))


def test_content_hash_depends_on_core_body_and_millisecond() -> None:
    base = content_hash("HDFCBK", "body", T)
    assert base == content_hash("HDFCBK", "body", T.astimezone(IST))
    assert base != content_hash("HDFCBN", "body", T)
    assert base != content_hash("HDFCBK", "body ", T)
    assert base != content_hash("HDFCBK", "body", T + timedelta(milliseconds=1))
    assert len(base) == 64


def test_reference_key_ignores_account_and_raw_message() -> None:
    other_account = dataclasses.replace(MONEY, account_last4="0009", channel=None)
    assert transaction_key(MONEY, "h1") == transaction_key(other_account, "h2")


@pytest.mark.parametrize(
    "change",
    [{"direction": "credit", "type": "credit"}, {"amount_paise": 3301}, {"reference": "x2"}],
)
def test_reference_key_changes_with_direction_amount_reference(change: dict) -> None:
    assert transaction_key(MONEY, "h") != transaction_key(dataclasses.replace(MONEY, **change), "h")


def test_without_reference_the_key_is_the_raw_message() -> None:
    no_ref = dataclasses.replace(MONEY, reference=None)
    assert transaction_key(no_ref, "h1") == transaction_key(no_ref, "h1")
    assert transaction_key(no_ref, "h1") != transaction_key(no_ref, "h2")  # never fuzzy


def test_non_money_and_zero_amounts_make_no_transaction() -> None:
    mandate = dataclasses.replace(MONEY, type="mandate", direction=None, txn_time_utc=None)
    assert transaction_key(mandate, "h") is None
    assert transaction_key(dataclasses.replace(MONEY, amount_paise=0), "h") is None


def txn(**change) -> SimpleNamespace:
    base = {
        "owner_id": 1,
        "bank": "HDFC",
        "account_last4": "0002",
        "direction": "debit",
        "amount_paise": 3300,
        "reference": None,
        "txn_time_utc": T,
    }
    return SimpleNamespace(**(base | change))


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"txn_time_utc": T + timedelta(minutes=10)}, True),
        ({"txn_time_utc": T - timedelta(minutes=9), "reference": "r1"}, True),
        ({"txn_time_utc": T + timedelta(minutes=10, seconds=1)}, False),
        ({"direction": "credit"}, False),  # self-transfer halves never match
        ({"amount_paise": 3301}, False),
        ({"account_last4": "0003"}, False),
        ({"bank": "SBI"}, False),
        ({"owner_id": 2}, False),
    ],
)
def test_candidate_rule(change: dict, expected: bool) -> None:
    assert is_candidate(txn(), txn(**change)) is expected


def test_shared_reference_is_not_a_candidate() -> None:
    assert not is_candidate(txn(reference="r1"), txn(reference="r1"))


def test_mandate_reference_never_merges_monthly_charges() -> None:
    """AutoPay SMS carry the mandate ID: same every month, so it is not a payment key."""
    charge = dataclasses.replace(MONEY, reference="TESTMANDATE1", hints=("mandate_reference",))
    assert transaction_key(charge, "jan") != transaction_key(charge, "feb")
    assert transaction_key(charge, "jan") == transaction_key(
        dataclasses.replace(charge, reference=None), "jan"
    )
