"""Tests for redact_sms.py using synthetic messages only (never real data)."""

import json

import redact_sms as r

SENDERS = {"HDFCBK", "SBIUPI", "PAYTM"}


def test_masks_account_card_upi_phone_and_keeps_amounts_dates_merchant() -> None:
    body = (
        "Rs.1,250.00 debited from A/c no. 50100123456789 on 03-11-26 to SWIGGY "
        "via card 4111 1111 1111 1234. UPI ref 612345678901. VPA rahul.k@okhdfcbank. "
        "Call +91 9876543210"
    )
    out = r.redact(body)

    assert "Rs.1,250.00" in out
    assert "03-11-26" in out
    assert "SWIGGY" in out
    assert "A/c no. XXXXXXXXXX6789" in out
    assert "card XXXX XXXX XXXX 1234" in out
    assert "ref XXXXXXXX8901" in out
    assert "xxxx@okhdfcbank" in out and "rahul" not in out
    assert "9876543210" not in out


def test_already_masked_account_is_unchanged() -> None:
    assert r.redact("A/c XX1234 credited") == "A/c XX1234 credited"


def test_otp_detection_keeps_alerts_with_share_warning() -> None:
    assert r.is_otp("123456 is your OTP for txn of Rs 500 at AMAZON")
    assert r.is_otp("Your one-time password is 4321")
    assert not r.is_otp("Rs 500 debited from A/c XX1234. Never share your OTP with anyone.")


def test_sender_matching() -> None:
    assert r.match_sender("VM-HDFCBK", SENDERS) == "HDFCBK"
    assert r.match_sender("AD-SBIUPI-S", SENDERS) == "SBIUPI"
    assert r.match_sender("JD-AMAZON", SENDERS) is None
    assert r.match_sender("+919876543210", SENDERS) is None


def test_end_to_end_with_limit(tmp_path) -> None:
    xml = tmp_path / "sms.xml"
    rows = [
        ("VM-HDFCBK", "Rs 100 debited from A/c XX1234 to ZOMATO"),
        ("VM-HDFCBK", "Rs 200 debited from A/c XX1234 to UBER"),
        ("VM-HDFCBK", "987654 is your OTP. Do not share."),
        ("AD-PAYTM-S", "Paid Rs 50 to CHAI POINT"),
        ("+919876543210", "hey call me"),
    ]
    items = "".join(
        f'<sms address="{a}" date="{1762300000000 + i}" body="{b}" type="1" />'
        for i, (a, b) in enumerate(rows)
    )
    xml.write_text(f'<?xml version="1.0"?><smses count="{len(rows)}">{items}</smses>')
    out = tmp_path / "out.json"

    assert r.main([str(xml), "-o", str(out), "--senders", "HDFCBK,PAYTM", "--limit", "1"]) == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    assert sorted(m["sender"] for m in data) == ["HDFCBK", "PAYTM"]
    assert all("OTP" not in m["body"] for m in data)
    assert data[0]["date_utc"].endswith("+00:00")
