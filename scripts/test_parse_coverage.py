"""Tests for parse_coverage.py. Synthetic messages only."""

import json
import re
from pathlib import Path

import parse_coverage as pc

MESSAGES = [
    {
        "sender": "HDFCBK",
        "date_utc": "2026-01-05T06:30:00+00:00",
        "body": "Sent Rs.33.00\nFrom HDFC Bank A/C *0001\nTo TEST SECRET STORE\nOn 05/01/26\n"
        "Ref 000000000001\nNot You?\nCall 18000000001/SMS BLOCK UPI to 9000000001\n",
    },
    {
        "sender": "HDFCBN",
        "date_utc": "2026-01-05T07:00:00+00:00",
        "body": "Paid Rs.44\nTo TEST SECRET STORE\nOn 05/01/26\nRef 000000000009",
    },
    # A known sender no parser reads (an app; banks without a parser have the generic one).
    {"sender": "PHONPE", "date_utc": "2026-01-05T08:00:00+00:00", "body": "Rs 77 debited"},
]


def test_coverage_prints_counts_and_unknown_shapes_only(tmp_path: Path, capsys) -> None:
    src = tmp_path / "sample.json"
    src.write_text(json.dumps(MESSAGES), encoding="utf-8")
    assert pc.main(["--input", str(src)]) == 0
    out = capsys.readouterr().out

    assert "Messages: 3  parsed: 1  is_money: 1" in out
    assert re.search(r"HDFC H01\s+1", out)
    assert re.search(r"no_template\s+1", out) and re.search(r"no_parser_for_bank\s+1", out)
    # The unknown HDFC message appears only as its shape; values never print.
    assert "Paid {AMOUNT}" in out and "To {PARTY}" in out and "Ref {REF}" in out
    for value in ("SECRET", "Rs.44", "000000000009", "Rs 77"):
        assert value not in out
