"""Derived storage and recompute: invariants I10 to I21 on a real database. Fake values only.

Runs on SQLite locally and on Postgres in CI (the db_engine fixture). The engine-only
invariants are in test_reconcile.py (I16, I18) and test_reconcile_links.py (I15, I17, I19).
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine, delete, event, func, select, update
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.engine.merchant import MERCHANT_VERSION
from app.engine.parsers import PARSERS
from app.engine.reconcile import RECONCILE_VERSION, ROLES, totals
from app.models import (
    DeriveRun,
    OwnerLinkDecision,
    OwnerRole,
    OwnIdentifier,
    Party,
    PartyText,
    RawMessage,
    Transaction,
    TxnDerived,
    TxnLink,
)
from app.pipeline import recompute as recompute_module
from app.pipeline.recompute import VERSIONS, plan
from tests.smsdata import WHEN, full_rows, write_backup
from tests.test_cli import assert_no_values
from tests.test_owner_load import count, owner_rows, private_values, write
from tests.test_pipeline import old_hdfc

OWNER = settings.owner_id
NOW = datetime(2026, 1, 21, tzinfo=UTC)
# An AutoPay success SMS and the card SMS for the same charge, 5 minutes apart.
PAIR = [
    (
        "HDFCBK",
        "AutoPay (E-mandate) Success!\nFor TEST CLOUD\nTxn Amt:Rs.999.00\nDt:20/01/2026\n"
        "Via:HDFC Bank DC 0002\nSI Hub ID: TEST0000009\nTnC",
        WHEN,
    ),
    (
        "HDFCBK",
        "Spent Rs.999.00 From HDFC Bank Card x0002 At TEST CLOUD On 2026-01-20:12:05:00 "
        "Bal Rs.24000 Not You? Call 18000000001/SMS BLOCK DC 0002 to 9000000001",
        WHEN,
    ),
]
# Owner file whose texts are counterparties of the fake fixture messages.
OWNER_FILE = {
    "accounts": [
        {
            "label": "Test other bank",
            "kind": "bank_account",
            "bank": "SBI",
            "last4": ["0009"],
            "texts": ["PERSON_900"],
        }
    ],
    "parties": [
        {
            "label": "Test Parent",
            "kind": "person",
            "income": "Pocket money",
            "texts": ["test.user@okaxis"],
        },
        {
            "label": "Test Employer",
            "kind": "business",
            "income": "Stipend",
            "texts": ["TEST EMPLOYER LTD"],
        },
        {"label": "Test Friend", "kind": "person", "texts": ["PERSON_901"]},
    ],
}


@pytest.fixture
def loaded(run, tmp_path: Path) -> str:
    """Fixture messages plus the AutoPay + card pair, imported (which ends with a recompute)."""
    path = write_backup(tmp_path / "all.xml", full_rows() + PAIR, mms=1)
    return run("import-sms", "--input", str(path))


def derived_rows(engine: Engine) -> dict[str, list]:
    link = TxnLink.__table__
    with engine.connect() as conn:
        return {
            "txn_derived": sorted(tuple(r) for r in conn.execute(select(TxnDerived.__table__))),
            "txn_links": sorted(
                tuple(r) for r in conn.execute(select(*[c for c in link.c if c.name != "id"]))
            ),
            "derive_runs": sorted(tuple(r) for r in conn.execute(select(DeriveRun.__table__))),
        }


def stored(engine: Engine) -> dict[int, TxnDerived]:
    with sessionmaker(engine, expire_on_commit=False)() as s:
        return {d.transaction_id: d for d in s.scalars(select(TxnDerived))}


def txn_id(engine: Engine, **where) -> int:
    with sessionmaker(engine)() as s:
        query = (
            select(Transaction.id).where(Transaction.status == "active").order_by(Transaction.id)
        )
        for name, value in where.items():
            query = query.where(getattr(Transaction, name) == value)
        return s.scalars(query).first()


def pair_ids(engine: Engine) -> tuple[int, int]:
    with sessionmaker(engine)() as s:
        ids = s.scalars(
            select(Transaction.id)
            .where(Transaction.counterparty_raw == "TEST CLOUD")
            .order_by(Transaction.id)
        )
        a, b = ids
        return a, b


def decide(engine: Engine, *rows) -> None:
    with sessionmaker(engine)() as s:
        s.add_all(rows)
        s.commit()


def role_decision(txn: int, role: str) -> OwnerRole:
    return OwnerRole(
        transaction_id=txn, owner_id=OWNER, role=role, decided_at=NOW, source="terminal"
    )


def link_decision(kind: str, a: int, b: int, verdict: str) -> OwnerLinkDecision:
    return OwnerLinkDecision(
        owner_id=OWNER,
        kind=kind,
        txn_a=min(a, b),
        txn_b=max(a, b),
        verdict=verdict,
        decided_at=NOW,
        source="terminal",
    )


def number(out: str, label: str) -> int:
    return int(re.search(rf"^\s*{re.escape(label)}\s+(\d+)$", out, flags=re.M).group(1))


# --- invariants -----------------------------------------------------------------


def test_i10_one_role_per_active_transaction_none_for_superseded(
    loaded: str, run, db_engine: Engine
) -> None:
    assert re.search(r"^recompute run #\d+ \(import\)$", loaded, flags=re.M)
    with sessionmaker(db_engine)() as s:
        active = set(s.scalars(select(Transaction.id).where(Transaction.status == "active")))
    rows = stored(db_engine)
    assert active and set(rows) == active  # the primary key allows one row each
    assert all(d.role in ROLES and d.role_basis == "engine" for d in rows.values())
    assert all(d.owner_id == OWNER and d.role_reasons[0] == d.role_rule for d in rows.values())
    gone = txn_id(db_engine, counterparty_raw="TEST BILLER")
    with sessionmaker(db_engine)() as s:
        s.execute(update(Transaction).where(Transaction.id == gone).values(status="superseded"))
        s.commit()
    out = run("recompute")
    assert number(out, "deleted") == 1 and set(stored(db_engine)) == active - {gone}


def test_i11_recompute_twice_writes_nothing(loaded: str, run, db_engine: Engine) -> None:
    before = derived_rows(db_engine)
    assert len(before["derive_runs"]) == 1
    for flags in ((), ("--dry-run",), ("--accept-key-changes",)):
        out = run("recompute", *flags)
        assert derived_rows(db_engine) == before  # not even a derive_runs row
        assert [number(out, w) for w in ("inserted", "updated", "deleted")] == [0, 0, 0]
    assert "recompute: nothing to change, nothing written" in run("recompute")


def test_i12_derived_data_is_a_pure_function_of_its_input(
    loaded: str, run, db_engine: Engine, tmp_path: Path
) -> None:
    run("owner-load", write(tmp_path, OWNER_FILE))
    before = derived_rows(db_engine)
    with sessionmaker(db_engine)() as s:
        s.execute(delete(TxnLink))
        s.execute(delete(TxnDerived))
        s.commit()
    out = run("recompute")
    after = derived_rows(db_engine)
    assert number(out, "inserted") == len(before["txn_derived"])
    assert (after["txn_derived"], after["txn_links"]) == (
        before["txn_derived"],
        before["txn_links"],
    )


def test_i13_import_reparse_and_recompute_never_change_an_owner_table(
    run, db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(PARSERS, "HDFC", old_hdfc())
    path = write_backup(tmp_path / "all.xml", full_rows() + PAIR)
    run("import-sms", "--input", str(path))
    run("owner-load", write(tmp_path, OWNER_FILE))
    a, b = pair_ids(db_engine)
    decide(
        db_engine,
        role_decision(txn_id(db_engine, counterparty_raw="TEST BILLER"), "ignored"),
        link_decision("duplicate", a, b, "different"),
    )
    owner = owner_rows(db_engine)
    monkeypatch.undo()  # the parser is at its real version again
    for command in (("reparse",), ("import-sms", "--input", str(path)), ("recompute",)):
        run(*command)
        assert owner_rows(db_engine) == owner, command
    assert any(owner.values()) and stored(db_engine)


def test_i14_the_owner_always_wins(loaded: str, run, db_engine: Engine) -> None:
    a, b = pair_ids(db_engine)
    assert derived_rows(db_engine)["txn_links"]  # the rule linked the pair
    ignored = txn_id(db_engine, counterparty_raw="TEST BILLER")
    refund = txn_id(db_engine, counterparty_raw="TEST BRANCH")  # a plain credit
    decide(
        db_engine,
        link_decision("duplicate", a, b, "different"),
        role_decision(ignored, "ignored"),
        role_decision(refund, "refund"),
    )
    run("recompute")
    rows = stored(db_engine)
    with sessionmaker(db_engine)() as s:
        decisions = {r.transaction_id: r.role for r in s.scalars(select(OwnerRole))}
        links = {(x.txn_a, x.txn_b): x for x in s.scalars(select(TxnLink))}
    assert {i: rows[i].role for i in decisions} == decisions
    assert {(rows[i].role_rule, rows[i].role_basis) for i in decisions} == {("OWNER_role", "owner")}
    assert (a, b) not in links  # "different": neither linked nor a candidate
    assert (rows[a].role, rows[b].role) == ("spend", "spend")

    with sessionmaker(db_engine)() as s:  # the owner changes the verdict
        s.execute(update(OwnerLinkDecision).values(verdict="same"))
        s.commit()
    run("recompute")
    with sessionmaker(db_engine)() as s:
        link = s.scalar(select(TxnLink).where(TxnLink.txn_a == a, TxnLink.txn_b == b))
    assert (link.status, link.decided_by, link.reason) == ("linked", "owner", "owner_same")
    assert sorted(d.role for i, d in stored(db_engine).items() if i in (a, b)) == [
        "duplicate",
        "spend",
    ]


def test_i15_a_duplicate_group_counts_once(loaded: str, db_engine: Engine) -> None:
    a, b = pair_ids(db_engine)
    with sessionmaker(db_engine)() as s:
        link = s.scalars(select(TxnLink).where(TxnLink.status == "linked")).one()
    assert (link.kind, link.txn_a, link.txn_b) == ("duplicate", a, b)
    assert (link.rule, link.reason, link.decided_by) == (
        "DUP_autopay_card",
        "unique_10min",
        "engine",
    )
    rows = stored(db_engine)
    (primary,) = [i for i in (a, b) if rows[i].role == "spend"]
    (other,) = [i for i in (a, b) if rows[i].role == "duplicate"]
    assert rows[other].duplicate_of == primary and rows[primary].duplicate_of is None
    for d in rows.values():  # every duplicate points at a member that counts
        assert (d.role == "duplicate") == (d.duplicate_of is not None)
        assert d.duplicate_of is None or rows[d.duplicate_of].role != "duplicate"
    with sessionmaker(db_engine)() as s:
        p = plan(s, OWNER)
    pair = [t for t in p.txns if t.id in (a, b)]
    whole = (WHEN - timedelta(days=1), WHEN + timedelta(days=1))
    assert totals(pair, rows_as_roles(rows), *whole).spent_paise == 99_900  # once, not twice


def rows_as_roles(rows: dict[int, TxnDerived]) -> dict[int, SimpleNamespace]:
    return {i: SimpleNamespace(role=d.role, basis=d.role_basis) for i, d in rows.items()}


def test_i16_totals_from_stored_roles_equal_a_fresh_derive(
    loaded: str, run, db_engine: Engine, tmp_path: Path
) -> None:
    run("owner-load", write(tmp_path, OWNER_FILE))
    rows = stored(db_engine)
    with sessionmaker(db_engine)() as s:
        p = plan(s, OWNER)
    assert p.changes == 0
    assert {i: d.role for i, d in rows.items()} == {i: d.role for i, d in p.result.roles.items()}
    times = sorted(t.txn_time_utc for t in p.txns)
    ranges = [(times[0], times[-1] + timedelta(seconds=1)), (times[0], times[len(times) // 2])]
    for start, end in ranges:
        from_storage = totals(p.txns, rows_as_roles(rows), start, end)
        assert from_storage == totals(p.txns, p.result.roles, start, end)
    whole = totals(p.txns, rows_as_roles(rows), *ranges[0])
    assert whole.spent_paise > 0 and whole.income_paise > 0  # the owner file named income


def test_i20_owner_decisions_survive_reparse(
    run, db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(PARSERS, "HDFC", old_hdfc())
    run("import-sms", "--input", str(write_backup(tmp_path / "all.xml", full_rows() + PAIR)))
    a, b = pair_ids(db_engine)
    upi_debit = txn_id(db_engine, counterparty_raw="PERSON_900")  # H01: reparse updates it
    with sessionmaker(db_engine)() as s:
        twin_a, twin_b = s.scalars(  # two AutoPay messages for one mandate and amount
            select(Transaction.id)
            .where(Transaction.channel == "e_mandate", Transaction.amount_paise == 49_900)
            .order_by(Transaction.id)
        )
        before_reference = s.get(Transaction, upi_debit).reference
    decide(
        db_engine,
        role_decision(upi_debit, "self_transfer"),
        link_decision("duplicate", a, b, "different"),
        link_decision("duplicate", twin_a, twin_b, "same"),
    )
    run("recompute")
    decisions = owner_rows(db_engine)
    monkeypatch.undo()

    out = run("reparse")
    assert re.search(r"^recompute run #\d+ \(reparse\)$", out, flags=re.M)
    assert owner_rows(db_engine) == decisions  # none changed, none deleted
    with sessionmaker(db_engine)() as s:
        assert s.get(Transaction, upi_debit).reference != before_reference  # it was reparsed
        links = {(x.txn_a, x.txn_b): x.status for x in s.scalars(select(TxnLink))}
    rows = stored(db_engine)
    assert (rows[upi_debit].role, rows[upi_debit].role_rule) == ("self_transfer", "OWNER_role")
    assert (a, b) not in links and links[twin_a, twin_b] == "linked"
    assert sorted(rows[i].role for i in (twin_a, twin_b)) == ["duplicate", "spend"]


def test_i21_commands_print_counts_only(
    loaded: str, run, db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = [
        loaded,
        run("owner-load", write(tmp_path, OWNER_FILE), "--dry-run"),
        run("owner-load", write(tmp_path, OWNER_FILE)),
        run("recompute"),
        run("recompute", "--dry-run"),
        run("reconcile-stats"),
        run("stats"),
        run("reparse"),
    ]
    with sessionmaker(db_engine)() as s:  # two owner texts with one merchant key
        party = s.scalars(select(Party.id).order_by(Party.id)).first()
        s.add(PartyText(owner_id=OWNER, party_id=party, text="person-900", source="app"))
        s.commit()
    outputs += [run("recompute", code=1), run("reconcile-stats", code=1)]
    monkeypatch.setattr(recompute_module, "derive", boom)
    outputs.append(run("recompute", code=1))
    for out in outputs:
        assert_no_values(out)
        assert not sorted(v for v in private_values(OWNER_FILE) if v in out)
        assert not [v for v in ("TEST CLOUD", "999", "person-900", "TEST SECRET") if v in out]
        assert not any(key in out for key in ("brand:", "vpa:", "name:"))


def boom(*args, **kwargs):
    raise RuntimeError("TEST SECRET in an error message")


# --- recompute ------------------------------------------------------------------


def test_recompute_after_owner_load_changes_roles(
    loaded: str, run, db_engine: Engine, tmp_path: Path
) -> None:
    upi_credit = txn_id(db_engine, counterparty_raw="test.user@okaxis")
    neft_credit = txn_id(db_engine, counterparty_raw="TEST EMPLOYER LTD")
    to_own = txn_id(db_engine, counterparty_raw="PERSON_900")
    to_friend = txn_id(db_engine, counterparty_raw="PERSON_901")
    before = stored(db_engine)
    assert (before[upi_credit].role, before[upi_credit].role_basis) == ("payback", "engine")
    assert (before[neft_credit].role, before[to_own].role) == ("uncertain", "spend")
    assert before[upi_credit].display_name == "test.user@okaxis"

    out = run("owner-load", write(tmp_path, OWNER_FILE))
    assert re.search(r"^texts matching no transaction\s+0$", out, flags=re.M)
    assert re.search(r"^recompute run #\d+ \(owner\)$", out, flags=re.M)
    assert "warning: owner data lists no income party" in loaded and "warning" not in out
    rows = stored(db_engine)
    with sessionmaker(db_engine)() as s:
        parties = {p.label: p.id for p in s.scalars(select(Party))}
        account = s.scalar(select(OwnIdentifier.own_account_id).where(OwnIdentifier.kind == "text"))
    d = rows[upi_credit]  # income is checked before payback
    assert (d.role, d.role_rule, d.role_basis) == ("income", "CR_income_party", "owner")
    assert (d.display_name, d.merchant_kind, d.merchant_confidence, d.party_id) == (
        "Test Parent",
        "person",
        "high",
        parties["Test Parent"],
    )
    assert d.merchant_key == "vpa:test.user@okaxis"  # the key is still the engine's
    assert (rows[neft_credit].role, rows[neft_credit].merchant_kind) == ("income", "business")
    d = rows[to_own]  # a self-transfer by own text
    assert (d.role, d.role_rule, d.role_basis) == ("self_transfer", "ST_own_text", "owner")
    assert (d.own_account_id, d.party_id) == (account, None)
    d = rows[to_friend]  # paying a person stays spend; the party names it
    assert (d.role, d.display_name, d.party_id) == ("spend", "Test Friend", parties["Test Friend"])
    changed = sum(before[i].role != rows[i].role for i in rows)
    assert changed == 3

    no_income = {
        **OWNER_FILE,
        "parties": [{**OWNER_FILE["parties"][0]}, *OWNER_FILE["parties"][1:]],
    }
    del no_income["parties"][0]["income"]
    run("owner-load", write(tmp_path, no_income))
    d = stored(db_engine)[upi_credit]
    assert (d.role, d.role_rule, d.role_basis) == ("payback", "CR_person_party", "owner")
    out = run("owner-load", write(tmp_path, {}))  # removing the file rows undoes it all
    assert {i: d.role for i, d in stored(db_engine).items()} == {
        i: d.role for i, d in before.items()
    }
    assert all(d.party_id is None and d.own_account_id is None for d in stored(db_engine).values())


def test_recompute_records_a_run_with_versions_and_counts(loaded: str, db_engine: Engine) -> None:
    with sessionmaker(db_engine)() as s:
        run_row = s.scalars(select(DeriveRun)).one()
        active = s.scalar(
            select(func.count()).select_from(Transaction).where(Transaction.status == "active")
        )
    assert (run_row.status, run_row.trigger, run_row.owner_id) == ("done", "import", OWNER)
    assert (
        run_row.versions
        == VERSIONS
        == {
            "merchant": MERCHANT_VERSION,
            "reconcile": RECONCILE_VERSION,
            "categorise": "categorise-1.2.0",
        }
    )
    assert run_row.started_at <= run_row.finished_at
    counts = run_row.counts
    assert counts["transactions"] == active == sum(counts["roles"].values())
    assert counts["txn_derived"] == {"inserted": active, "updated": 0, "deleted": 0}
    assert counts["links"]["duplicate linked"] == 1 and counts["roles"]["duplicate"] == 1


def test_dry_run_shows_the_changes_and_saves_nothing(loaded: str, run, db_engine: Engine) -> None:
    with sessionmaker(db_engine)() as s:
        s.execute(delete(TxnLink))
        s.execute(delete(TxnDerived))
        s.commit()
    before = derived_rows(db_engine)
    out = run("recompute", "--dry-run")
    assert "recompute (dry run: nothing saved)" in out and number(out, "inserted") > 0
    assert derived_rows(db_engine) == before
    stats = run("reconcile-stats")
    assert number(stats, "stored rows that differ") > 0
    run("recompute")
    stats = run("reconcile-stats")
    assert number(stats, "stored rows that differ") == 0
    assert re.search(r"^stored run\n  last run\s+#\d+\n", stats, flags=re.M)
    assert re.search(rf"^  merchant version\s+{MERCHANT_VERSION}$", stats, flags=re.M)
    assert re.search(rf"^  reconcile version\s+{RECONCILE_VERSION}$", stats, flags=re.M)


def test_stats_before_any_recompute(run, db_engine: Engine) -> None:
    stats = run("reconcile-stats")
    assert re.search(r"^stored run\n  last run\s+none\n  merchant version\s+-\n", stats, flags=re.M)
    assert number(stats, "stored rows that differ") == 0


def old_merchant_version(engine: Engine) -> None:
    """Pretend the stored rows were made by an older merchant engine."""
    with sessionmaker(engine)() as s:
        versions = VERSIONS | {"merchant": "merchant-0.9.0"}
        s.execute(update(DeriveRun).values(versions=versions))
        s.commit()


def test_recompute_stops_when_a_merchant_change_loses_an_owner_match(
    loaded: str, run, db_engine: Engine, tmp_path: Path
) -> None:
    run("owner-load", write(tmp_path, OWNER_FILE))
    friend_rows = sum(d.party_id is not None for d in stored(db_engine).values())

    def rename_text() -> None:  # stands for a key rule change: the text no longer matches
        with sessionmaker(db_engine)() as s:
            s.execute(
                update(PartyText).where(PartyText.text == "PERSON_901").values(text="PERSON_999")
            )
            s.commit()

    rename_text()
    old_merchant_version(db_engine)
    before = derived_rows(db_engine)
    for flags in ((), ("--dry-run",)):
        out = run("recompute", *flags, code=3)
        assert "recompute stopped: nothing written" in out
        assert re.search(r"merchant-0\.9\.0 -> " + re.escape(MERCHANT_VERSION), out)
        assert "2 transaction(s) would lose or change their owner match" in out
        assert "--accept-key-changes" in out and derived_rows(db_engine) == before
    stats = run("reconcile-stats")
    assert number(stats, "stored rows that differ") == 2
    assert re.search(r"^  merchant version\s+merchant-0\.9\.0$", stats, flags=re.M)

    out = run("recompute", "--accept-key-changes")
    assert number(out, "updated") == 2
    assert sum(d.party_id is not None for d in stored(db_engine).values()) == friend_rows - 2
    with sessionmaker(db_engine)() as s:
        last = s.scalars(select(DeriveRun).order_by(DeriveRun.id.desc())).first()
    assert last.versions == VERSIONS and last.trigger == "manual"


def test_merchant_change_without_a_lost_match_just_records_the_new_version(
    loaded: str, run, db_engine: Engine, tmp_path: Path
) -> None:
    run("owner-load", write(tmp_path, OWNER_FILE))
    old_merchant_version(db_engine)
    rows = derived_rows(db_engine)
    out = run("recompute")  # no row differs, but the stored version must move on
    assert re.search(r"^recompute run #\d+ \(manual\)$", out, flags=re.M)
    after = derived_rows(db_engine)
    assert (after["txn_derived"], after["txn_links"]) == (rows["txn_derived"], rows["txn_links"])
    assert len(after["derive_runs"]) == len(rows["derive_runs"]) + 1
    assert "nothing to change" in run("recompute")


def test_owner_text_change_alone_never_stops_recompute(
    loaded: str, run, db_engine: Engine, tmp_path: Path
) -> None:
    run("owner-load", write(tmp_path, OWNER_FILE))
    changed = {**OWNER_FILE, "parties": OWNER_FILE["parties"][:2]}  # the owner drops a party
    out = run("owner-load", write(tmp_path, changed))
    assert count(out, "txn_derived", "updated") == 2 and "stopped" not in out


def test_owner_data_that_cannot_hold_writes_nothing(
    loaded: str, run, db_engine: Engine, tmp_path: Path
) -> None:
    run("owner-load", write(tmp_path, OWNER_FILE))
    before = derived_rows(db_engine)
    with sessionmaker(db_engine)() as s:  # past the loader: one text in two places
        party = s.scalars(select(Party.id).order_by(Party.id)).first()
        s.add(PartyText(owner_id=OWNER, party_id=party, text="Person 900", source="app"))
        s.commit()
    out = run("recompute", code=1)
    assert "recompute failed: one owner text is listed in two places" in out
    assert "No derived data was written" in out and derived_rows(db_engine) == before
    assert "reconcile-stats failed: one owner text" in run("reconcile-stats", code=1)


def test_import_is_saved_when_the_recompute_after_it_fails(
    run, db_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recompute_module, "derive", boom)
    path = write_backup(tmp_path / "all.xml", full_rows() + PAIR)
    out = run("import-sms", "--input", str(path), code=1)
    assert "import-sms batch" in out and "recompute failed: RuntimeError" in out
    assert "The import step itself is saved" in out and "python -m app.cli recompute" in out
    assert "TEST SECRET" not in out
    with sessionmaker(db_engine)() as s:
        assert s.scalar(select(func.count()).select_from(RawMessage)) > 0
        assert s.scalar(select(func.count()).select_from(Transaction)) > 0
        assert s.scalar(select(func.count()).select_from(TxnDerived)) == 0
    monkeypatch.undo()
    out = run("recompute")
    assert number(out, "inserted") > 0 and stored(db_engine)


def test_recompute_uses_a_fixed_number_of_statements(loaded: str, run, db_engine: Engine) -> None:
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement.split()[0].upper())

    def run_counted() -> list[str]:
        statements.clear()
        event.listen(db_engine, "before_cursor_execute", record)
        try:
            run("recompute")
        finally:
            event.remove(db_engine, "before_cursor_execute", record)
        return list(statements)

    quiet = run_counted()  # nothing to change: reads only
    assert not {"INSERT", "UPDATE", "DELETE"} & set(quiet) and len(quiet) <= 14
    with sessionmaker(db_engine)() as s:  # every kind of change at once
        ids = list(s.scalars(select(TxnDerived.transaction_id).order_by(TxnDerived.transaction_id)))
        s.execute(delete(TxnDerived).where(TxnDerived.transaction_id.in_(ids[:10])))
        s.execute(
            update(TxnDerived)
            .where(TxnDerived.transaction_id.in_(ids[10:20]))
            .values(role="ignored")
        )
        s.execute(update(Transaction).where(Transaction.id == ids[25]).values(status="superseded"))
        s.execute(update(TxnLink).values(status="candidate"))
        s.commit()
    busy = run_counted()
    writes = [s for s in busy if s in ("INSERT", "UPDATE", "DELETE")]
    lock = db_engine.dialect.name == "postgresql"  # the advisory lock is one more statement
    assert len(busy) == 17 + lock and sorted(writes) == ["DELETE", "DELETE"] + ["INSERT"] * 3, (
        " ".join(busy)
    )
