"""reconcile-review, owner-export and totals. Fake values only."""

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import sessionmaker

from app import cli
from app.config import settings
from app.db import Base
from app.engine.money import format_inr
from app.engine.reconcile import ist_month, totals
from app.models import (
    DeriveRun,
    OwnAccount,
    OwnerLinkDecision,
    OwnerRole,
    OwnIdentifier,
    Party,
    PartyText,
    Transaction,
    TxnDerived,
)
from app.pipeline.recompute import plan
from tests.smsdata import full_rows, write_backup
from tests.test_cli import assert_no_values
from tests.test_owner_load import private_values, write
from tests.test_storage import OWNER_FILE, PAIR, decide, link_decision, pair_ids, role_decision

OWNER = settings.owner_id


@pytest.fixture
def loaded(run, tmp_path: Path) -> str:
    """Fixture messages plus an AutoPay + card pair, imported (ends with a recompute)."""
    return run("import-sms", "--input", str(write_backup(tmp_path / "all.xml", full_rows() + PAIR)))


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch):
    """Pretend stdout and stdin are a console; returns a function that queues answers."""
    monkeypatch.setattr(cli, "is_terminal", lambda: True)
    monkeypatch.setattr(cli, "can_ask", lambda: True)
    answers: list[str] = []

    def ask(prompt: str) -> str:
        print(prompt)
        if not answers:
            raise EOFError
        return answers.pop(0)

    monkeypatch.setattr(cli, "ask", ask)
    return answers.extend


def items(out: str) -> list[str]:
    return re.findall(r"^\[\d+/\d+\] (.*)$", out, flags=re.M)


def private_lines(out: str) -> list[str]:
    lines = out.strip().splitlines()
    assert lines[0] == lines[-1] == cli.PRIVATE
    return lines


# --- reconcile-review -------------------------------------------------------------


def test_review_refuses_without_a_terminal(loaded, run, monkeypatch) -> None:
    for flags in ((), ("--list",)):
        out = run("reconcile-review", *flags, code=2)
        assert "only to a terminal" in out and cli.PRIVATE not in out
        assert_no_values(out)
    monkeypatch.setattr(cli, "is_terminal", lambda: True)
    assert "asks questions" in run("reconcile-review", code=2)  # stdin is not a console
    assert run("reconcile-review", "--list").startswith(cli.PRIVATE)  # --list asks nothing


def test_review_list_shows_every_kind_of_item(loaded, run, terminal) -> None:
    out = run("reconcile-review", "--list")
    lines = private_lines(out)
    found = items(out)
    kinds = {title.split(":")[0] for title in found}
    assert kinds == {"refund candidate", "uncertain credit", "debit with no payee"}
    assert lines[-2] == f"{len(found)} item(s)"
    assert re.search(
        r"^  #\d+\s+2026-01-\d\d \d\d:\d\d IST  (debit |credit) +Rs [\d,]+\.\d\d  \S+ +\S",
        out,
        flags=re.M,
    )
    pair = re.search(r"^\[\d+/\d+\] refund candidate: RF_\w+, \w+\n(  #.*\n){2}", out, re.M)
    assert pair  # a pair shows both sides
    assert "?" not in out  # nothing was asked


def test_review_saves_answers_and_recomputes(loaded, run, terminal, db_engine: Engine) -> None:
    found = items(run("reconcile-review", "--list"))
    pairs = [t for t in found if "candidate" in t]
    credits = [t for t in found if t.startswith("uncertain")]
    payees = [t for t in found if t.startswith("debit with")]
    answers = []
    for title in found:
        if "candidate" in title:
            answers += ["maybe", "different"]  # a wrong answer is asked again
        elif title.startswith("uncertain"):
            answers.append("ignored")
        else:
            answers.append("")  # empty: leave
    terminal(answers)
    out = run("reconcile-review")
    lines = private_lines(out)
    assert "answer one of: same, different, skip, quit" in out
    assert f"answered: {len(pairs)} pair(s), {len(credits)} role(s)" in lines
    assert f"saved: {len(pairs)} link decision(s), {len(credits)} role decision(s)" in lines
    assert re.search(r"^recompute run #\d+ \(owner\)$", out, flags=re.M)
    with sessionmaker(db_engine)() as s:
        links = list(s.scalars(select(OwnerLinkDecision)))
        roles = list(s.scalars(select(OwnerRole)))
    assert len(links) == len(pairs) and {(x.verdict, x.source) for x in links} == {
        ("different", "terminal")
    }
    assert len(roles) == len(credits) and {(r.role, r.source) for r in roles} == {
        ("ignored", "terminal")
    }
    left = items(run("reconcile-review", "--list"))
    assert left == payees  # pairs decided, credits set; the payees were left


def test_review_same_links_and_quit_keeps_earlier_answers(
    loaded, run, terminal, db_engine: Engine
) -> None:
    found = items(run("reconcile-review", "--list"))
    assert found[0].startswith("refund candidate")
    terminal(["same", "quit"])
    out = run("reconcile-review")
    assert "answered: 1 pair(s), 0 role(s)" in out
    with sessionmaker(db_engine)() as s:
        (decision,) = s.scalars(select(OwnerLinkDecision))
        assert (decision.kind, decision.verdict) == ("refund", "same")
    with sessionmaker(db_engine)() as s:
        p = plan(s, OWNER)
    linked = [x for x in p.result.links if (x.txn_a, x.txn_b) == (decision.txn_a, decision.txn_b)]
    assert [(x.status, x.decided_by) for x in linked] == [("linked", "owner")]
    terminal([])  # end of input stops the review like quit
    out = run("reconcile-review")
    assert "answered: 0 pair(s), 0 role(s)" in out and "saved" not in out


def test_review_refuses_answers_that_cannot_hold(loaded, run, terminal, db_engine) -> None:
    with sessionmaker(db_engine)() as s:

        def one(**where) -> int:
            query = select(Transaction.id)
            for name, value in where.items():
                query = query.where(getattr(Transaction, name) == value)
            return s.scalar(query)

        purchase = one(channel="debit_card", counterparty_raw="TEST MERCHANT")  # Rs 222
        upi_refund = one(type="refund", channel="upi")  # Rs 199
        card_refund = one(type="refund", channel="debit_card", counterparty_raw="TEST MERCHANT")
    decide(db_engine, link_decision("refund", purchase, upi_refund, "same"))  # the owner, earlier
    run("recompute")
    found = items(run("reconcile-review", "--list"))
    assert found[0].startswith("refund candidate: RF_partial")  # Rs 77 more on the same purchase
    terminal(["same", "quit"])
    out = run("reconcile-review", code=1)
    assert "not saved: owner link decisions: refunds add up to more than the purchase" in out
    with sessionmaker(db_engine)() as s:
        saved = [(d.txn_a, d.txn_b) for d in s.scalars(select(OwnerLinkDecision))]
    assert saved == [tuple(sorted((purchase, upi_refund)))] and card_refund not in saved[0]


# --- owner-export -----------------------------------------------------------------


def snapshot(engine: Engine) -> dict:
    """Owner data without ids or creation times, decisions by dedupe key."""
    with sessionmaker(engine)() as s:
        key = dict(s.execute(select(Transaction.id, Transaction.dedupe_key)).all())
        account_of = {a.id: a.label for a in s.scalars(select(OwnAccount))}
        party_of = {p.id: p.label for p in s.scalars(select(Party))}
        return {
            "accounts": sorted(
                (a.label, a.kind, a.bank, a.source) for a in s.scalars(select(OwnAccount))
            ),
            "identifiers": sorted(
                (account_of[i.own_account_id], i.kind, i.value, i.source)
                for i in s.scalars(select(OwnIdentifier))
            ),
            "parties": sorted(
                (p.label, p.kind, p.income_label, p.source) for p in s.scalars(select(Party))
            ),
            "texts": sorted(
                (party_of[t.party_id], t.text, t.source) for t in s.scalars(select(PartyText))
            ),
            "roles": sorted(
                (key[r.transaction_id], r.role, r.decided_at, r.source)
                for r in s.scalars(select(OwnerRole))
            ),
            "links": sorted(
                (d.kind, *sorted((key[d.txn_a], key[d.txn_b])), d.verdict, d.decided_at, d.source)
                for d in s.scalars(select(OwnerLinkDecision))
            ),
        }


def empty_owner_tables(engine: Engine) -> None:
    with sessionmaker(engine)() as s:
        for model in (OwnIdentifier, PartyText, OwnerLinkDecision, OwnerRole):
            s.execute(delete(model))
        s.execute(update(TxnDerived).values(party_id=None, own_account_id=None))
        s.execute(delete(OwnAccount))
        s.execute(delete(Party))
        s.commit()


@pytest.fixture
def decided(loaded, run, db_engine: Engine, tmp_path: Path) -> dict:
    """Owner file loaded, plus a review role and link decision."""
    run("owner-load", write(tmp_path, OWNER_FILE))
    a, b = pair_ids(db_engine)
    with sessionmaker(db_engine)() as s:
        biller = s.scalar(
            select(Transaction.id).where(Transaction.counterparty_raw == "TEST BILLER")
        )
    decide(
        db_engine, role_decision(biller, "ignored"), link_decision("duplicate", a, b, "different")
    )
    run("recompute")
    return snapshot(db_engine)


def test_export_then_load_into_empty_tables_restores_every_row(
    decided: dict, run, db_engine: Engine, tmp_path: Path
) -> None:
    target = tmp_path / "export.json"
    out = run("owner-export", str(target))
    assert out.startswith("owner-export\n")
    counts = dict(re.findall(r"^(\w[\w ]*?)\s+(\d+)$", out, flags=re.M))
    assert counts == {
        "accounts": "1",
        "identifiers": "2",
        "parties": "3",
        "texts": "3",
        "role decisions": "1",
        "link decisions": "1",
        "category decisions": "0",
        "labels": "0",
        "labelled transactions": "0",
    }
    assert_no_values(out)
    assert not sorted(v for v in private_values(OWNER_FILE) if v in out)
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["format"] == "flash-owner-export-1"
    assert {e["source"] for e in document["accounts"] + document["parties"]} == {"file"}
    assert document["roles"][0]["source"] == document["links"][0]["source"] == "terminal"
    assert len(document["links"][0]["a_key"]) == 64

    stored = {i: d.role for i, d in stored_roles(db_engine).items()}
    empty_owner_tables(db_engine)
    assert not any(snapshot(db_engine).values())
    out = run("owner-load", str(target))
    assert out.startswith("owner-load: export restored\n")
    assert re.search(r"^mapped to another id\s+0$", out, flags=re.M)
    assert re.search(r"^recompute run #\d+ \(owner\)$", out, flags=re.M)
    assert snapshot(db_engine) == decided
    assert {i: d.role for i, d in stored_roles(db_engine).items()} == stored
    assert not sorted(v for v in private_values(OWNER_FILE) if v in out)

    again = run("owner-load", str(target), code=2)  # never over rows that exist
    assert "not empty; an export is restored only into empty owner tables" in again
    assert snapshot(db_engine) == decided
    plain = run("owner-load", write(tmp_path, OWNER_FILE))  # the plain file still syncs
    assert re.search(r"^  unchanged\s+3$", plain, flags=re.M)


def stored_roles(engine: Engine) -> dict[int, TxnDerived]:
    with sessionmaker(engine, expire_on_commit=False)() as s:
        return {d.transaction_id: d for d in s.scalars(select(TxnDerived))}


def test_rebuilt_database_takes_the_export_back_by_dedupe_key(
    decided: dict, run, db_engine: Engine, tmp_path: Path
) -> None:
    target = tmp_path / "export.json"
    run("owner-export", str(target))
    Base.metadata.drop_all(db_engine)  # a new database: the same messages, other ids
    Base.metadata.create_all(db_engine)
    rows = list(reversed(full_rows() + PAIR))
    run("import-sms", "--input", str(write_backup(tmp_path / "again.xml", rows)))

    document = json.loads(target.read_text(encoding="utf-8"))
    with sessionmaker(db_engine)() as s:
        id_of = dict(s.execute(select(Transaction.dedupe_key, Transaction.id)).all())
    assert id_of[document["roles"][0]["dedupe_key"]] != document["roles"][0]["transaction"]
    out = run("owner-load", str(target))
    mapped = int(re.search(r"^mapped to another id\s+(\d+)$", out, flags=re.M).group(1))
    assert mapped == 2  # the role decision and the link decision
    assert snapshot(db_engine) == decided
    rows_now = stored_roles(db_engine)
    assert rows_now[id_of[document["roles"][0]["dedupe_key"]]].role == "ignored"
    a, b = (id_of[document["links"][0][k]] for k in ("a_key", "b_key"))
    assert {rows_now[a].role, rows_now[b].role} == {"spend"}  # "different" still holds


def test_export_naming_a_missing_transaction_loads_nothing(
    decided: dict, run, db_engine: Engine, tmp_path: Path
) -> None:
    target = tmp_path / "export.json"
    run("owner-export", str(target))
    document = json.loads(target.read_text(encoding="utf-8"))
    document["links"][0]["b_key"] = "0" * 64
    document["roles"][0]["role"] = "duplicate"
    empty_owner_tables(db_engine)
    out = run("owner-load", write(tmp_path, document), code=2)
    assert "roles[0].role: must be one of" in out  # checked before anything is written
    document["roles"][0]["role"] = "ignored"
    out = run("owner-load", write(tmp_path, document), code=2)
    assert "links[0].b_key: no transaction with this dedupe key; import the messages first" in out
    assert not any(snapshot(db_engine).values())
    for bad, message in (
        ({"format": "flash-owner-export-9"}, "file.format: must be flash-owner-export-1"),
        ({"links": [{"kind": "duplicate"}]}, "links[0].a: must be a transaction id"),
        ({"roles": [{**document["roles"][0], "decided_at": "yesterday"}]}, "decided_at: must be"),
        ({"accounts": [{**document["accounts"][0], "source": "review"}]}, "accounts[0].source"),
    ):
        out = run("owner-load", write(tmp_path, document | bad), code=2)
        assert message in out, message


def test_export_refuses_a_path_inside_the_repository(decided: dict, run) -> None:
    out = run("owner-export", str(cli.REPO / "data" / "owner-export.json"), code=2)
    assert "outside the repository" in out
    assert not (cli.REPO / "data" / "owner-export.json").exists()


# --- totals -----------------------------------------------------------------------


def money(out: str, label: str) -> str:
    return re.search(rf"^\s*{label}\s+(-?Rs [\d,]+\.\d\d)$", out, flags=re.M).group(1)


def test_totals_for_an_ist_month(decided: dict, run, terminal, db_engine: Engine) -> None:
    out = run("totals", "--month", "2026-01")
    lines = private_lines(out)
    assert re.match(r"totals 2026-01 \(IST\), stored run #\d+ \(merchant-", lines[1])
    with sessionmaker(db_engine)() as s:
        p = plan(s, OWNER)
    expected = totals(p.txns, p.result.roles, *ist_month("2026-01"))
    assert money(out, "Spent") == format_inr(expected.spent_paise)
    assert money(out, "Paid back") == format_inr(expected.paid_back_paise)
    assert money(out, "Net") == format_inr(expected.net_paise)
    assert money(out, "Income") == format_inr(expected.income_paise)
    assert expected.income_paise > 0  # the owner file named an income source
    paid = {
        basis: sum(
            t.amount_paise
            for t in p.txns
            if p.result.roles[t.id].role == "payback" and p.result.roles[t.id].basis == basis
        )
        for basis in ("owner", "engine")
    }
    assert money(out, "Paid back") == format_inr(paid["owner"])  # confirmed only
    assert money(out, "To confirm") == format_inr(paid["engine"])
    assert expected.to_confirm_paise == paid["engine"]
    by_role = dict(re.findall(r"^  (\w+)\s+(\d+)$", out.split("transactions by role")[1], re.M))
    assert sum(map(int, by_role.values())) == len(p.txns) and by_role["ignored"] == "1"
    empty = run("totals", "--month", "2026-02")
    assert money(empty, "Spent") == "Rs 0.00" and re.search(r"^transactions\s+0$", empty, re.M)


def test_totals_refuses_stale_rows_bad_months_and_no_terminal(
    decided: dict, run, terminal, db_engine: Engine, monkeypatch
) -> None:
    assert "month must look like 2026-01" in run("totals", "--month", "2026-13", code=2)
    with sessionmaker(db_engine)() as s:
        s.execute(update(TxnDerived).where(TxnDerived.role == "spend").values(role="ignored"))
        s.commit()
    out = run("totals", "--month", "2026-01", code=1)
    assert "stored results are stale" in out and "row(s) differ" in out and "Rs" not in out
    run("recompute")
    with sessionmaker(db_engine)() as s:
        s.execute(update(DeriveRun).values(versions={"merchant": "old", "reconcile": "old"}))
        s.commit()
    assert "another engine version" in run("totals", "--month", "2026-01", code=1)
    with sessionmaker(db_engine)() as s:
        s.execute(delete(DeriveRun))
        s.commit()
    assert "no recompute has run yet" in run("totals", "--month", "2026-01", code=1)
    run("recompute")
    monkeypatch.setattr(cli, "is_terminal", lambda: False)
    out = run("totals", "--month", "2026-01", code=2)
    assert "only to a terminal" in out and "Rs" not in out
