"""5B-1: To-do newest first (Part 1), and the owner review commands category-diff and
payback-review (D-137). FAKE data only; the CSV goes to a temp folder outside the repo."""

import csv
from pathlib import Path

from app.cli import REPO
from app.pipeline import review
from tests.apiclient import FRIEND_PAID, get
from tests.smsdata import WHEN, full_rows, write_backup
from tests.test_self_investment import sent
from tests.test_storage import PAIR


def newest_first(rows: list[dict], time: str, ident: str) -> bool:
    keys = [(r[time], r[ident]) for r in rows]
    return keys == sorted(keys, reverse=True)


def test_every_todo_list_is_newest_first(client, data, run, tmp_path) -> None:
    brokers = [
        sent("1,111.00", "ZERODHA BROKING", "612400000101", 5),
        sent("2,222.00", "GROWW INVEST TECH", "612400000102", 9),
        sent("3,333.00", "UPSTOX SECURITIES", "612400000103", 7),
    ]
    run("import-sms", "--input", str(write_backup(tmp_path / "brokers.xml", brokers)))
    todo = get(client, "/api/v1/sync/snapshot").json()["todo"]
    assert len(todo["senders"]) >= 2 and len(todo["merchants"]) >= 2
    for name in ("senders", "answered"):
        assert newest_first(todo[name], "last_time_utc", "txn_id"), name
    assert newest_first(todo["merchants"], "last_time_utc", "txn_id")
    assert len(todo["suggestions"]) == 3 and newest_first(
        todo["suggestions"], "last_time_utc", "txn_id"
    )
    assert [x["name"] for x in todo["suggestions"]] == [
        "Groww Invest Tech", "Upstox Securities", "Zerodha Broking",
    ]  # fmt: skip
    assert newest_first(todo["transfers"], "debit_time_utc", "debit")
    senders = get(client, "/api/v1/senders", status="all").json()  # the question queue too
    assert newest_first(senders, "last_time_utc", "txn_id")


def loaded(run, tmp_path: Path) -> None:
    rows = full_rows() + PAIR + [FRIEND_PAID]
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", rows)))


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_category_diff_counts_and_writes_the_changed_rows_only(run, tmp_path, db_engine) -> None:
    loaded(run, tmp_path)
    # A rent platform the 1.3.0 rules left Uncategorised; 1.4.0 knows it (D-155).
    rent = [sent("1,500.00", "RENTOK PAYMENTS", "612400000201", 3)]
    run("import-sms", "--input", str(write_backup(tmp_path / "rent.xml", rent)))
    out = tmp_path / "diff.csv"
    printed = run("category-diff", "--out", str(out))
    assert printed.startswith("category-diff (categorise-1.3.0 -> 1.4.0, read-only")
    rows = read(out)
    assert rows and list(rows[0]) == list(review.DIFF_COLUMNS)
    changed = int(
        next(x for x in printed.splitlines() if x.startswith("category changed")).split()[-1]
    )
    assert changed == len(rows) >= 1
    assert {(r["category_1_3_0"], r["category_1_4_0"]) for r in rows} == {
        ("uncategorised", "rent_hostel")
    }
    assert "uncategorised -> rent_hostel" in printed
    for r in rows:  # what the terminal shows is counts: never a name, amount or text
        assert r["counterparty"] not in printed and f" {r['amount_paise']}" not in printed
    again = tmp_path / "again.csv"
    run("category-diff", "--out", str(again))
    assert read(again) == rows  # read only: the same answer twice


def test_payback_review_counts_by_month_and_links(run, tmp_path) -> None:
    loaded(run, tmp_path)
    out = tmp_path / "paybacks.csv"
    printed = run("payback-review", "--out", str(out))
    assert "payback-review (reconcile-1.7.1, read-only" in printed
    rows = read(out)
    by = {r["answer"] for r in rows}
    assert by <= {"owner_confirmed", "engine_suggested", "unanswered"}
    suggested = [r for r in rows if r["answer"] == "engine_suggested"]
    assert len(suggested) == 1 and suggested[0]["link"] == "linked" and suggested[0]["pays_back"]
    assert "engine suggested" in printed and "2026-01" in printed
    for r in rows:
        assert not r["counterparty"] or r["counterparty"] not in printed


def test_both_refuse_an_out_path_inside_the_repo(run, tmp_path) -> None:
    loaded(run, tmp_path)
    for command in ("category-diff", "payback-review"):
        inside = REPO / "backend" / f"{command}-test.csv"
        assert "outside the repository" in run(command, "--out", str(inside), code=2)
        assert not inside.exists()
        missing = tmp_path / "no-such-folder" / "x.csv"
        assert "does not exist" in run(command, "--out", str(missing), code=2)


# A payment to a payee whose full UPI ID fits the masked sender of fixture H02 ("*test@oksbi",
# 7 Jan, Rs 2,50,000): reconcile-1.7.1 (D-145) makes that credit a payback guess, linked to it
# (the payment is larger: a smaller one would make it a candidate, more_than_paid).
MASKED_PAID = (
    "HDFCBK",
    "Sent Rs.3,33,333.00\nFrom HDFC Bank A/C *0001\nTo mytest@oksbi\nOn 02/01/26\n"
    "Ref 000000000078\nNot You?\nCall 18000000001/SMS BLOCK UPI to 9000000001\n",
    WHEN.replace(day=2),
)


def test_payback_review_counts_move_with_a_masked_payee(run, tmp_path, db_engine) -> None:
    from sqlalchemy.orm import sessionmaker

    from app.config import settings

    loaded(run, tmp_path)
    with sessionmaker(db_engine)() as s:
        before = review.payback_review(s, settings.owner_id)
    run("import-sms", "--input", str(write_backup(tmp_path / "m.xml", [MASKED_PAID])))
    with sessionmaker(db_engine)() as s:
        after = review.payback_review(s, settings.owner_id)
    print(
        f"\nfixtures: {dict(before.counts)} {dict(before.links)}"
        f" -> {dict(after.counts)} {dict(after.links)}"
    )
    assert after.counts["engine_suggested"] == before.counts["engine_suggested"] + 1
    assert after.counts["unanswered"] == before.counts["unanswered"] - 1
    assert after.links["linked"] == before.links["linked"] + 1
    assert after.counts["owner_confirmed"] == before.counts["owner_confirmed"] == 0
