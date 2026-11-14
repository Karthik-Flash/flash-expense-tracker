"""Structural checks for SMS parser fixtures (no parser yet; fake data only)."""

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sms"
FIELDS = {
    "type",
    "amount_paise",
    "direction",
    "account_last4",
    "channel",
    "counterparty_raw",
    "reference",
    "balance_paise",
    "txn_time_utc",
}
TYPES = {
    "debit",
    "credit",
    "refund",
    "collect_request",
    "mandate",
    "card_alert",
    "balance_info",
    "fraud_warning",
    "foreign_currency",
    "other_info",
}
CHANNELS = {
    "upi",
    "netbanking",
    "debit_card",
    "atm",
    "credit_card",
    "e_mandate",
    "nach",
    "neft",
    "imps",
    "emi",
    "cash",
}
FIXTURES = [
    (path.stem, fx)
    for path in sorted(FIXTURE_DIR.glob("*.json"))
    for fx in json.loads(path.read_text(encoding="utf-8"))
]


def is_utc_iso(value: str) -> bool:
    return value.endswith("Z") and datetime.fromisoformat(value) is not None


def test_fixture_ids_are_unique() -> None:
    ids = [fx["id"] for _, fx in FIXTURES]
    assert ids and len(ids) == len(set(ids))


@pytest.mark.parametrize(("bank", "fx"), FIXTURES, ids=[fx["id"] for _, fx in FIXTURES])
def test_fixture_shape(bank: str, fx: dict) -> None:
    assert set(fx) == {"id", "sender", "body", "received_at", "expected"}
    assert fx["id"].startswith(f"{bank}-")
    assert is_utc_iso(fx["received_at"])
    # Fake-data rule: pseudonym tokens in fixtures start at 900.
    assert all(int(n) >= 900 for n in re.findall(r"(?:PERSON|PARTY)_(\d+)", fx["body"]))

    exp = fx["expected"]
    assert exp["type"] in TYPES
    if exp["type"] == "foreign_currency":
        assert exp == {"type": "foreign_currency"}
        return
    assert set(exp) == FIELDS
    for key in ("amount_paise", "balance_paise"):
        assert exp[key] is None or (isinstance(exp[key], int) and exp[key] >= 0)
    assert exp["direction"] in {"debit", "credit", None}
    assert exp["channel"] in CHANNELS | {None}
    assert exp["account_last4"] is None or re.fullmatch(r"\d{4}", exp["account_last4"])
    assert exp["txn_time_utc"] is None or is_utc_iso(exp["txn_time_utc"])
    for key in ("account_last4", "counterparty_raw", "reference"):
        assert exp[key] is None or exp[key] in fx["body"], key
