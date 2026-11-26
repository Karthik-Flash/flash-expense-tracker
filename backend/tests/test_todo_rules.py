"""To-do (5G-D, D-156): Leave as is, This is income, and one answer clearing a question
everywhere. FAKE data only."""

from tests.apiclient import delete, get, put


def snap(client) -> dict:
    return get(client, "/api/v1/sync/snapshot").json()


def snap_month(time_utc: str) -> str:
    from datetime import datetime

    from app.engine.reconcile import IST

    return datetime.fromisoformat(time_utc).astimezone(IST).strftime("%Y-%m")


def test_leave_as_is_stops_the_category_question_and_undo_brings_it_back(client, data) -> None:
    first = snap(client)
    m = first["todo"]["merchants"][0]
    before = get(client, f"/api/v1/transactions/{m['txn_id']}").json()
    month = snap_month(before["time_utc"])
    spent = get(client, "/api/v1/summary", month=month).json()["spent_paise"]
    path = f"/api/v1/transactions/{m['txn_id']}/leave"
    assert put(client, path, {"question": "category"}).status_code == 200
    after = snap(client)
    assert m["name"] not in {x["name"] for x in after["todo"]["merchants"]}  # not asked
    t = get(client, f"/api/v1/transactions/{m['txn_id']}").json()
    assert (t["category"], t["role"], t["amount_paise"]) == (
        before["category"], before["role"], before["amount_paise"],
    )  # fmt: skip
    assert get(client, "/api/v1/summary", month=month).json()["spent_paise"] == spent
    (left,) = after["todo"]["left"]
    assert left["person_id"] == t["person_id"] and left["category"] and not left["sender"]
    # Undo (the sheet's "Ask again"): the question is back.
    assert delete(client, path).status_code == 200
    again = snap(client)
    assert m["name"] in {x["name"] for x in again["todo"]["merchants"]}
    assert again["todo"]["left"] == []
    assert put(client, path, {"question": "maybe"}).status_code == 422


def test_leave_as_is_stops_who_sent_you_money_everywhere(client, data) -> None:
    first = snap(client)
    s = first["todo"]["senders"][0]
    month = snap_month(s["last_time_utc"])
    summary = get(client, "/api/v1/summary", month=month).json()
    roles = {t["id"]: t["role"] for t in first["transactions"]}
    path = f"/api/v1/transactions/{s['txn_id']}/leave"
    assert put(client, path, {"question": "sender"}).status_code == 200
    after = snap(client)
    assert s["id"] not in {x["id"] for x in after["todo"]["senders"]}  # To-do
    answered = {x["id"]: x for x in after["todo"]["answered"]}
    assert answered[s["id"]]["status"] == "left"  # shown with the answered ones, to undo
    assert s["id"] not in {x["id"] for x in get(client, "/api/v1/senders").json()}  # the queue
    now = get(client, "/api/v1/summary", month=month).json()
    assert now["to_confirm"]["senders"] == summary["to_confirm"]["senders"] - 1  # the count
    # Amounts and roles unchanged: Net, Spent and To confirm in money stay.
    assert (now["net_paise"], now["spent_paise"], now["to_confirm"]["amount_paise"]) == (
        summary["net_paise"], summary["spent_paise"], summary["to_confirm"]["amount_paise"],
    )  # fmt: skip
    assert {t["id"]: t["role"] for t in after["transactions"]} == roles
    assert delete(client, path).status_code == 200
    assert s["id"] in {x["id"] for x in snap(client)["todo"]["senders"]}


def test_this_is_income_for_one_credit_counts_in_income(client, data) -> None:
    s = snap(client)["todo"]["senders"][0]
    credit = get(client, f"/api/v1/transactions/{s['txn_id']}").json()
    month = snap_month(credit["time_utc"])
    before = get(client, "/api/v1/summary", month=month).json()
    path = f"/api/v1/transactions/{credit['id']}/payback"
    assert put(client, path, {"answer": "income"}).status_code == 200
    after = get(client, "/api/v1/summary", month=month).json()
    assert after["income_paise"] == before["income_paise"] + credit["amount_paise"]
    assert after["spent_paise"] == before["spent_paise"]
    assert get(client, f"/api/v1/transactions/{credit['id']}").json()["role"] == "income"
    answers = snap(client)["profile"]["credit_answers"]
    assert answers[str(credit["id"])] == "income"
    # Always from <name>: the person-level answer (To-do's Income) still works beside it.
    body = {"answer": "income", "label": "Test Salary"}
    assert put(client, f"/api/v1/senders/{s['id']}", body).status_code == 200
    assert s["id"] not in {x["id"] for x in snap(client)["todo"]["senders"]}


def test_an_answer_in_the_sheet_clears_to_do_too(client, data) -> None:
    """Answering anywhere removes the question everywhere: a category for all payments to a
    payee, given in a payment's sheet, takes that payee out of "Pick a category"."""
    m = snap(client)["todo"]["merchants"][0]
    body = {"category": "groceries", "scope": "merchant"}
    assert put(client, f"/api/v1/transactions/{m['txn_id']}/category", body).status_code == 200
    assert m["name"] not in {x["name"] for x in snap(client)["todo"]["merchants"]}
