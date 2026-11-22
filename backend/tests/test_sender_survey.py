"""sender-survey (5C): sender codes holding a text, stored and skipped as unregistered_sender,
counts only. FAKE messages; the skipped ones come from the backup file."""

import re
from datetime import UTC, datetime

from tests.smsdata import write_backup

WHEN = datetime(2026, 1, 20, 6, 30, tzinfo=UTC)
SENT = "Sent Rs.33.00\nFrom HDFC Bank A/C *0001\nTo TEST SHOP\nOn 20/01/26\nRef 000000000033"
CREDIT = "Rs.44.00 credited to a/c XX0001 by TEST PERSON"


def test_counts_per_code_stored_and_skipped_and_never_a_body(run, tmp_path) -> None:
    rows = [
        ("VM-HDFCBK-S", SENT, WHEN),  # registered: stored
        ("JD-HDFCUP-T", SENT, WHEN),  # an unregistered code: skipped by import-sms
        ("AX-HDFCUP-S", CREDIT, WHEN),
        ("VK-HDFCLF-P", "TEST OFFER: a loan for you", WHEN),  # promotional, still unregistered
        ("+919000000001", "HDFC is my bank: TEST", WHEN),  # a person: never a code
    ]
    backup = write_backup(tmp_path / "s.xml", rows)
    run("import-sms", "--input", str(backup))
    out = run("sender-survey", "--contains", "hdfc", "--input", str(backup))
    lines = {line.split()[0]: line.split()[1:] for line in out.splitlines()[2:] if line.strip()}
    assert lines["HDFCBK"] == ["yes", "1", "0", "1", "0", "0"]
    assert lines["HDFCUP"] == ["NO", "0", "2", "1", "1", "0"]
    assert lines["HDFCLF"] == ["NO", "0", "1", "0", "0", "1"]
    assert "919000000001" not in out and "TEST" not in out and "33" not in out
    stored_only = run("sender-survey", "--contains", "HDFC")
    assert re.search(r"HDFCBK\s+yes\s+1\s+0", stored_only) and "HDFCUP" not in stored_only
