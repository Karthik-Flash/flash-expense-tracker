"""D-101 and D-103 in the app: "Looks right" clears the check flag of a payment the generic
parser read; "Not a payment" (owner role ignored) works on any transaction and is undone by
"Count it again". Every write goes through ops.write, so it replays with its key. FAKE data."""

import json
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import OwnerRole, TxnCheck
from tests.apiclient import all_transactions, bearer, get, token
from tests.smsdata import write_backup

DOC = json.loads((Path(__file__).parent / "fixtures" / "generic_sms.json").read_text("utf-8"))


def send(client, method: str, path: str, key=None):
    headers = bearer(token())
    if key:
        headers["Idempotency-Key"] = str(key)
    return client.request(method, path, headers=headers)


def generic_data(run, tmp_path: Path) -> None:
    rows = [
        (f["sender"], f["body"], datetime.fromisoformat(f["received_at"]))
        for f in DOC["accepted"]
        if f["id"].endswith(("UPI-vpa", "debit-card", "salary-neft"))
    ]
    run("import-sms", "--input", str(write_backup(tmp_path / "g.xml", rows)))


def month_net(client, month: str) -> int:
    return get(client, "/api/v1/summary", month=month).json()["net_paise"]


def test_generic_rows_ask_for_a_check_until_looks_right(client, run, tmp_path, db_engine):
    generic_data(run, tmp_path)
    items = all_transactions(client)
    assert items and all(t["generic"] and t["check"] for t in items)
    debit = next(t for t in items if t["direction"] == "debit")
    assert debit["role"] == "spend"  # money that left counts (D-101)
    month = debit["time_utc"][:7]
    net = month_net(client, month)

    key = uuid.uuid4()
    first = send(client, "PUT", f"/api/v1/transactions/{debit['id']}/check", key)
    again = send(client, "PUT", f"/api/v1/transactions/{debit['id']}/check", key)
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    after = {t["id"]: t for t in all_transactions(client)}
    assert after[debit["id"]]["check"] is False and after[debit["id"]]["generic"] is True
    assert month_net(client, month) == net  # a check changes no total
    with sessionmaker(db_engine)() as s:
        assert s.scalar(select(func.count()).select_from(TxnCheck)) == 1
        row = s.get(TxnCheck, debit["id"])
        assert (row.owner_id, row.source) == (settings.owner_id, "app")


def test_not_a_payment_then_count_it_again(client, run, tmp_path, db_engine):
    generic_data(run, tmp_path)
    debit = next(t for t in all_transactions(client) if t["direction"] == "debit")
    month = debit["time_utc"][:7]
    net = month_net(client, month)
    path = f"/api/v1/transactions/{debit['id']}/ignore"

    assert send(client, "PUT", path, uuid.uuid4()).status_code == 200
    ignored = next(t for t in all_transactions(client) if t["id"] == debit["id"])
    assert ignored["role"] == "ignored" and ignored["check"] is False  # nothing left to check
    assert month_net(client, month) == net - debit["amount_paise"]  # the owner's own choice

    assert send(client, "DELETE", path, uuid.uuid4()).status_code == 200
    back = next(t for t in all_transactions(client) if t["id"] == debit["id"])
    assert back["role"] == "spend" and back["check"] is True
    assert month_net(client, month) == net
    assert send(client, "DELETE", path).status_code == 200  # nothing to undo: no change


def test_count_again_never_removes_another_owner_answer(client, data, db_engine):
    t = next(t for t in all_transactions(client) if t["direction"] == "credit")
    with sessionmaker(db_engine)() as s:
        s.add(OwnerRole(transaction_id=t["id"], owner_id=settings.owner_id, role="income",
                        decided_at=datetime.fromisoformat("2026-11-20T00:00:00+00:00"),
                        source="app"))  # fmt: skip
        s.commit()
    answer = send(client, "DELETE", f"/api/v1/transactions/{t['id']}/ignore")
    assert answer.status_code == 409
    with sessionmaker(db_engine)() as s:
        assert s.get(OwnerRole, t["id"]).role == "income"


def test_only_a_generic_payment_takes_a_check_and_not_a_payment_works_on_any(client, data):
    hdfc = next(t for t in all_transactions(client) if t["role"] == "spend")
    assert hdfc["generic"] is False and hdfc["check"] is False
    assert send(client, "PUT", f"/api/v1/transactions/{hdfc['id']}/check").status_code == 422
    assert send(client, "PUT", f"/api/v1/transactions/{hdfc['id']}/ignore").status_code == 200
    assert send(client, "PUT", "/api/v1/transactions/999999/ignore").status_code == 404
    assert send(client, "PUT", "/api/v1/transactions/999999/check").status_code == 404
