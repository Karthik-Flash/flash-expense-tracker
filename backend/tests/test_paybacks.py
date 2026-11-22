"""Paybacks (5B-1, D-134): which credits are money back from a person, which payment each
pays back, and that none lowers Net without the owner's answer. FAKE values only.

The engine (reconcile-1.7.0) makes a credit a payback guess only from a person the owner
paid in the 90 days before; the owner's Friend answer (a person party) makes every credit of
that person a confirmed payback. credits.payback_links() says which payment a payback pays
back, for the transaction sheet; a link never changes a role or a total.
"""

from datetime import timedelta

import pytest

from app.engine.credits import PaybackRow, payback_links
from app.engine.reconcile import OwnAccount, OwnerData, Party, derive, totals
from tests.test_reconcile import DAY, T0, credit, txn

EVER = (T0 - 1000 * DAY, T0 + 1000 * DAY)
FRIEND = "test.friend@okaxis"
OTHER = "test.second@ybl"


def friend(*texts: str) -> OwnerData:
    """The owner answered Friend for this person (a party of kind person)."""
    return OwnerData(parties=(Party("person", texts=texts or (FRIEND,)),))


def links_of(txns, owner: OwnerData | None = None) -> list[tuple[int, int, str]]:
    """payback_links over a derive, as (payment, credit, status)."""
    result = derive(txns, owner)
    rows = []
    for t in txns:
        d, m = result.roles[t.id], result.merchants[t.id]
        person = f"p_{d.party}" if d.party is not None else m.merchant_key
        rows.append(PaybackRow(t.id, t.direction, t.amount_paise, t.txn_time_utc, person, d.role))
    return [(x.debit, x.credit, x.status) for x in payback_links(rows)]


def money(txns, owner: OwnerData | None = None):
    t = totals(txns, derive(txns, owner).roles, *EVER)
    return t.spent_paise, t.paid_back_paise, t.net_paise, t.to_confirm_paise


def test_a_payback_in_a_later_month_links_and_counts_in_its_own_month() -> None:
    pay = txn(1, party=FRIEND, amount_paise=60_000, txn_time_utc=T0)
    back = credit(FRIEND, id=2, amount_paise=60_000, txn_time_utc=T0 + 40 * DAY)  # next month
    assert links_of([pay, back]) == [(1, 2, "linked")]
    assert derive([pay, back]).roles[2].rule == "CR_person_signal"  # a guess: To confirm
    assert money([pay, back]) == (60_000, 0, 60_000, 60_000)  # Net unchanged until answered
    assert money([pay, back], friend()) == (60_000, 60_000, 0, 0)  # Friend: Paid back
    january = (T0 - 5 * DAY, T0 + 5 * DAY)  # the payment's month: no payback there
    assert totals([pay, back], derive([pay, back], friend()).roles, *january).paid_back_paise == 0


def test_partial_paybacks_each_link_to_the_one_payment() -> None:
    pay = txn(1, party=FRIEND, amount_paise=90_000)
    parts = [credit(FRIEND, id=i, amount_paise=30_000, txn_time_utc=T0 + i * DAY) for i in (2, 3)]
    assert links_of([pay, *parts], friend()) == [(1, 2, "linked"), (1, 3, "linked")]
    assert money([pay, *parts], friend()) == (90_000, 60_000, 30_000, 0)


def test_one_payment_paid_back_by_several_people_is_never_linked() -> None:
    """A split: the owner paid a shop, two friends pay their share. No person to match, so no
    link and no guess; once the owner answers Friend for each, both count as Paid back."""
    shop = txn(1, party="TEST CAFE SHOP", amount_paise=90_000)
    a = credit(FRIEND, id=2, amount_paise=30_000, txn_time_utc=T0 + DAY)
    b = credit(OTHER, id=3, amount_paise=30_000, txn_time_utc=T0 + DAY)
    txns = [shop, a, b]
    assert links_of(txns) == [] and links_of(txns, friend(FRIEND, OTHER)) == []
    roles = derive(txns).roles
    assert roles[2].rule == "CR_no_debit"  # a person signal, never paid: no guess
    assert {roles[2].role, roles[3].role} == {"uncertain"}
    assert money(txns) == (90_000, 0, 90_000, 0)
    both = OwnerData(parties=(Party("person", texts=(FRIEND,)), Party("person", texts=(OTHER,))))
    assert money(txns, both) == (90_000, 60_000, 30_000, 0)


def test_several_payments_for_one_credit_are_candidates_only() -> None:
    """One credit covering two payments to the same person: the engine does not pick one."""
    first = txn(1, party=FRIEND, amount_paise=40_000, txn_time_utc=T0)
    second = txn(2, party=FRIEND, amount_paise=50_000, txn_time_utc=T0 + DAY)
    back = credit(FRIEND, id=3, amount_paise=90_000, txn_time_utc=T0 + 2 * DAY)
    assert links_of([first, second, back], friend()) == [(1, 3, "candidate"), (2, 3, "candidate")]
    assert money([first, second, back], friend()) == (90_000, 90_000, 0, 0)  # counted all the same


def test_credits_adding_up_to_more_than_the_payment_are_candidates() -> None:
    pay = txn(1, party=FRIEND, amount_paise=50_000)
    backs = [credit(FRIEND, id=i, amount_paise=30_000, txn_time_utc=T0 + i * DAY) for i in (2, 3)]
    assert {s for *_, s in links_of([pay, *backs], friend())} == {"candidate"}


def test_the_same_person_under_joined_identities() -> None:
    """Paid by name, paid back from a UPI ID: one person once the owner joins them (D-096)."""
    pay = txn(1, party="TEST FRIEND NAME", channel="imps", amount_paise=20_000)
    back = credit(FRIEND, id=2, amount_paise=20_000, txn_time_utc=T0 + DAY)
    assert links_of([pay, back]) == []  # two people to the engine
    joined = OwnerData(parties=(Party("unsure", texts=("TEST FRIEND NAME", FRIEND)),))
    assert links_of([pay, back], joined) == [(1, 2, "linked")]
    assert derive([pay, back], joined).roles[2].basis == "engine"  # joined, not answered
    assert money([pay, back], joined) == (20_000, 0, 20_000, 20_000)
    assert links_of([pay, back], friend("TEST FRIEND NAME", FRIEND)) == [(1, 2, "linked")]


def test_a_credit_from_a_person_never_paid_is_not_a_payback() -> None:
    alone = credit(FRIEND, id=1, amount_paise=70_000)
    d = derive([alone]).roles[1]
    assert (d.role, d.rule) == ("uncertain", "CR_no_debit")
    assert money([alone]) == (0, 0, 0, 0)  # not even To confirm
    too_old = txn(2, party=FRIEND, txn_time_utc=T0 - 91 * DAY)
    assert derive([alone, too_old]).roles[1].role == "uncertain"
    assert links_of([alone, too_old], friend()) == []  # outside the 90 days: no link either


def test_a_merchant_refund_is_not_a_payback() -> None:
    bought = txn(1, party="TEST SHOP", channel="debit_card", amount_paise=40_000)
    refund = credit("TEST SHOP", id=2, type="refund", channel="debit_card", amount_paise=40_000,
                    txn_time_utc=T0 + DAY)  # fmt: skip
    plain = credit("TEST SHOP", id=3, channel="upi", amount_paise=10_000, txn_time_utc=T0 + DAY)
    roles = derive([bought, refund, plain]).roles
    assert (roles[2].role, roles[3].role) == ("refund", "uncertain")  # only the wording refunds
    assert links_of([bought, refund, plain]) == []
    assert money([bought, refund, plain]) == (0, 0, 0, 0)  # the refund lowers Spent


def test_money_from_the_owners_own_account_is_never_a_payback() -> None:
    """Under the owner's own name: with It's me (a party of kind self) or a listed account
    it is a transfer; with neither, at most a guess that never lowers Net."""
    out = txn(1, party="TEST OWNER NAME", channel="imps", amount_paise=80_000)
    back = credit("TEST OWNER NAME", id=2, channel="imps", amount_paise=80_000,
                  txn_time_utc=T0 + 2 * DAY)  # fmt: skip
    assert money([out, back]) == (80_000, 0, 80_000, 0)  # a bare name: CR_name_only, uncertain
    me = OwnerData(parties=(Party("self", texts=("TEST OWNER NAME",)),))
    assert {d.role for d in derive([out, back], me).roles.values()} == {"self_transfer"}
    assert money([out, back], me) == (0, 0, 0, 0) and links_of([out, back], me) == []
    listed = OwnerData(
        accounts=(OwnAccount("bank_account", "SBI", ("0009",), ("TEST OWNER NAME",)),)
    )
    assert {d.role for d in derive([out, back], listed).roles.values()} == {"self_transfer"}


def test_engine_paybacks_never_touch_paid_back_net_or_spent() -> None:
    """The engine's paybacks (CR_person_signal) are suggestions: To confirm only (D-076)."""
    txns = [txn(1, party=FRIEND, amount_paise=50_000)]
    txns += [credit(FRIEND, id=i, amount_paise=10_000, txn_time_utc=T0 + i * DAY) for i in (2, 3)]
    roles = derive(txns).roles
    assert {(roles[i].role, roles[i].basis) for i in (2, 3)} == {("payback", "engine")}
    t = totals(txns, roles, *EVER)
    assert (t.spent_paise, t.paid_back_paise, t.net_paise) == (50_000, 0, 50_000)
    assert t.to_confirm_paise == 20_000


@pytest.mark.parametrize("gap", [timedelta(0), 90 * DAY])
def test_the_window_ends_count(gap) -> None:
    pay = txn(1, party=FRIEND)
    back = credit(FRIEND, id=2, txn_time_utc=T0 + gap)
    assert links_of([pay, back], friend()) == [(1, 2, "linked")]


def test_only_spending_payments_and_payback_credits_take_part() -> None:
    ignored = txn(1, party=FRIEND)
    back = credit(FRIEND, id=2, txn_time_utc=T0 + DAY)
    owner = OwnerData(parties=friend().parties, roles={1: "ignored"})
    assert links_of([ignored, back], owner) == []  # not a payment: nothing to pay back
    income = OwnerData(parties=(Party("person", income=True, texts=(FRIEND,)),))
    assert links_of([txn(1, party=FRIEND), back], income) == []  # income is not a payback


# --- the app: the snapshot's payback links and the sheet answer -----------------------


def test_the_snapshot_links_the_friend_payback_and_answers_move_it(client, data) -> None:
    from tests.apiclient import bearer, get, put, token

    snap = client.get("/api/v1/sync/snapshot", headers=bearer(token())).json()
    by_id = {t["id"]: t for t in snap["transactions"]}
    (link,) = snap["paybacks"]
    debit, back = by_id[link["debit"]], by_id[link["credit"]]
    assert (debit["direction"], back["direction"], back["role"]) == ("debit", "credit", "payback")
    assert back["role_basis"] == "engine" and debit["person_id"] == back["person_id"]
    sender = next(s for s in snap["todo"]["senders"] if s["person_id"] == back["person_id"])
    before = get(client, "/api/v1/summary", month="2026-01").json()
    # "Paid back" on the sheet is the To-do answer: the same write, the same sender.
    assert put(client, f"/api/v1/senders/{sender['id']}", {"answer": "friend"}).status_code == 200
    after = client.get("/api/v1/sync/snapshot", headers=bearer(token())).json()
    assert sender["id"] not in {s["id"] for s in after["todo"]["senders"]}
    assert sender["id"] in {s["id"] for s in after["todo"]["answered"]}
    month = next(m["summary"] for m in after["months"] if m["month"] == "2026-01")
    assert month["paid_back_paise"] == before["paid_back_paise"] + back["amount_paise"]
    assert [x["status"] for x in after["paybacks"]] == ["linked"]
    # "Not paid back": Ignore, the To-do answer; the credit leaves every total.
    put(client, f"/api/v1/senders/{sender['id']}", {"answer": "ignore"})
    last = client.get("/api/v1/sync/snapshot", headers=bearer(token())).json()
    assert {t["id"]: t["role"] for t in last["transactions"]}[back["id"]] == "ignored"
    assert last["paybacks"] == []
