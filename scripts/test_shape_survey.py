"""Tests for shape_survey.py. Synthetic messages only."""

import json
from pathlib import Path

import pytest
import shape_survey as s

RUPEE = chr(0x20B9)


@pytest.mark.parametrize(
    ("body", "shape"),
    [
        (
            "Sent Rs.1,00,000.00\nFrom HDFC Bank A/C *0001\nTo TEST MERCHANT 2\nOn 01/01/26\n"
            "Ref 000000000001\nNot You?\nCall XXXXXXX0000/SMS BLOCK UPI to 9000000001\n",
            "Sent {AMOUNT}\nFrom HDFC Bank A/C {ACCT}\nTo {PARTY}\nOn {DATE}\nRef {REF}\n"
            "Not You?\nCall {PHONE}/SMS BLOCK UPI to {PHONE}",
        ),
        (
            "Credit Alert!\nINR 555 credited to HDFC Bank A/c XX0001 on 01-01-26 "
            "from VPA test.user@okaxis (UPI 000000000002)\n",
            "Credit Alert!\n{AMOUNT} credited to HDFC Bank A/c {ACCT} on {DATE} "
            "from VPA {VPA} (UPI {REF})",
        ),
        (
            f"Spent {RUPEE}222 From PERSON_900 At TEST STORE On 2026-01-01:10:00:00 "
            "Bal Rs.1000.50 Not You? Call XXXXXXX0000/SMS BLOCK DC 0002 to 9000000001",
            "Spent {AMOUNT} From {PARTY} At {PARTY} On {DATE}:{TIME} Bal {BAL} Not You? "
            "Call {PHONE}/SMS BLOCK DC {ACCT} to {PHONE}",
        ),
        (
            "Card xx0002 used for USD 12.50 at TEST STORE on 01-JAN-2026. Ref No 000000000003. "
            "Visit https://example.com/x",
            "Card {ACCT} used for {CURRENCY} {AMOUNT} at TEST STORE on {DATE}. Ref No {REF}. "
            "Visit {URL}",
        ),
        ("Your code expires in 5 minutes", "Your code expires in {NUM} minutes"),
    ],
)
def test_shape_of(body: str, shape: str) -> None:
    assert s.shape_of(body) == shape


def test_survey_groups_by_shape_and_filters_senders(tmp_path: Path, capsys) -> None:
    msgs = [
        {"sender": "BANKAA", "body": "Sent Rs.33\nTo PERSON_900\nOn 01/01/26"},
        {"sender": "BANKAB", "body": "Sent Rs.2,500.00\nTo TEST MERCHANT\nOn 02/01/26"},
        {"sender": "BANKAA", "body": "Credit Alert! Rs.5 on 03-01-26"},
        {"sender": "OTHERS", "body": "Sent Rs.99\nTo PERSON_901\nOn 04/01/26"},
    ]
    src = tmp_path / "in.json"
    src.write_text(json.dumps(msgs), encoding="utf-8")
    out = tmp_path / "report.json"

    assert s.main(["--input", str(src), "--senders", "BANKAA,BANKAB", "--output", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert [r["count"] for r in report] == [2, 1]
    assert report[0]["shape"] == "Sent {AMOUNT}\nTo {PARTY}\nOn {DATE}"
    assert report[0]["senders"] == ["BANKAA", "BANKAB"]
    assert report[0]["id"] == s.shape_id(report[0]["shape"])
    assert "3 messages, 2 shapes" in capsys.readouterr().out
