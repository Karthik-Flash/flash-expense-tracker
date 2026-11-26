"""Investments visible (5B-1, D-136): the Invested totals, the "Investment" tag and the owner's
setting "Count investments in Spent". FAKE messages only.

Only an owner-confirmed investment (role investment: the answer Investments) leaves Spent,
and only while the setting is off (the default). A suggested one ("Is this an investment?",
not answered) stays in Spent and shows as Invested (to confirm).
"""

import uuid

import pytest

from app.engine.categorise import breakdown, categorise
from app.engine.reconcile import OwnerData, Party, derive, totals
from tests.apiclient import bearer, get, put, token
from tests.smsdata import write_backup
from tests.test_reconcile import DAY, T0, credit, txn
from tests.test_self_investment import ROWS

EVER = (T0 - 1000 * DAY, T0 + 1000 * DAY)
BROKER = OwnerData(parties=(Party("investment", texts=("TEST BROKER",)),))


@pytest.mark.parametrize("invest", [False, True])
def test_engine_totals_for_each_setting(invest) -> None:
    txns = [
        txn(1, party="TEST BROKER", amount_paise=30_000),  # confirmed (party of kind investment)
        credit("TEST BROKER", id=2, amount_paise=5_000),  # money back from the broker
        txn(3, party="TEST CAFE", amount_paise=7_000),
    ]
    result = derive(txns, BROKER)
    t = totals(txns, result.roles, *EVER, invest)
    assert t.invested_paise == 30_000  # whatever the setting: the confirmed debit
    assert t.spent_paise == 7_000 + (30_000 if invest else 0)
    assert t.net_paise == t.spent_paise and t.income_paise == 0  # a broker credit: no total
    parts = breakdown(txns, result.roles, categorise(txns, BROKER, result), *EVER, invest)
    assert sum(parts.values()) == t.spent_paise
    assert parts.get("investments", 0) == (30_000 if invest else 0)


def test_a_suggested_investment_stays_in_spent() -> None:
    """No owner answer: role spend, in Spent either way; Invested is 0."""
    txns = [txn(1, party="ZERODHA BROKING", amount_paise=30_000)]
    roles = derive(txns).roles
    assert roles[1].role == "spend"
    for invest in (False, True):
        t = totals(txns, roles, *EVER, invest)
        assert (t.spent_paise, t.invested_paise) == (30_000, 0)


def month(client) -> dict:
    s = get(client, "/api/v1/sync/snapshot").json()
    return next(m for m in s["months"] if m["month"] == "2026-03")["summary"]


def snap(client) -> dict:
    return get(client, "/api/v1/sync/snapshot").json()


def setting(client, on: bool, key: str | None = None):
    headers = bearer(token()) | {"Idempotency-Key": key or str(uuid.uuid4())}
    body = {"count_investments_in_spent": on}
    return client.put("/api/v1/profile/settings", headers=headers, json=body)


def test_invested_totals_tag_and_setting_over_the_api(client, run, tmp_path) -> None:
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", ROWS)))
    start = month(client)
    # 5G (D-156): investments count in Spent until the owner says otherwise.
    assert start["investments_in_spent"] is True
    assert snap(client)["profile"]["settings"] == {"count_investments_in_spent": True}
    # Suggested only: in Spent, shown as Invested (to confirm); tagged "suggested".
    assert (start["spent_paise"], start["invested_paise"]) == (5_500_00, 0)
    assert start["invested_to_confirm_paise"] == 3_000_00
    tags = {t["amount_paise"]: t["investment"] for t in snap(client)["transactions"]}
    assert tags == {2_000_00: None, 3_000_00: "suggested", 500_00: None, 4_000_00: None}

    broker = snap(client)["todo"]["suggestions"][0]["txn_id"]
    assert put(client, f"/api/v1/people/{broker}/kind", {"kind": "investment"}).status_code == 200
    on = month(client)  # confirmed, and counted in Spent by default
    assert (on["spent_paise"], on["invested_paise"], on["investments_in_spent"]) == (
        5_500_00, 3_000_00, True,
    )  # fmt: skip
    assert on["invested_to_confirm_paise"] == 0
    assert sum(c["amount_paise"] for c in on["categories"]) == on["spent_paise"]
    assert {c["slug"]: c["amount_paise"] for c in on["categories"]}["investments"] == 3_000_00
    assert {t["amount_paise"]: t["investment"] for t in snap(client)["transactions"]}[
        3_000_00
    ] == "confirmed"

    # The setting off: through the outbox (an Idempotency-Key), the snapshot carries it.
    key = str(uuid.uuid4())
    answer = setting(client, False, key)
    assert answer.status_code == 200, answer.text
    assert answer.json()["settings"] == {"count_investments_in_spent": False}  # no recompute
    assert setting(client, False, key).json() == answer.json()  # a replay writes nothing
    off = month(client)
    assert (off["spent_paise"], off["invested_paise"], off["investments_in_spent"]) == (
        2_500_00, 3_000_00, False,
    )  # fmt: skip
    assert snap(client)["profile"]["settings"] == {"count_investments_in_spent": False}
    assert get(client, "/api/v1/summary", month="2026-03").json() == off  # the route agrees
    assert setting(client, True).status_code == 200  # and on again, chosen this time
    assert month(client) == on


def test_the_setting_is_per_user_and_checked(client, data) -> None:
    from tests.apiclient import SUB_B

    headers = bearer(token(SUB_B)) | {"Idempotency-Key": str(uuid.uuid4())}
    assert client.put("/api/v1/profile/settings", headers=headers,
                      json={"count_investments_in_spent": False}).status_code == 200  # fmt: skip
    assert get(client, "/api/v1/sync/snapshot").json()["profile"]["settings"] == {
        "count_investments_in_spent": True
    }  # A's is untouched (the default)
    for bad in ({}, {"count_investments_in_spent": "yes"}, {"x": True}):
        response = client.put("/api/v1/profile/settings", headers=bearer(token()), json=bad)
        assert response.status_code == 422
