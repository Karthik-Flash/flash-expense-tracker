"""It's me and Investments (D-117, D-118): owner names, suggestions, answers and undo, over
the API. FAKE messages only. A suggestion alone never changes a total."""

from datetime import UTC, datetime

from tests.apiclient import bearer, get, put, token
from tests.smsdata import write_backup


def sent(rupees: str, to: str, ref: str, day: int = 10) -> tuple:
    body = (f"Sent Rs.{rupees}\nFrom HDFC Bank A/C *0001\nTo {to}\nOn {day:02d}/03/26\nRef {ref}\n"
            "Not You?\nCall 18000000001/SMS BLOCK UPI to 9000000001\n")  # fmt: skip
    return ("VM-HDFCBK-S", body, datetime(2026, 3, day, 6, 0, tzinfo=UTC))


def neft_in(rupees: str, by: str) -> tuple:
    body = (f"Update! INR {rupees} deposited in HDFC Bank A/c XX0001 on 11-MAR-26 for NEFT "
            f"Cr-TEST0000001-{by}-XXXXXXXXXX0009-TESTN00000000009.Avl bal INR 1,50,000.00. "
            "Cheque deposits in A/C are subject to clearing")  # fmt: skip
    return ("VM-HDFCBK-S", body, datetime(2026, 3, 11, 6, 0, tzinfo=UTC))


ROWS = [
    sent("2,000.00", "TEST OWNER NAME", "612400000001"),
    sent("3,000.00", "ZERODHA BROKING", "612400000002", 12),
    sent("500.00", "TEST CAFE", "612400000003", 13),
    neft_in("4,000.00", "TEST OWNER NAME"),
]


def month(client) -> dict:
    s = get(client, "/api/v1/sync/snapshot").json()
    return next(m for m in s["months"] if m["month"] == "2026-03")["summary"]


def snap(client) -> dict:
    return get(client, "/api/v1/sync/snapshot").json()


def test_suggest_answer_and_undo(client, run, tmp_path) -> None:
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", ROWS)))
    start = month(client)
    assert start["spent_paise"] == 5_500_00  # all three debits count until the owner says
    # Investments are suggested from the name alone; "Is this you?" needs the owner's names.
    kinds = {x["kind"] for x in snap(client)["todo"]["suggestions"]}
    assert kinds == {"investment"}
    assert (
        put(
            client, "/api/v1/profile/names", {"names": ["Test Owner Name", " T  Owner "]}
        ).status_code
        == 200
    )
    s = snap(client)
    assert s["profile"]["names"] == ["Test Owner Name", "T Owner"]
    suggested = {x["kind"]: x for x in s["todo"]["suggestions"]}
    assert set(suggested) == {"self", "investment"} and suggested["self"]["count"] == 2
    assert month(client) == start  # a suggestion alone moves nothing

    me = suggested["self"]["txn_id"]
    assert put(client, f"/api/v1/people/{me}/kind", {"kind": "self"}).status_code == 200
    after = month(client)
    assert after["spent_paise"] == 3_500_00  # the transfer to the owner left Spent
    assert after["paid_back_paise"] == start["paid_back_paise"] and after["income_paise"] == 0
    txns = {t["amount_paise"]: t["role"] for t in s["transactions"]}  # before
    now = {t["amount_paise"]: t["role"] for t in snap(client)["transactions"]}
    assert (now[2_000_00], now[4_000_00]) == ("self_transfer", "self_transfer")
    assert txns[2_000_00] == "spend"

    broker = suggested["investment"]["txn_id"]
    assert put(client, f"/api/v1/people/{broker}/kind", {"kind": "investment"}).status_code == 200
    assert month(client)["spent_paise"] == 500_00
    roles = {t["amount_paise"]: t["role"] for t in snap(client)["transactions"]}
    assert roles[3_000_00] == "investment"
    assert snap(client)["todo"]["suggestions"] == []  # answered: not asked again

    # Undo restores the state before: both back in Spent.
    for txn in (me, broker):
        undone = client.delete(f"/api/v1/people/{txn}/kind", headers=bearer(token()))
        assert undone.status_code == 200
    assert month(client)["spent_paise"] == start["spent_paise"]
    assert client.delete(f"/api/v1/people/{me}/kind", headers=bearer(token())).status_code == 404


def test_no_to_a_suggestion_is_remembered(client, run, tmp_path) -> None:
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", ROWS)))
    broker = snap(client)["todo"]["suggestions"][0]["txn_id"]
    assert (
        put(client, f"/api/v1/people/{broker}/suggestion", {"kind": "investment"}).status_code
        == 200
    )
    assert snap(client)["todo"]["suggestions"] == []
    assert put(client, f"/api/v1/people/{broker}/kind", {"kind": "friend"}).status_code == 422
    assert put(client, "/api/v1/profile/names", {"names": ["X"]}).status_code == 422
