"""Learn from the owner (premium C, D-149): "All payments to <name>" rules and per-credit
Paid back answers. FAKE data only."""

from datetime import timedelta

from tests.apiclient import delete, get, put
from tests.test_devices import UPI_SENT, WHEN, register, sms, upload


def payments(client, name: str) -> list[dict]:
    return [
        t
        for t in get(client, "/api/v1/transactions", month="2026-03", limit=200).json()["items"]
        if (t["display_name"] or "").casefold() == name.casefold()
    ]


def summary(client, month: str = "2026-03") -> dict:
    return get(client, "/api/v1/summary", month=month).json()


def test_a_rule_covers_past_and_new_payments_and_one_offs_beat_it(client, run) -> None:
    token = register(client).json()["token"]
    for n, ref in enumerate(("612300000011", "612300000012"), start=1):
        body = UPI_SENT.replace("612300000002", ref)
        upload(client, token, sms(body, when=WHEN + timedelta(hours=n), n=n))
    first, second = payments(client, "Test Cafe New")
    engine = first["category"]
    spent = summary(client)["spent_paise"]
    # All payments to Test Cafe New: a rule, past and future.
    rule = {"category": "groceries", "scope": "merchant"}
    assert put(client, f"/api/v1/transactions/{first['id']}/category", rule).status_code == 200
    assert {t["category"] for t in payments(client, "Test Cafe New")} == {"groceries"}
    assert summary(client)["spent_paise"] == spent  # a category never moves Spent
    body = UPI_SENT.replace("612300000002", "612300000013")
    upload(client, token, sms(body, when=WHEN + timedelta(hours=5), n=3))
    rows = payments(client, "Test Cafe New")
    assert len(rows) == 3 and {t["category"] for t in rows} == {"groceries"}  # the new one too
    # Just this payment beats the rule; the rule beats the engine.
    one = {"category": "health", "scope": "transaction"}
    assert put(client, f"/api/v1/transactions/{second['id']}/category", one).status_code == 200
    by_id = {t["id"]: t["category"] for t in payments(client, "Test Cafe New")}
    assert by_id[second["id"]] == "health" and by_id[first["id"]] == "groceries"
    # Rules survive reparse and recompute.
    run("reparse")
    run("recompute")
    by_id = {t["id"]: t["category"] for t in payments(client, "Test Cafe New")}
    assert by_id[second["id"]] == "health" and list(by_id.values()).count("groceries") == 2
    # Your rules: listed, and undone.
    snap = get(client, "/api/v1/sync/snapshot").json()
    (listed,) = snap["profile"]["rules"]
    assert listed["category"] == "groceries" and listed["payments"] == 3
    assert delete(client, f"/api/v1/rules/{listed['party_id']}").status_code == 200
    by_id = {t["id"]: t["category"] for t in payments(client, "Test Cafe New")}
    assert by_id[second["id"]] == "health"  # the one-off stays
    assert {v for k, v in by_id.items() if k != second["id"]} == {engine}
    assert get(client, "/api/v1/sync/snapshot").json()["profile"]["rules"] == []
    assert delete(client, f"/api/v1/rules/{listed['party_id']}").status_code == 200  # same answer
    assert delete(client, "/api/v1/rules/999999").status_code == 404


def test_a_per_credit_answer_beats_the_person_level_one(client, data) -> None:
    """Net moves only on the owner's answers: the engine's guess is To confirm; the person's
    Paid back lowers Net; Not paid back for one credit lifts it again whatever the person-level
    answer later says; forgetting it hands back to the person-level answer."""
    month = "2026-01"
    listed = get(client, "/api/v1/senders").json()
    payback = next(s for s in listed if s["role"] == "payback")
    credit = payback["txn_id"]
    amount = get(client, f"/api/v1/transactions/{credit}").json()["amount_paise"]
    start = summary(client, month)
    assert put(client, f"/api/v1/senders/{payback['id']}", {"answer": "friend"}).status_code == 200
    friend = summary(client, month)
    assert friend["net_paise"] == start["net_paise"] - payback["total_paise"]
    path = f"/api/v1/transactions/{credit}/payback"
    assert put(client, path, {"answer": "not_paid_back"}).status_code == 200
    one = summary(client, month)
    assert one["net_paise"] == friend["net_paise"] + amount
    assert one["spent_paise"] == start["spent_paise"]
    # The person-level answer changes twice: the per-credit answer stays.
    assert put(client, f"/api/v1/senders/{payback['id']}", {"answer": "ignore"}).status_code == 200
    assert put(client, f"/api/v1/senders/{payback['id']}", {"answer": "friend"}).status_code == 200
    assert summary(client, month)["net_paise"] == one["net_paise"]
    answers = get(client, "/api/v1/sync/snapshot").json()["profile"]["credit_answers"]
    assert answers == {str(credit): "not_paid_back"}
    # Forget it: the person-level answer (Paid back) decides again.
    assert delete(client, path).status_code == 200
    assert summary(client, month)["net_paise"] == friend["net_paise"]
    # Only money in; another owner's credit is not found; a bad answer is 422.
    debit = next(
        t
        for t in get(client, "/api/v1/transactions", month=month, limit=200).json()["items"]
        if t["direction"] == "debit"
    )
    paid = put(client, f"/api/v1/transactions/{debit['id']}/payback", {"answer": "paid_back"})
    assert paid.status_code == 422
    assert put(client, path, {"answer": "maybe"}).status_code == 422
    assert put(client, path, {"answer": "paid_back"}, "user-b").status_code in (403, 404)


def test_a_per_credit_paid_back_lowers_net_without_a_person_answer(client, data) -> None:
    month = "2026-01"
    payback = next(s for s in get(client, "/api/v1/senders").json() if s["role"] == "payback")
    credit = get(client, f"/api/v1/transactions/{payback['txn_id']}").json()
    start = summary(client, month)
    path = f"/api/v1/transactions/{credit['id']}/payback"
    assert put(client, path, {"answer": "paid_back"}).status_code == 200
    after = summary(client, month)
    assert after["net_paise"] == start["net_paise"] - credit["amount_paise"]
    assert after["spent_paise"] == start["spent_paise"]
