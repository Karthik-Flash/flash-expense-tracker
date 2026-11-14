"""Import pipeline invariants I1-I8 (docs/data-model.md). Synthetic data only."""

import dataclasses
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, aliased, sessionmaker

import app.importers.sms_backup as sms_backup
from app.config import settings
from app.db import Base
from app.engine import MONEY_TYPES
from app.engine.parsers import PARSERS
from app.engine.parsers.hdfc import PARSER as HDFC
from app.importers.sms_backup import import_sms
from app.models import (
    DuplicateCandidate,
    ImportBatch,
    ParseResult,
    RawMessage,
    Transaction,
    TransactionSource,
)
from app.pipeline.reparse import reparse
from tests.smsdata import NEVER_STORED, SBI_ROW, WHEN, full_rows, hdfc_rows, write_backup

OWNER = settings.owner_id
ALL_TABLES = (ImportBatch, RawMessage, ParseResult, Transaction, TransactionSource)


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
def backup(tmp_path: Path) -> Path:
    return write_backup(tmp_path / "backup.xml", full_rows(), mms=2)


def run_import(factory: sessionmaker, path: Path, **kwargs):
    with factory() as session:
        return import_sms(session, path, OWNER, **kwargs)


def run_reparse(factory: sessionmaker, **kwargs):
    with factory() as session:
        return reparse(session, OWNER, **kwargs)


def count(factory: sessionmaker, model, *where) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(model).where(*where))


def snapshot(factory: sessionmaker) -> dict:
    """Database content without ids, batch links or timestamps (they differ per run)."""
    with factory() as s:
        raw_hash = {r.id: r.content_hash for r in s.scalars(select(RawMessage))}
        txn_key = {t.id: t.dedupe_key for t in s.scalars(select(Transaction))}
        version = {p.id: p.parser_version for p in s.scalars(select(ParseResult))}
        return {
            "raw": sorted(
                (r.content_hash, r.source, r.sender_core, r.body, r.received_at)
                for r in s.scalars(select(RawMessage))
            ),
            "parse": sorted(
                (
                    raw_hash[p.raw_message_id],
                    p.parser_version,
                    p.status,
                    p.is_current,
                    p.unknown_reason or "",
                    p.type or "",
                    p.amount_paise or 0,
                    p.reference or "",
                )
                for p in s.scalars(select(ParseResult))
            ),  # fmt: skip
            "txn": sorted(
                (t.dedupe_key, t.status, t.type, t.direction, t.amount_paise, t.txn_time_utc)
                for t in s.scalars(select(Transaction))
            ),
            "source": sorted(
                (raw_hash[x.raw_message_id], txn_key[x.transaction_id], version[x.parse_result_id])
                for x in s.scalars(select(TransactionSource))
            ),
            "candidates": sorted(
                (txn_key[c.txn_a], txn_key[c.txn_b], c.rule, c.status)
                for c in s.scalars(select(DuplicateCandidate))
            ),
        }


def reset(engine: Engine) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def old_hdfc() -> object:
    """hdfc parser as an older version: H01 without its reference, no H17."""
    templates = []
    for t in HDFC.templates:
        if t.id == "H17":
            continue
        if t.id == "H01":
            t = dataclasses.replace(
                t, pattern=re.compile(t.pattern.pattern.replace(r"(?P<ref>\d+)", r"\d+"))
            )
        templates.append(t)
    return dataclasses.replace(HDFC, version="hdfc-1.0.0", templates=tuple(templates))


# --- I1 ---------------------------------------------------------------------
def test_i1_same_file_twice_adds_nothing(factory: sessionmaker, backup: Path) -> None:
    _, first = run_import(factory, backup)
    before = snapshot(factory)
    _, second = run_import(factory, backup)

    assert first.raw_new > 0 and first.transactions["new"] > 0
    assert (second.raw_new, second.transactions["new"]) == (0, 0)
    assert second.raw_duplicate == first.raw_new
    assert snapshot(factory) == before
    assert count(factory, ImportBatch, ImportBatch.status == "done") == 2


# --- I2 ---------------------------------------------------------------------
def test_i2_overlapping_backups_store_each_message_once(
    factory: sessionmaker, db_engine: Engine, tmp_path: Path
) -> None:
    rows = hdfc_rows()
    # Same SMS under another sender prefix is the same message (same core).
    relabelled = [("AD-HDFCBK-S" if s == "HDFCBK" else s, b, t) for s, b, t in rows[10:30]]
    folder = tmp_path / "backups"
    folder.mkdir()
    write_backup(folder / "a.xml", rows[:30])
    write_backup(folder / "b.xml", relabelled + rows[20:])
    _, counts = run_import(factory, folder)

    assert count(factory, RawMessage) == len(rows)
    assert counts.raw_duplicate == len(relabelled) + 10
    overlapped = snapshot(factory)

    reset(db_engine)
    run_import(factory, write_backup(tmp_path / "all.xml", rows))
    assert snapshot(factory)["txn"] == overlapped["txn"]
    assert snapshot(factory)["raw"] == overlapped["raw"]


# --- I3 ---------------------------------------------------------------------
def test_i3_every_transaction_traces_to_raw_and_parse_result(
    factory: sessionmaker, backup: Path
) -> None:
    run_import(factory, backup)
    with factory() as s:
        txns = s.scalars(select(Transaction)).all()
        assert txns
        for t in txns:
            sources = s.scalars(
                select(TransactionSource).where(TransactionSource.transaction_id == t.id)
            ).all()
            assert sources, t.id
            for src in sources:
                result = s.get(ParseResult, src.parse_result_id)
                assert result.raw_message_id == src.raw_message_id
                assert s.get(RawMessage, src.raw_message_id) is not None
                assert result.parser_version == HDFC.version and result.is_current
                assert (result.amount_paise, result.direction) == (t.amount_paise, t.direction)


# --- I4 ---------------------------------------------------------------------
def txn_by_raw(factory: sessionmaker) -> dict[str, int]:
    with factory() as s:
        rows = s.execute(
            select(RawMessage.content_hash, TransactionSource.transaction_id).join(
                TransactionSource, TransactionSource.raw_message_id == RawMessage.id
            )
        )
        return dict(rows.all())


def test_i4_reparse_after_version_bump(
    factory: sessionmaker, backup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(PARSERS, "HDFC", old_hdfc())
    run_import(factory, backup)
    before_ids = txn_by_raw(factory)
    raws, results = count(factory, RawMessage), count(factory, ParseResult)
    monkeypatch.undo()

    dry = run_reparse(factory, dry_run=True)
    assert count(factory, ParseResult) == results  # dry run saves nothing
    counts = run_reparse(factory)
    hdfc_raws = count(factory, RawMessage, RawMessage.sender_core.in_(["HDFCBK", "HDFCBN"]))
    assert counts.reparsed == dry.reparsed == hdfc_raws  # SBI stays at "none"
    assert counts.transactions["new"] == 2  # the two H17 messages now parse

    # Nothing deleted; one new result per reparsed message; ids stable per event.
    assert count(factory, RawMessage) == raws
    assert count(factory, ParseResult) == results + hdfc_raws
    after_ids = txn_by_raw(factory)
    assert {h: after_ids[h] for h in before_ids} == before_ids
    with factory() as s:
        refs = s.scalars(select(Transaction.reference).where(Transaction.channel == "upi"))
        assert all(refs)  # H01 debits now carry their reference

    # Idempotent: a second run changes nothing.
    state = snapshot(factory)
    assert run_reparse(factory).reparsed == 0
    assert snapshot(factory) == state


def test_i4_reparse_none_to_parser_matches_a_clean_import(
    factory: sessionmaker, db_engine: Engine, backup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_import(factory, backup)
    clean = snapshot(factory)

    reset(db_engine)
    monkeypatch.delitem(PARSERS, "HDFC")
    run_import(factory, backup)
    assert count(factory, Transaction) == 0
    with factory() as s:
        versions = set(s.scalars(select(ParseResult.parser_version)))
    assert versions == {"none"}
    monkeypatch.undo()

    run_reparse(factory)
    after = snapshot(factory)
    assert after["txn"] == clean["txn"]
    assert after["source"] == clean["source"]
    current = [p for p in after["parse"] if p[3]]
    assert current == [p for p in clean["parse"] if p[3]]


def test_i4_key_collision_moves_source_and_supersedes(
    factory: sessionmaker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender, body, when = hdfc_rows()[0]  # H01 UPI debit with a reference
    path = write_backup(tmp_path / "pair.xml", [("HDFCBK", body, when), ("HDFCBN", body, when)])
    monkeypatch.setitem(PARSERS, "HDFC", old_hdfc())
    run_import(factory, path)
    assert count(factory, Transaction) == 2  # no reference yet: one per raw message
    monkeypatch.undo()

    counts = run_reparse(factory)
    assert counts.transactions == {"updated": 1, "merged": 1, "superseded": 1}
    assert count(factory, Transaction, Transaction.status == "active") == 1
    assert count(factory, Transaction, Transaction.status == "superseded") == 1
    with factory() as s:
        targets = set(s.scalars(select(TransactionSource.transaction_id)))
    assert len(targets) == 1
    assert run_reparse(factory).reparsed == 0


# --- I5 ---------------------------------------------------------------------
def test_i5_non_money_never_creates_transactions(factory: sessionmaker, backup: Path) -> None:
    run_import(factory, backup)
    with factory() as s:
        linked = aliased(ParseResult)
        types = set(
            s.scalars(
                select(linked.type).join(
                    TransactionSource, TransactionSource.parse_result_id == linked.id
                )
            )
        )
        assert types <= MONEY_TYPES
        info = s.scalars(
            select(ParseResult.type).where(ParseResult.type.in_(["mandate", "other_info"]))
        ).all()
        assert "mandate" in info and "other_info" in info
        templates = set(s.scalars(select(ParseResult.template_id)))
        assert {"H_INFO", "H18", "H21"} <= templates

        unknown = dict(
            s.execute(
                select(ParseResult.unknown_reason, ParseResult.parser_version).where(
                    ParseResult.is_current, ParseResult.status == "unknown"
                )
            ).all()
        )
    assert unknown == {"no_parser_for_bank": "none", "foreign_currency_deferred": HDFC.version}


# --- I6 ---------------------------------------------------------------------
def test_i6_otp_promotional_and_unregistered_are_never_stored(
    factory: sessionmaker, backup: Path
) -> None:
    _, counts = run_import(factory, backup)
    assert counts.skipped == {"otp": 1, "promotional": 1, "unregistered_sender": 2, "mms": 2}
    with factory() as s:
        bodies = set(s.scalars(select(RawMessage.body)))
        cores = set(s.scalars(select(RawMessage.sender_core)))
    assert not bodies & {body for _, body, _ in NEVER_STORED}
    assert SBI_ROW[1] in bodies  # known bank without a parser: stored for a later reparse
    assert cores == {"HDFCBK", "HDFCBN", "SBIBNK"}


# --- I7 ---------------------------------------------------------------------
def test_i7_paise_are_integers_and_times_round_trip_in_utc(
    factory: sessionmaker, tmp_path: Path
) -> None:
    sender, body, _ = hdfc_rows()[0]
    when = datetime(2026, 1, 5, 23, 59, 59, 987000, tzinfo=UTC)
    run_import(factory, write_backup(tmp_path / "one.xml", [(sender, body, when)]))
    with factory() as s:
        raw = s.scalars(select(RawMessage)).one()
        txn = s.scalars(select(Transaction)).one()
    assert raw.received_at == when and raw.received_at.tzinfo == UTC
    assert txn.txn_time_utc == when and txn.txn_time_utc.utcoffset().total_seconds() == 0
    assert type(txn.amount_paise) is int and txn.amount_paise == 12500000


def test_i7_naive_times_are_rejected(factory: sessionmaker) -> None:
    with factory() as s:
        s.add(
            ImportBatch(
                owner_id=OWNER,
                source="sms_backup",
                started_at=datetime(2026, 1, 5),
                status="running",
                input_fingerprint="0" * 64,
                app_version="test",
                parser_versions={},
                counts={},
            )
        )
        with pytest.raises(Exception, match="naive"):
            s.flush()


# --- I8 ---------------------------------------------------------------------
def test_i8_crash_then_rerun_equals_one_clean_run(
    factory: sessionmaker, db_engine: Engine, backup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_import(factory, backup)
    clean = snapshot(factory)

    reset(db_engine)
    calls = {"n": 0}
    real = sms_backup.ingest

    def crash_on_23rd(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 23:
            raise RuntimeError("simulated crash")
        return real(*args, **kwargs)

    monkeypatch.setattr(sms_backup, "ingest", crash_on_23rd)
    with pytest.raises(RuntimeError):
        run_import(factory, backup, commit_every=5)
    assert 0 < count(factory, RawMessage) < len(clean["raw"])  # partly committed
    assert count(factory, ImportBatch, ImportBatch.status == "failed") == 1
    monkeypatch.undo()

    run_import(factory, backup, commit_every=5)
    assert snapshot(factory) == clean


# --- Dry run ----------------------------------------------------------------
def test_dry_run_counts_everything_and_saves_nothing(factory: sessionmaker, backup: Path) -> None:
    _, dry = run_import(factory, backup, dry_run=True)
    for model in ALL_TABLES:
        assert count(factory, model) == 0, model.__tablename__
    _, real = run_import(factory, backup)
    assert dry.as_dict() == real.as_dict()


def test_batch_row_records_versions_counts_and_fingerprint(
    factory: sessionmaker, backup: Path
) -> None:
    batch_id, counts = run_import(factory, backup)
    with factory() as s:
        batch = s.get(ImportBatch, batch_id)
    assert batch.status == "done" and batch.finished_at >= batch.started_at
    assert batch.parser_versions == {"HDFC": HDFC.version}
    assert re.fullmatch(r"[0-9a-f]{64}", batch.input_fingerprint)
    assert backup.name not in batch.input_fingerprint
    assert {k: v for k, v in batch.counts.items() if k != "seconds"} == counts.as_dict()


def test_candidates_are_recorded_not_merged(factory: sessionmaker, tmp_path: Path) -> None:
    autopay = (
        "HDFCBK",
        "AutoPay (E-mandate) Success!\nFor TEST STREAMING\nTxn Amt:Rs.999.00\nDt:20/01/2026\n"
        "Via:HDFC Bank DC 0002\nSI Hub ID: TEST0000001\nTnC",
        WHEN,
    )
    spend = (
        "HDFCBK",
        "Spent Rs.999.00 From HDFC Bank Card x0002 At TEST STREAMING On 2026-01-20:12:05:00 "
        "Bal Rs.24000 Not You? Call 18000000001/SMS BLOCK DC 0002 to 9000000001",
        WHEN,
    )
    _, counts = run_import(factory, write_backup(tmp_path / "pair.xml", [autopay, spend]))
    assert counts.transactions["new"] == 2 and counts.candidates == 1
    with factory() as s:
        pair = s.scalars(select(DuplicateCandidate)).one()
    assert (pair.status, pair.rule) == ("open", "same_amount_10min") and pair.txn_a < pair.txn_b


def test_reparse_reports_progress_every_5000(
    factory: sessionmaker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [("VM-SBIBNK-S", f"Rs {i} debited", WHEN) for i in range(1, 5002)]
    run_import(factory, write_backup(tmp_path / "sbi.xml", rows))
    monkeypatch.setitem(PARSERS, "SBI", dataclasses.replace(HDFC, bank="SBI", version="sbi-0.0.1"))
    seen: list[int] = []
    assert run_reparse(factory, progress=seen.append).reparsed == 5001
    assert seen == [5000]
