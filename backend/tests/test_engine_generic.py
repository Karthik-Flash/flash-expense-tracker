"""The generic parser for banks with no dedicated parser (D-101). FAKE fixtures only:
tests/fixtures/generic_sms.json (expectations from the values put in, not from the parser)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import engine
from app.engine import ParsedMessage, Unknown, parse_message
from app.engine.parsers import GENERIC_BANKS, PARSERS, generic
from app.engine.senders import bank_for, parse_sender
from app.models import ParseResult, Transaction, TransactionSource
from app.pipeline.dedupe import transaction_key
from tests.smsdata import hdfc_rows, write_backup

DOC = json.loads((Path(__file__).parent / "fixtures" / "generic_sms.json").read_text("utf-8"))
ACCEPTED, REJECTED = DOC["accepted"], DOC["rejected"]
SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample" / "redacted_sample.json"


def parse(fx: dict):
    return parse_message(fx["sender"], fx["body"], datetime.fromisoformat(fx["received_at"]))


def value(result: ParsedMessage, name: str):
    v = getattr(result, name)
    if isinstance(v, datetime):
        return v.isoformat().replace("+00:00", "Z")
    return list(v) if isinstance(v, tuple) else v


def test_fixture_counts() -> None:
    assert len(ACCEPTED) >= 80 and len(REJECTED) >= 40
    assert len({f["id"] for f in ACCEPTED + REJECTED}) == len(ACCEPTED) + len(REJECTED)
    assert all(bank_for(parse_sender(f["sender"])[0]) in GENERIC_BANKS for f in ACCEPTED)


@pytest.mark.parametrize("fx", ACCEPTED, ids=[f["id"] for f in ACCEPTED])
def test_accepted(fx: dict) -> None:
    result = parse(fx)
    assert isinstance(result, ParsedMessage), result
    assert result.parser_version == generic.GENERIC_VERSION and result.template_id == "GEN"
    assert result.bank == bank_for(parse_sender(fx["sender"])[0]) and result.currency == "INR"
    got = {name: value(result, name) for name in fx["expect"]}
    assert got == fx["expect"]
    assert result.type in ("debit", "credit")  # never a refund: a guess never lowers Net


@pytest.mark.parametrize("fx", REJECTED, ids=[f["id"] for f in REJECTED])
def test_rejected(fx: dict) -> None:
    result = parse(fx)
    assert isinstance(result, Unknown), result
    expect = fx["expect"]
    assert result.reason == expect["unknown"]
    assert result.detail == expect.get("detail")
    if result.reason == "not_a_transaction":
        assert result.detail in generic.REJECTS
    if result.reason == "generic_unsure":
        assert result.detail in generic.UNSURE


def test_every_reason_has_a_fixture() -> None:
    seen = {f["expect"].get("detail") for f in REJECTED}
    assert set(generic.REJECTS) | set(generic.UNSURE) <= seen


def test_kinds_for_the_survey() -> None:
    for fx in ACCEPTED:
        kind = generic.kind_of(fx["body"])
        if fx["expect"]["direction"] == "credit":
            assert kind == "credit", fx["id"]
        else:
            assert kind in ("debit", "card", "atm"), fx["id"]
            assert (kind == "atm") == (fx["expect"]["channel"] == "atm"), fx["id"]
    wanted = {"otp": "otp", "request": "request", "promo": "promo", "balance_only": "balance",
              "card_bill_due": "bill_due", "scheduled": "bill_due", "mandate_notice": "bill_due",
              "other": "other"}  # fmt: skip
    for fx in REJECTED:
        if (detail := fx["expect"].get("detail")) in wanted:
            assert generic.kind_of(fx["body"]) == wanted[detail], fx["id"]
    assert set(wanted.values()) | {"debit", "credit", "card", "atm"} == set(generic.KINDS)


def test_only_banks_without_a_parser_and_never_an_app() -> None:
    assert "HDFC" in PARSERS and "HDFC" not in GENERIC_BANKS and "PHONEPE" not in GENERIC_BANKS
    body = ACCEPTED[1]["body"]
    when = datetime(2026, 3, 10, tzinfo=UTC)
    assert parse_message("VM-PHONPE", body, when) == Unknown("no_parser_for_bank", "PHONEPE")
    assert parse_message("AB-TESTCO", body, when) == Unknown("unknown_sender")
    with pytest.raises(ValueError):
        generic.parse("SBI", body, datetime(2026, 3, 10))  # naive time: a caller bug


def test_hdfc_results_do_not_change(monkeypatch) -> None:
    """HDFC never reaches the generic parser; every HDFC fixture (and the redacted sample,
    when it is on this machine) gives exactly the dedicated parser's result."""
    rows = hdfc_rows()
    if SAMPLE.exists():
        sample = json.loads(SAMPLE.read_text("utf-8"))
        rows += [
            (m["sender"], m["body"], datetime.fromisoformat(m["date_utc"].replace("Z", "+00:00")))
            for m in sample
            if bank_for(parse_sender(m["sender"])[0]) == "HDFC"
        ]

    def never(*_):
        raise AssertionError("the generic parser ran on an HDFC message")

    monkeypatch.setattr(generic, "parse", never)
    for sender, body, when in rows:
        assert parse_message(sender, body, when) == PARSERS["HDFC"].parse(body, when)


def test_same_alert_twice_is_one_key_and_two_references_are_two() -> None:
    fx = next(f for f in ACCEPTED if f["id"].endswith("debit-card"))  # time in the text
    a = parse(fx)
    later = datetime.fromisoformat(fx["received_at"]).replace(minute=59)
    b = parse_message(fx["sender"], fx["body"], later)
    assert a.reference is None and a == b
    assert transaction_key(a, "raw-1") == transaction_key(b, "raw-2")  # one payment
    other_minute = fx["body"].replace(f"{a.txn_time_utc.astimezone(generic.IST):%H:%M}", "00:01")
    c = parse_message(fx["sender"], other_minute, datetime.fromisoformat(fx["received_at"]))
    assert transaction_key(c, "raw-3") != transaction_key(a, "raw-1")
    ref = next(f for f in ACCEPTED if f["id"].endswith("UPI-vpa"))
    one = parse(ref)
    two = parse_message(ref["sender"], ref["body"].replace(one.reference, "599999999999"),
                        datetime.fromisoformat(ref["received_at"]))  # fmt: skip
    assert transaction_key(one, "r") != transaction_key(two, "r")  # D-069


def _sbi_rows():
    """Six SBI alerts that are six different payments (each with its own reference)."""
    picks, seen = [], set()
    for f in ACCEPTED:
        e = f["expect"]
        key = (e["direction"], e["amount_paise"], e.get("reference"))
        if f["sender"].endswith(("SBIINB", "SBIUPI", "CBSSBI")) and key[2] and key not in seen:
            seen.add(key)
            picks.append((f["sender"], f["body"], datetime.fromisoformat(f["received_at"])))
    return picks[:6]


def test_first_parse_and_a_reparse_keep_transaction_ids(run, db_engine, tmp_path, monkeypatch):
    """Before the generic parser: no_parser_for_bank. After it: a reparse makes the
    transactions. A later generic version reparses them in place: the ids stay."""
    rows = _sbi_rows()
    monkeypatch.setattr(engine, "GENERIC_BANKS", frozenset())
    monkeypatch.setattr(engine.parsers, "GENERIC_BANKS", frozenset())
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", rows)))
    factory = sessionmaker(db_engine)
    with factory() as s:
        assert not s.scalars(select(Transaction)).all()
    monkeypatch.undo()

    run("reparse")
    with factory() as s:
        first = sorted((t.id, t.dedupe_key, t.amount_paise) for t in s.scalars(select(Transaction)))
    assert len(first) == len(rows)

    monkeypatch.setattr(generic, "GENERIC_VERSION", "generic-1.0.1")
    assert "reparsed                         " in run("reparse")
    with factory() as s:
        again = sorted((t.id, t.dedupe_key, t.amount_paise) for t in s.scalars(select(Transaction)))
        versions = set(s.scalars(select(ParseResult.parser_version).where(ParseResult.is_current)))
        links = s.scalars(select(TransactionSource.transaction_id)).all()
    assert again == first and versions == {"generic-1.0.1"}
    assert sorted(links) == [i for i, _, _ in first]
