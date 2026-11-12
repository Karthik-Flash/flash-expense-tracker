"""Tests for redact_sms.py. Synthetic messages only; never real data."""

import json
import re
import tracemalloc
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pytest
import redact_sms as r

SENDERS = {"HDFCBK", "ICICIT", "AXISBK", "SBIUPI", "PAYTM"}


@pytest.fixture
def redactor(tmp_path: Path) -> r.Redactor:
    return r.Redactor(tmp_path / "private")


def write_backup(path: Path, rows: list[tuple[str, str]], mms: int = 0) -> Path:
    """Write a minimal SMS Backup & Restore file. Bodies may contain raw char refs."""
    with path.open("w", encoding="utf-8") as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<smses count="{len(rows)}">\n')
        for i, (address, body) in enumerate(rows):
            body_attr = quoteattr(body).replace("&amp;#", "&#")  # keep test char refs raw
            f.write(f'<sms address="{address}" date="{1762300000000 + i}" body={body_attr} />\n')
        for _ in range(mms):
            f.write('<mms date="1762300000000"><parts><part data="' + "QUFB" * 5000)
            f.write('" /></parts><addrs><addr address="+919876543210" /></addrs></mms>\n')
        f.write("</smses>\n")
    return path


# --- Masking ------------------------------------------------------------------
def test_masks_ids_and_keeps_amounts_dates_merchant(redactor: r.Redactor) -> None:
    out = redactor.redact(
        "Rs.1,250.00 debited from A/c no. 50100123456789 on 03-11-26 to SWIGGY via UPI "
        "card 4111 1111 1111 1234. VPA rahul.k@okhdfcbank. Mail me@example.com. "
        "Call +91 9876543210"
    )
    assert "Rs.1,250.00" in out and "03-11-26" in out and "SWIGGY" in out
    assert "A/c no. XXXXXXXXXX6789" in out
    assert "card XXXX XXXX XXXX 1234" in out
    assert "xxxx@okhdfcbank" in out and "rahul" not in out
    assert "xxxx@example.com" in out
    assert "9876543210" not in out


def test_already_masked_account_is_unchanged(redactor: r.Redactor) -> None:
    assert redactor.redact("A/c XX1234 credited") == "A/c XX1234 credited"


def test_otp_detection_keeps_alerts_with_share_warning() -> None:
    assert r.is_otp("123456 is your OTP for txn of Rs 500 at AMAZON")
    assert r.is_otp("Your one-time password is 4321")
    assert not r.is_otp("Rs 500 debited from A/c XX1234. Never share your OTP with anyone.")


# --- Senders ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("VM-HDFCBK", ("HDFCBK", "")),
        ("AD-HDFCBK-S", ("HDFCBK", "S")),
        ("JD-ICICIT-T", ("ICICIT", "T")),
        ("VK-SBIUPI-P", ("SBIUPI", "P")),
        ("HDFCBK", ("HDFCBK", "")),
        ("+919876543210", ("+919876543210", "")),
    ],
)
def test_parse_sender(address: str, expected: tuple[str, str]) -> None:
    assert r.parse_sender(address) == expected


# --- References ---------------------------------------------------------------
def test_refs_get_stable_fakes_of_same_shape(tmp_path: Path) -> None:
    first = r.Redactor(tmp_path)
    a = first.redact("Sent Rs.50 Ref 612345678901 via UPI")
    b = first.redact("ICICI Bank Acct XX123 debited; UPI:612345678901.")
    c = first.redact("NEFT credit UTR No. SBIN326317123456 to A/c XX1234")
    fake = re.search(r"Ref (\d{12})", a).group(1)

    assert fake != "612345678901" and len(fake) == 12
    assert f"UPI:{fake}" in b  # same real ref, same fake: dedupe stays testable
    utr = re.search(r"UTR No\. (\S+)", c).group(1)
    assert utr.startswith("SBIN") and len(utr) == 16 and utr != "SBIN326317123456"

    first.save()
    again = r.Redactor(tmp_path).redact("Ref 612345678901")
    assert again == f"Ref {fake}"  # stable across runs via ref_map.json


# --- Names --------------------------------------------------------------------
def test_p2p_names_get_consistent_tokens(redactor: r.Redactor) -> None:
    hdfc = (
        "Sent Rs.500.00\nFrom HDFC Bank A/C *1234\nTo RAHUL KUMAR\nOn 12/11/26\n"
        "Ref 612345678901\nNot You?\nCall 18002586161/SMS BLOCK UPI to 7308080808"
    )
    icici = "ICICI Bank Acct XX123 debited for Rs 500.00 on 12-Nov-26; Rahul Kumar credited."
    axis = "INR 200.00 debited A/c no. XX1234 UPI/P2A/612345678903/PRIYA S Not you?"
    imps = "Rs 900 credited to a/c XX1234 by IMPS from Mr. ANIL VERMA. Ref 612345678904"
    merchant = "Rs 250 debited from A/c XX1234 to SWIGGY via UPI. UPI/P2M/612345678905/ZOMATO LTD"

    out = [redactor.redact(m) for m in (hdfc, icici, axis, imps, merchant)]

    assert "To PERSON_001\nOn" in out[0]
    assert "; PERSON_001 credited" in out[1]
    assert "/PERSON_002 Not you?" in out[2]
    assert "from Mr. PERSON_003." in out[3]
    assert "SWIGGY" in out[4] and "ZOMATO LTD" in out[4]
    joined = " ".join(out).upper()
    assert all(n not in joined for n in ("RAHUL", "KUMAR", "PRIYA", "ANIL", "VERMA"))
    assert "HDFC Bank" in out[0]


def test_greeting_name_is_pseudonymised_but_customer_is_not(redactor: r.Redactor) -> None:
    assert redactor.redact("Dear Customer, Rs 5 debited") == "Dear Customer, Rs 5 debited"
    assert redactor.redact("Dear Rahul, Rs 5 debited") == "Dear PERSON_001, Rs 5 debited"


def test_name_map_is_reused_and_override_keeps_merchant(tmp_path: Path) -> None:
    first = r.Redactor(tmp_path)
    first.redact("Rs 100 sent via UPI to CHAI POINT on 12-11-26")
    first.redact("Rs 100 sent via UPI to RAHUL on 12-11-26")
    first.save()
    names = json.loads((tmp_path / "name_map.json").read_text(encoding="utf-8"))
    assert names == {"CHAI POINT": "PERSON_001", "RAHUL": "PERSON_002"}

    names["CHAI POINT"] = "CHAI POINT"  # user marks it as a merchant
    (tmp_path / "name_map.json").write_text(json.dumps(names), encoding="utf-8")
    second = r.Redactor(tmp_path)
    assert "to CHAI POINT on" in second.redact("Rs 9 sent via UPI to CHAI POINT on 13-11-26")
    assert second.redact("Rs 9 sent via UPI to Asha on 13-11-26").count("PERSON_003") == 1


# --- Streaming / end to end ---------------------------------------------------
def test_invalid_char_refs_do_not_break_parsing(tmp_path: Path) -> None:
    xml = write_backup(tmp_path / "emoji.xml", [("VM-HDFCBK", "Paid Rs 5 &#55357;&#56832; &#1;")])
    [(tag, sms)] = list(r.iter_files([xml]))
    assert tag == "sms" and sms["body"] == "Paid Rs 5 \ufffd\ufffd \ufffd"


def test_char_ref_split_across_chunks_is_fixed() -> None:
    class Chunks:
        def __init__(self, parts: list[bytes]) -> None:
            self.parts = parts

        def read(self, n: int) -> bytes:
            return self.parts.pop(0) if self.parts else b""

    cleaner = r.CharRefCleaner(Chunks([b"<a>x &#553", b"57; y</a>"]))
    data = b"".join(iter(lambda: cleaner.read(64), b""))
    assert data == b"<a>x &#65533; y</a>"


def test_streams_20k_messages_with_flat_memory(tmp_path: Path, capsys) -> None:
    rows = []
    for i in range(20_000):
        if i % 4 == 0:
            rows.append(
                ("VM-HDFCBK-S", f"Rs {i} sent via UPI to RAHUL KUMAR Ref {612000000000 + i}")
            )
        elif i % 4 == 1:
            rows.append(("AD-SBIUPI-P", "Get a pre-approved loan today!"))
        elif i % 4 == 2:
            rows.append(("JD-ICICIT-T", f"{100000 + i} is your OTP. Do not share."))
        else:
            rows.append(("+919876543210", "hey, call me back"))
    xml = write_backup(tmp_path / "big.xml", rows, mms=20)

    tracemalloc.start()
    n = sum(1 for _ in r.iter_files([xml]))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert n == 20_020
    # Measured on this file: streaming ~0.1x file size, iterparse without
    # root.clear() ~0.7x, ET.parse ~4x. So /4 fails both non-streaming versions.
    assert peak < xml.stat().st_size / 4

    out = tmp_path / "out.json"
    args = [str(xml), "-o", str(out), "--private-dir", str(tmp_path / "p")]
    assert r.main([*args, "--senders", ",".join(SENDERS), "--limit", "50"]) == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == 50 and {m["sender"] for m in data} == {"HDFCBK"}
    text = json.dumps(data)
    assert "RAHUL" not in text and "PERSON_001" in text
    assert "612000000000" not in text
    summary = capsys.readouterr().out
    assert "Kept 5,000" in summary
    assert re.search(r"promotional \(-P\)\s+5,000", summary)
    assert re.search(r"otp\s+5,000", summary)
    assert re.search(r"sender not allowlisted\s+5,000", summary)
    assert re.search(r"mms \(skipped\)\s+20", summary)


def test_list_senders_prints_counts_but_no_bodies_or_numbers(tmp_path: Path, capsys) -> None:
    xml = write_backup(
        tmp_path / "s.xml",
        [
            ("VM-HDFCBK", "secret body one"),
            ("AD-HDFCBK-P", "secret body two"),
            ("JD-NEWBNK-T", "secret body three"),
            ("+919876543210", "secret body four"),
        ],
    )
    assert r.main([str(xml), "--list-senders", "--senders", "HDFCBK"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"HDFCBK\s+2\s+1\s+yes", out)
    assert re.search(r"NEWBNK\s+1\s+0", out)
    assert "secret" not in out and "9876543210" not in out
    assert "1 messages from 1 numbers" in out
