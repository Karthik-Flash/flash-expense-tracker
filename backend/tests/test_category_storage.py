"""Categories in storage and on the command line: invariants I22 to I27. Fake values only."""

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app import cli
from app.config import settings
from app.db import Base
from app.engine.categorise import CATEGORIES, RULES, breakdown
from app.engine.money import format_inr
from app.engine.parsers import PARSERS
from app.engine.reconcile import ist_month, totals
from app.models import Label, OwnerCategory, Party, PartyText, Transaction, TxnDerived, TxnLabel
from app.pipeline.recompute import plan
from tests.smsdata import WHEN, full_rows, write_backup
from tests.test_cli import assert_no_values
from tests.test_owner_commands import private_lines
from tests.test_owner_load import private_values, write
from tests.test_pipeline import old_hdfc
from tests.test_storage import NOW, OWNER_FILE, PAIR, decide, derived_rows, stored

OWNER = settings.owner_id
FILE = {
    **OWNER_FILE,
    "parties": [
        *OWNER_FILE["parties"],
        {
            "label": "Test Canteen",
            "kind": "business",
            "category": "food_drinks",
            "texts": ["TEST MERCHANT"],
        },
    ],
}
LATER = (
    "HDFCBK",
    "Spent Rs.555.00 From HDFC Bank Card x0002 At TEST MERCHANT On 2026-01-25:12:05:00 "
    "Bal Rs.24000 Not You? Call 18000000001/SMS BLOCK DC 0002 to 9000000001",
    WHEN,
)


@pytest.fixture
def loaded(run, tmp_path: Path) -> str:
    return run("import-sms", "--input", str(write_backup(tmp_path / "all.xml", full_rows() + PAIR)))


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch):
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


def ids(engine: Engine, text: str) -> list[int]:
    with sessionmaker(engine)() as s:
        return list(
            s.scalars(
                select(Transaction.id)
                .where(Transaction.counterparty_raw == text, Transaction.type == "debit")
                .order_by(Transaction.id)
            )
        )


def category_decision(txn: int, slug: str) -> OwnerCategory:
    return OwnerCategory(
        transaction_id=txn, owner_id=OWNER, category=slug, decided_at=NOW, source="terminal"
    )


def merchants(out: str) -> list[tuple[str, str]]:
    return re.findall(r"^\[\d+/\d+\]\s+\d+ txns  (.*?)  ->  (.*)$", out, flags=re.M)


def review(run, terminal, choices: dict[str, str], *flags: str) -> str:
    names = [name for name, _ in merchants(run("category-review", "--list", *flags))]
    terminal([choices.get(name, "") for name in names])
    return run("category-review", *flags)


# --- invariants -----------------------------------------------------------------


def test_i22_one_category_per_active_transaction_from_the_list(loaded, db_engine) -> None:
    rows = stored(db_engine)
    assert rows and all(d.category in CATEGORIES for d in rows.values())
    assert all(d.category_rule in RULES and d.category_basis == "engine" for d in rows.values())
    assert {d.category for d in rows.values()} >= {"cash", "emi_loans", "people", "uncategorised"}


def test_i23_stored_breakdown_adds_up_to_spent(loaded, run, db_engine, tmp_path) -> None:
    run("owner-load", write(tmp_path, FILE))
    rows = stored(db_engine)
    with sessionmaker(db_engine)() as s:
        p = plan(s, OWNER)
    assert p.changes == 0
    assert {i: d.category for i, d in rows.items()} == {
        i: c.category for i, c in p.categories.items()
    }
    times = sorted(t.txn_time_utc for t in p.txns)
    for start, end in [ist_month("2026-01"), (times[3], times[-4]), ist_month("2026-02")]:
        parts = breakdown(p.txns, p.result.roles, rows_as_categories(rows), start, end)
        assert sum(parts.values()) == totals(p.txns, p.result.roles, start, end).spent_paise
    assert parts == {}


def rows_as_categories(rows: dict[int, TxnDerived]) -> dict:
    return {i: type("C", (), {"category": d.category})() for i, d in rows.items()}


def test_i24_transaction_decision_beats_party_default_beats_engine(
    loaded, run, db_engine, tmp_path
) -> None:
    first, second, third = ids(db_engine, "TEST MERCHANT")
    engine = {stored(db_engine)[i].category_rule for i in (first, second, third)}
    # categorise-1.3.0 (D-133): "merchant" is a business word, so never People (1.2.0: PERSON).
    assert engine == {"NONE"}
    run("owner-load", write(tmp_path, FILE))  # the party default
    decide(db_engine, category_decision(second, "gifts_donations"))  # a one-off
    run("recompute")
    rows = stored(db_engine)
    assert [
        (rows[i].category, rows[i].category_rule, rows[i].category_basis) for i in (first, second)
    ] == [
        ("food_drinks", "OWNER_party", "owner"),
        ("gifts_donations", "OWNER_txn", "owner"),
    ]
    assert rows[third].category == "food_drinks"  # the one-off did not change the merchant
    with sessionmaker(db_engine)() as s:
        assert (
            s.scalar(select(Party.category).where(Party.label == "Test Canteen")) == "food_drinks"
        )


def test_i25_recompute_twice_changes_nothing(loaded, run, db_engine, tmp_path) -> None:
    run("owner-load", write(tmp_path, FILE))
    before = derived_rows(db_engine)
    assert "nothing to change" in run("recompute")
    assert derived_rows(db_engine) == before


def test_i26_corrections_survive_reparse(run, db_engine, tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(PARSERS, "HDFC", old_hdfc())
    run("import-sms", "--input", str(write_backup(tmp_path / "all.xml", full_rows() + PAIR)))
    run("owner-load", write(tmp_path, FILE))
    first, second, _ = ids(db_engine, "TEST MERCHANT")
    decide(db_engine, category_decision(second, "gifts_donations"))
    run("recompute")
    monkeypatch.undo()
    out = run("reparse")
    assert re.search(r"^reparsed\s+[1-9]", out, flags=re.M)
    rows = stored(db_engine)
    assert (rows[first].category, rows[second].category) == ("food_drinks", "gifts_donations")
    with sessionmaker(db_engine)() as s:
        assert s.get(OwnerCategory, second).category == "gifts_donations"
        assert (
            s.scalar(select(Party.category).where(Party.label == "Test Canteen")) == "food_drinks"
        )


def test_i27_a_later_import_gets_the_merchants_category(
    loaded, run, terminal, db_engine, tmp_path
) -> None:
    review(run, terminal, {"Test Merchant": "food_drinks"})
    before = set(ids(db_engine, "TEST MERCHANT"))
    run("import-sms", "--input", str(write_backup(tmp_path / "later.xml", [LATER])))
    (new,) = set(ids(db_engine, "TEST MERCHANT")) - before
    d = stored(db_engine)[new]
    assert (d.category, d.category_rule, d.category_basis) == (
        "food_drinks",
        "OWNER_party",
        "owner",
    )


# --- owner file -----------------------------------------------------------------


def test_owner_load_takes_a_category_on_a_party(loaded, run, terminal, db_engine, tmp_path) -> None:
    bad = {
        "parties": [{"label": "Test A", "kind": "person", "category": "Food", "texts": ["TEST A"]}]
    }
    out = run("owner-load", write(tmp_path, bad), code=2)
    assert "parties[0].category: must be one of food_drinks" in out
    bad["parties"][0]["category"] = "food_drinks"
    bad["accounts"] = [
        {"label": "Test B", "kind": "wallet", "category": "cash", "texts": ["TEST B"]}
    ]
    assert "accounts[0]: 1 unknown key" in run("owner-load", write(tmp_path, bad), code=2)

    run("owner-load", write(tmp_path, OWNER_FILE))  # Test Friend: no category in the file
    review(run, terminal, {"Person_901": "rent_hostel"})  # the review sets one on the file party
    run("owner-load", write(tmp_path, OWNER_FILE))  # the file does not state it: it stays
    with sessionmaker(db_engine)() as s:
        friend = s.scalar(select(Party).where(Party.label == "Test Friend"))
        assert (friend.category, friend.source) == ("rent_hostel", "file")
    stated = json.loads(json.dumps(OWNER_FILE))
    stated["parties"][2]["category"] = "people"  # the file states one: the file wins
    run("owner-load", write(tmp_path, stated))
    with sessionmaker(db_engine)() as s:
        assert s.scalar(select(Party.category).where(Party.label == "Test Friend")) == "people"


# --- commands -------------------------------------------------------------------


def test_category_stats_prints_counts_and_percentages_only(
    loaded, run, db_engine, tmp_path
) -> None:
    run("owner-load", write(tmp_path, FILE))
    before = derived_rows(db_engine)
    out = run("category-stats")
    assert derived_rows(db_engine) == before
    assert out.startswith("category-stats (categorise-1.4.0, read-only)\n")
    block = out.split("spend transactions by category\n")[1].split("by rule")[0]
    counts = dict(re.findall(r"^  (\w+)\s+(\d+)$", block, flags=re.M))
    assert list(counts) == list(CATEGORIES)  # every category, in list order
    spend = int(re.search(r"^  spend transactions\s+(\d+)$", out, flags=re.M).group(1))
    assert sum(map(int, counts.values())) == spend and int(counts["food_drinks"]) >= 3
    assert re.search(r"^  share of spend transactions\s+\d+\.\d%$", out, flags=re.M)
    assert re.search(r"^  share of spend amount\s+\d+\.\d%$", out, flags=re.M)
    assert re.search(
        r"^  merchants covering 50%\s+\d+\n  merchants covering 80%\s+\d+\n", out, re.M
    )
    assert re.search(r"^  OWNER_party\s+[3-9]$", out, flags=re.M)  # the debits, and refunds
    assert re.search(r"^  stored rows that differ\s+0$", out, flags=re.M)
    assert_no_values(out)
    assert not sorted(v for v in private_values(FILE) if v in out)
    assert not any(k in out for k in ("brand:", "vpa:", "name:", "Rs"))


def test_category_review_refuses_without_a_terminal(loaded, run, monkeypatch) -> None:
    out = run("category-review", "--list", code=2)
    assert "only to a terminal" in out and cli.PRIVATE not in out
    assert_no_values(out)
    monkeypatch.setattr(cli, "is_terminal", lambda: True)
    assert "asks questions" in run("category-review", code=2)


def test_category_review_sets_a_default_on_a_merchant(loaded, run, terminal, db_engine) -> None:
    listed = run("category-review", "--list")
    lines = private_lines(listed)
    found = merchants(listed)
    assert lines[-2] == f"{len(found)} merchant(s)" and "?" not in listed
    counts = [int(n) for n in re.findall(r"^\[\d+/\d+\]\s+(\d+) txns", listed, flags=re.M)]
    assert counts == sorted(counts, reverse=True)  # most transactions first
    assert ("Test Merchant", "Uncategorised (engine, NONE)") in found
    only_open = merchants(run("category-review", "--list", "--uncategorised"))
    assert only_open and all(c.startswith("Uncategorised") for _, c in only_open)
    assert len(only_open) < len(found)

    number = str(list(CATEGORIES).index("groceries") + 1)
    out = review(run, terminal, {"Test Merchant": number, "Test Biller": "bills_recharges"})
    private_lines(out)
    assert " 2 groceries" in out and "answered: 2 merchant(s)" in out
    assert "saved: 2 merchant categor(ies)" in out
    assert re.search(r"^recompute run #\d+ \(owner\)$", out, flags=re.M)
    with sessionmaker(db_engine)() as s:
        party = s.scalar(select(Party).where(Party.label == "Test Merchant"))
        assert (party.kind, party.category, party.source) == ("business", "groceries", "terminal")
        text = s.scalar(select(PartyText).where(PartyText.party_id == party.id))
        assert (text.text, text.source) == ("TEST MERCHANT", "terminal")
    rows = stored(db_engine)
    assert {rows[i].category for i in ids(db_engine, "TEST MERCHANT")} == {"groceries"}
    assert {rows[i].category_basis for i in ids(db_engine, "TEST MERCHANT")} == {"owner"}
    after = dict(merchants(run("category-review", "--list")))
    assert after["Test Merchant"] == "Groceries (owner, OWNER_party)"

    terminal_answers = {"Test Merchant": "health", "Test Biller": "none"}  # update, and clear
    out = review(run, terminal, terminal_answers)
    with sessionmaker(db_engine)() as s:
        assert s.scalar(select(Party.category).where(Party.label == "Test Merchant")) == "health"
        assert s.scalar(select(Party.category).where(Party.label == "Test Biller")) is None
        assert len(list(s.scalars(select(Party)))) == 2  # updated, not created again
    terminal(["nonsense", "quit"])
    out = run("category-review")
    assert "answer a number from the list" in out and "answered: 0 merchant(s)" in out


def test_totals_shows_the_category_breakdown(loaded, run, terminal, db_engine, tmp_path) -> None:
    run("owner-load", write(tmp_path, FILE))
    out = run("totals", "--month", "2026-01")
    spent = re.search(r"^Spent\s+(-?Rs [\d,]+\.\d\d)$", out, flags=re.M).group(1)
    block = out.split("Spent by category\n")[1].split("transactions by role")[0]
    parts = dict(re.findall(r"^  (.+?)\s+(-?Rs [\d,]+\.\d\d)$", block, flags=re.M))
    assert parts.pop("adds up to") == spent
    assert set(parts) <= set(CATEGORIES.values()) and "Food & Drinks" in parts
    with sessionmaker(db_engine)() as s:
        p = plan(s, OWNER)
    fresh = breakdown(p.txns, p.result.roles, p.categories, *ist_month("2026-01"))
    assert parts == {CATEGORIES[slug]: format_inr(v) for slug, v in fresh.items() if v}


# --- labels, export and restore -------------------------------------------------


def labelled(engine: Engine) -> dict:
    with sessionmaker(engine)() as s:
        key = dict(s.execute(select(Transaction.id, Transaction.dedupe_key)).all())
        name = {x.id: x.name for x in s.scalars(select(Label))}
        return {
            "labels": sorted((x.name, x.source) for x in s.scalars(select(Label))),
            "txn_labels": sorted(
                (key[x.transaction_id], name[x.label_id], x.source)
                for x in s.scalars(select(TxnLabel))
            ),
            "categories": sorted(
                (key[c.transaction_id], c.category, c.decided_at, c.source)
                for c in s.scalars(select(OwnerCategory))
            ),
            "party_categories": sorted(
                (p.label, p.category, p.source) for p in s.scalars(select(Party))
            ),
        }


def test_export_and_restore_cover_categories_and_labels(
    loaded, run, db_engine: Engine, tmp_path: Path
) -> None:
    run("owner-load", write(tmp_path, FILE))
    first, second, _ = ids(db_engine, "TEST MERCHANT")
    with sessionmaker(db_engine)() as s:
        trip = Label(owner_id=OWNER, name="Test Trip", source="app")
        s.add(trip)
        s.flush()
        s.add_all(
            [
                TxnLabel(transaction_id=first, owner_id=OWNER, label_id=trip.id, source="app"),
                TxnLabel(transaction_id=second, owner_id=OWNER, label_id=trip.id, source="app"),
                category_decision(second, "gifts_donations"),
            ]
        )
        s.commit()
        trip_id = trip.id
    run("recompute")
    before, rows = labelled(db_engine), {i: d.category for i, d in stored(db_engine).items()}
    assert (
        rows[second] == "gifts_donations" and rows[first] == "food_drinks"
    )  # a label changes none
    with sessionmaker(db_engine)() as s, pytest.raises(Exception, match="(?i)unique|duplicate"):
        s.add(TxnLabel(transaction_id=first, owner_id=OWNER, label_id=trip_id, source="app"))
        s.commit()  # at most one label per transaction

    target = tmp_path / "export.json"
    out = run("owner-export", str(target))
    assert re.search(r"^category decisions\s+1\nlabels\s+1\nlabelled transactions\s+2$", out, re.M)
    assert "Test Trip" not in out
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["labels"][0]["name"] == "Test Trip"
    assert document["parties"][-1]["category"] == "food_drinks"

    Base.metadata.drop_all(db_engine)  # a rebuilt database: the same messages, other ids
    Base.metadata.create_all(db_engine)
    again = write_backup(tmp_path / "again.xml", list(reversed(full_rows() + PAIR)))
    run("import-sms", "--input", str(again))
    out = run("owner-load", str(target))
    assert int(re.search(r"^mapped to another id\s+(\d+)$", out, flags=re.M).group(1)) >= 3
    assert labelled(db_engine) == before
    with sessionmaker(db_engine)() as s:
        key = dict(s.execute(select(Transaction.dedupe_key, Transaction.id)).all())
    restored = stored(db_engine)
    gift = key[document["categories"][0]["dedupe_key"]]
    assert (restored[gift].category, restored[gift].category_rule) == (
        "gifts_donations",
        "OWNER_txn",
    )
    bad = document | {"categories": [{**document["categories"][0], "category": "nope"}]}
    assert "categories[0].category: must be one of" in run(
        "owner-load", write(tmp_path, bad), code=2
    )
