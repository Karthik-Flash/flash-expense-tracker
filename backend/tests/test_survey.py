"""bank-survey, generic-preview and redact-sample (D-100, D-101). FAKE messages only; every
file goes to a temp folder."""

import importlib.util
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.engine.parsers import GENERIC_BANKS
from app.engine.senders import bank_for
from app.models import ParseResult, RawMessage
from app.pipeline import sample_export
from tests.smsdata import NEVER_STORED, hdfc_rows, write_backup

REPO = Path(__file__).resolve().parents[2]
DOC = json.loads((Path(__file__).parent / "fixtures" / "generic_sms.json").read_text("utf-8"))
ROWS = [
    (f["sender"], f["body"], datetime.fromisoformat(f["received_at"]))
    for f in DOC["accepted"] + DOC["rejected"]
]


def stored_cores(db_engine) -> Counter:
    """Stored messages per family (the import never stores an OTP)."""
    with sessionmaker(db_engine)() as s:
        return Counter(bank_for(c) or c for c in s.scalars(select(RawMessage.sender_core)))


@pytest.fixture
def stored(run, tmp_path):
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", ROWS + hdfc_rows())))
    return tmp_path


def test_shape_rules_are_the_phase_1_rules() -> None:
    spec = importlib.util.spec_from_file_location(
        "shape_survey", REPO / "scripts" / "shape_survey.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert [(p, rx.pattern, rx.flags) for p, rx in sample_export.RULES] == [
        (p, rx.pattern, rx.flags) for p, rx in module.RULES
    ]
    for _, body, _ in ROWS:
        assert sample_export.shape_of(body) == module.shape_of(body)


def test_bank_survey_counts_by_family_kind_and_status(run, stored, db_engine) -> None:
    out = run("bank-survey")
    for family, n in stored_cores(db_engine).items():
        assert re.search(rf"^{family}  \({n} messages, \d+ foreign currency\)$", out, re.M)
    assert re.search(r"^HDFC  \(\d+ messages, \d+ foreign currency\)$", out, re.M)
    # Every kind row has three counts: dedicated, generic, not parsed.
    rows = re.findall(r"^  ([a-z_]+)\s+(\d+)\s+(\d+)\s+(\d+)$", out, re.M)
    assert rows and {k for k, *_ in rows} <= set(
        "debit credit card atm balance otp promo bill_due request other".split()
    )
    hdfc_block = out.split("HDFC  (")[1].split("\n\n")[0]
    assert "generic" not in hdfc_block.split("\n")[0]
    assert all(c.isdigit() or c in " \n()_,:/abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-"
               for c in out)  # fmt: skip
    for _, body, _ in ROWS[:5]:
        assert body not in out


def test_generic_preview_counts_without_writing(run, stored, db_engine) -> None:
    with sessionmaker(db_engine)() as s:
        before = s.scalar(select(func.count()).select_from(ParseResult))
    out = run("generic-preview")
    with sessionmaker(db_engine)() as s:
        assert s.scalar(select(func.count()).select_from(ParseResult)) == before
    accepted = sum(int(n) for n in re.findall(r"^  accepted: \w+\s+(\d+)$", out, re.M))
    refused = sum(int(n) for n in re.findall(r"^  (?:refused|unsure): \w+\s+(\d+)$", out, re.M))
    foreign = sum(int(n) for n in re.findall(r"^  foreign currency: kept out\s+(\d+)$", out, re.M))
    generic_stored = sum(n for f, n in stored_cores(db_engine).items() if f in GENERIC_BANKS)
    assert accepted == len(DOC["accepted"])
    assert accepted + refused + foreign == generic_stored
    assert "HDFC" not in out


def test_redact_sample_writes_only_shapes_then_approve_copies(run, stored, monkeypatch) -> None:
    review, sample = stored / "review", stored / "sample"
    monkeypatch.setattr(sample_export, "SAMPLE_DIR", sample)
    out = run("redact-sample", "--family", "icici", "--review-dir", str(review))
    assert "written to the review folder: icici-sample.txt" in out
    text = (review / "icici-sample.txt").read_text("utf-8")
    vocab = (review / "icici-vocabulary.txt").read_text("utf-8")
    assert text.startswith("# ICICI sample: ") and "## 1 | " in text
    assert not re.search(r"\d{4}", re.sub(r"\{[A-Z]+\}", "", text.split("\n", 1)[1]))
    assert "@" not in text
    for word in ("TEST", "DEMO", "RAVI", "MEERA", "TESTMART", "KIRAN", "ANITA"):
        assert word not in text and word.lower() not in vocab.split()
    assert sample_export.leak_scan(text) == (Counter(), [])
    assert "words replaced by {WORD}:" in vocab

    assert "approved: leak scan clean" in run(
        "redact-sample", "--approve", "ICICI", "--review-dir", str(review)
    )
    assert (sample / "icici-sample.txt").read_text("utf-8") == text


def test_a_deliberate_leak_is_refused_and_nothing_is_copied(run, stored, monkeypatch) -> None:
    review, sample = stored / "review", stored / "sample"
    monkeypatch.setattr(sample_export, "SAMPLE_DIR", sample)
    run("redact-sample", "--family", "ICICI", "--review-dir", str(review))
    path = review / "icici-sample.txt"
    path.write_text(path.read_text("utf-8") + "Paid to Test Ravi 98765 via testravi@okaxis\n")
    out = run("redact-sample", "--approve", "ICICI", "--review-dir", str(review), code=1)
    assert "refused: the leak scan found lines" in out
    counts = dict(re.findall(r"^  (4\+ digits|@ handle|capitalised word)\s+(\d+)$", out, re.M))
    assert counts == {"4+ digits": "1", "@ handle": "1", "capitalised word": "1"}
    assert "Ravi" not in out  # PRIVATE detail only on a terminal
    assert not sample.exists()


def test_the_scan_and_the_folder_rules() -> None:
    reasons, lines = sample_export.leak_scan("## 1 | 2 messages | kind debit | generic\nTo Kiran")
    assert reasons == Counter({"capitalised word": 1}) and lines == ["To Kiran"]
    assert sample_export.leak_scan("# made by hand\nDear {WORD}")[0] == Counter(
        {"capitalised word": 1}
    )
    assert sample_export.inside_repo(REPO / "data" / "x")
    kept: Counter = Counter()
    text, replaced = sample_export.redact("Rs 500 paid to zorblax quentin from A/c XX1234", kept)
    assert text == "{AMOUNT} paid to {WORD} {WORD} from A/c {ACCT}" and replaced == 2
    assert kept == Counter({"paid": 1, "to": 1, "from": 1, "a": 1, "c": 1})


def test_review_folder_inside_the_repo_is_refused(run, stored) -> None:
    out = run("redact-sample", "--family", "ICICI", "--review-dir", str(REPO / "data"), code=2)
    assert "must be outside the repository" in out


def test_never_stored_rows_never_reach_a_sample(run, tmp_path) -> None:
    run("import-sms", "--input", str(write_backup(tmp_path / "n.xml", NEVER_STORED)))
    out = run("redact-sample", "--family", "HDFC", "--review-dir", str(tmp_path / "r"), code=2)
    assert "nothing to write" in out


def test_unparsed_hdfc_messages_only(run, tmp_path, monkeypatch) -> None:
    """4Z: --unparsed exports only the HDFC messages no parser read, as HDFC-UNPARSED."""
    body = "TEST NEW SHAPE: Rs.700.00 paid to TEST PERSON via TEST APP on 01-01-26"
    unread = ("VM-HDFCBK-S", body)
    rows = [
        *hdfc_rows(),
        (unread[0], unread[1], datetime.fromisoformat("2026-01-01T06:00:00+00:00")),
    ]
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", rows)))
    review, sample = tmp_path / "review", tmp_path / "sample"
    monkeypatch.setattr(sample_export, "SAMPLE_DIR", sample)
    out = run("redact-sample", "--family", "HDFC", "--unparsed", "--review-dir", str(review))
    unread_stored = sum(1 for _, b, _ in rows if b) - int(
        re.search(r"^messages\s+(\d+)$", out, re.M).group(1)
    )
    assert unread_stored > 0  # the parsed fixtures are left out
    text = (review / "hdfc-unparsed-sample.txt").read_text("utf-8")
    assert text.startswith("# HDFC sample, unread messages only: ") and "TEST" not in text
    assert "NEW SHAPE" not in text and "{WORD}" in text
    assert "approved" in run("redact-sample", "--approve", "HDFC-UNPARSED", "--review-dir",
                             str(review))  # fmt: skip
    assert (sample / "hdfc-unparsed-sample.txt").exists()
    assert "--unparsed goes with --family" in run("redact-sample", "--approve", "HDFC",
                                                  "--unparsed", code=2)  # fmt: skip
