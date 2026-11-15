"""Reconcile links: duplicates and pair linking (reconcile-1.1.0). Fake values only."""

import random
from dataclasses import replace
from datetime import timedelta

import pytest

from app.engine.reconcile import (
    LINK_KINDS,
    LINK_REASONS,
    LINK_RULES,
    Link,
    OwnerData,
    Result,
    Txn,
    derive,
    totals,
)
from tests.test_reconcile import DAY, OWNER, T0, credit, txn

SEC = timedelta(seconds=1)
MIN = timedelta(minutes=1)
HOUR = timedelta(hours=1)
EVER = (T0 - 1000 * DAY, T0 + 1000 * DAY)


def autopay(id: int, at=T0, **fields) -> Txn:
    """AutoPay success SMS: card last 4, a mandate ID as its reference, no real time."""
    values = {
        "party": "TEST STREAMING",
        "channel": "e_mandate",
        "account_last4": "0002",
        "reference": "TESTMANDATE01",
        "hints": ("mandate_reference",),
    }
    return txn(id, txn_time_utc=at, **(values | fields))


def card(id: int, at=T0, **fields) -> Txn:
    values = {"party": "TEST STREAMING BLR", "channel": "debit_card", "account_last4": "0002"}
    return txn(id, txn_time_utc=at, **(values | fields))


def refund(id: int, at=T0, **fields) -> Txn:
    values = {"party": "TEST SHOP", "channel": "debit_card", "account_last4": "0002"}
    return credit(id=id, type="refund", txn_time_utc=at, **(values | fields))


def brief(result: Result) -> list[tuple]:
    return [
        (x.kind, x.txn_a, x.txn_b, x.status, x.rule, x.reason, x.decided_by) for x in result.links
    ]


def roles(result: Result) -> dict[int, str]:
    return {i: d.role for i, d in result.roles.items()}


def spent(txns: list[Txn], result: Result) -> int:
    return totals(txns, result.roles, *EVER).spent_paise


def links(decisions: dict) -> OwnerData:
    return OwnerData(links=decisions)


# --- duplicates (B1) ------------------------------------------------------------


def test_unique_autopay_and_card_pair_links_and_counts_once() -> None:
    txns = [autopay(1, T0 + 3 * MIN), card(2)]
    result = derive(txns)
    assert brief(result) == [
        ("duplicate", 1, 2, "linked", "DUP_autopay_card", "unique_10min", "engine")
    ]
    primary, other = result.roles[2], result.roles[1]  # the earlier one is the primary
    assert (primary.role, primary.rule, primary.duplicate_of) == ("spend", "DB_spend", None)
    assert (other.role, other.rule, other.basis, other.duplicate_of) == (
        "duplicate",
        "DUP_autopay_card",
        "engine",
        2,
    )
    assert other.reasons == ("DUP_autopay_card", "DB_spend")
    assert spent(txns, result) == 10_000  # once, not twice
    same_time = derive([autopay(5), card(4)])
    assert roles(same_time) == {4: "spend", 5: "duplicate"}  # same time: the lowest id


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({}, "linked"),
        ({"party": "SWIGGY"}, "linked"),  # one brand, one plain name
        ({"bank": "SBI"}, None),
        ({"account_last4": "0001"}, None),
        ({"amount_paise": 10_001}, None),
        ({"direction": "credit", "type": "credit"}, None),
        ({"channel": "upi"}, "candidate"),  # not a card spend: only the same-amount rule
        ({"channel": "credit_card"}, "linked"),
        ({"account_last4": None}, None),
    ],
)
def test_autopay_card_pair_needs_every_field(change: dict, expected: str | None) -> None:
    result = derive([autopay(1), card(2, T0 + MIN, **change)])
    assert [x.status for x in result.links] == ([expected] if expected else [])
    if expected == "candidate":
        assert result.links[0].rule == "DUP_same_amount"
    if expected != "linked":
        assert "duplicate" not in roles(result).values()


def test_two_different_brands_are_not_an_autopay_card_pair() -> None:
    both = derive([autopay(1, party="NETFLIX"), card(2, T0 + MIN, party="NETFLIX COM")])
    assert both.links[0].status == "linked"
    other = derive([autopay(1, party="NETFLIX"), card(2, T0 + MIN, party="SPOTIFY")])
    assert brief(other) == [
        ("duplicate", 1, 2, "candidate", "DUP_same_amount", "same_amount", "engine")
    ]


@pytest.mark.parametrize(
    ("gap", "status", "reason"),
    [
        (10 * MIN - SEC, "linked", "unique_10min"),
        (10 * MIN, "linked", "unique_10min"),
        (10 * MIN + SEC, "candidate", "within_24h"),
        (24 * HOUR, "candidate", "within_24h"),
        (24 * HOUR + SEC, None, None),
    ],
)
def test_autopay_card_windows_at_10_minutes_and_24_hours(gap, status, reason) -> None:
    for txns in ([autopay(1), card(2, T0 + gap)], [autopay(1, T0 + gap), card(2)]):
        result = derive(txns)
        assert [(x.status, x.reason) for x in result.links] == (
            [(status, reason)] if status else []
        )
        assert ("duplicate" in roles(result).values()) == (status == "linked")


def test_one_to_two_gives_candidates_only_nothing_greedy() -> None:
    txns = [autopay(1), card(2, T0 + MIN), card(3, T0 + 9 * MIN)]  # 2 is far closer than 3
    result = derive(txns)
    assert brief(result) == [
        ("duplicate", 1, 2, "candidate", "DUP_autopay_card", "several_partners", "engine"),
        ("duplicate", 1, 3, "candidate", "DUP_autopay_card", "several_partners", "engine"),
        ("duplicate", 2, 3, "candidate", "DUP_same_amount", "same_amount", "engine"),
    ]
    assert set(roles(result).values()) == {"spend"} and spent(txns, result) == 30_000
    two_to_one = derive([autopay(1), autopay(2, T0 + MIN, reference="TESTMANDATE02"), card(3)])
    assert [x.status for x in two_to_one.links] == ["candidate"] * 3
    late_partner = derive([autopay(1), card(2, T0 + MIN), card(3, T0 + 5 * HOUR)])
    assert [(x.txn_b, x.status, x.reason) for x in late_partner.links] == [
        (2, "candidate", "several_partners"),  # a second card spend within 24 hours is enough
        (3, "candidate", "within_24h"),
    ]


def test_three_in_a_chain_are_all_candidates() -> None:
    txns = [card(1), autopay(2, T0 + 8 * MIN), card(3, T0 + 16 * MIN)]  # 1 and 3: 16 min apart
    result = derive(txns)
    assert [(x.txn_a, x.txn_b, x.status, x.reason) for x in result.links] == [
        (1, 2, "candidate", "several_partners"),
        (2, 3, "candidate", "several_partners"),
    ]
    assert set(roles(result).values()) == {"spend"} and spent(txns, result) == 30_000


def test_same_amount_pair_is_only_ever_a_candidate() -> None:
    def pair(gap=5 * MIN, **second) -> Result:
        return derive([txn(1, reference="000000000001"), txn(2, txn_time_utc=T0 + gap, **second)])

    assert brief(pair(reference="000000000002")) == [
        ("duplicate", 1, 2, "candidate", "DUP_same_amount", "different_references", "engine")
    ]
    assert pair().links[0].reason == "same_amount"  # one side has no reference
    assert pair(10 * MIN).links and not pair(10 * MIN + SEC).links
    for other in ({"bank": "SBI"}, {"account_last4": "0002"}, {"amount_paise": 1}):
        assert not pair(**other).links
    assert not pair(direction="credit", type="credit", party="TEST").links
    result = pair(reference="000000000002")
    assert roles(result) == {1: "spend", 2: "spend"}  # a candidate changes no role
    both_null = derive([txn(1, account_last4=None), txn(2, account_last4=None)])
    assert both_null.links[0].rule == "DUP_same_amount"  # as recorded at import (D-047)


def test_a_mandate_id_is_never_a_match_key() -> None:
    month_apart = [autopay(1), autopay(2, T0 + 30 * DAY)]  # the same mandate ID every month
    assert not derive(month_apart).links and spent(month_apart, derive(month_apart)) == 20_000
    for second in ("TESTMANDATE01", "TESTMANDATE02"):  # a mandate ID is no per-payment reference
        close = derive([autopay(1), autopay(2, T0 + MIN, reference=second)])
        assert brief(close) == [
            ("duplicate", 1, 2, "candidate", "DUP_same_amount", "same_amount", "engine")
        ]
    shared = [autopay(1), card(2, T0 + MIN, amount_paise=20_000, reference="TESTMANDATE01")]
    assert not derive(shared).links  # an equal reference links nothing by itself


def test_owner_same_links_and_the_group_counts_once() -> None:
    txns = [txn(1), txn(2, txn_time_utc=T0 + MIN), txn(3, txn_time_utc=T0 + 2 * DAY)]
    result = derive(txns, links({("duplicate", 1, 2): "same", ("duplicate", 2, 3): "same"}))
    assert brief(result) == [
        ("duplicate", 1, 2, "linked", "DUP_same_amount", "owner_same", "owner"),
        ("duplicate", 2, 3, "linked", "OWNER_link", "owner_same", "owner"),  # no rule saw it
    ]
    assert roles(result) == {1: "spend", 2: "duplicate", 3: "duplicate"}
    assert {result.roles[i].duplicate_of for i in (2, 3)} == {1}
    assert (result.roles[3].rule, result.roles[3].basis) == ("OWNER_link", "owner")
    assert spent(txns, result) == 10_000


def test_owner_different_removes_the_pair_for_good() -> None:
    txns = [autopay(1), card(2, T0 + MIN)]
    different = links({("duplicate", 1, 2): "different"})
    assert derive(txns).links[0].status == "linked"
    for legacy in ((), [(1, 2)], [(2, 1)]):  # not proposed again by any rule, nor from import
        result = derive(txns, different, legacy)
        assert result.links == () and roles(result) == {1: "spend", 2: "spend"}
    three = [autopay(1), card(2, T0 + MIN), card(3, T0 + 2 * MIN)]
    solved = derive(three, links({("duplicate", 1, 3): "different"}))
    assert [(x.txn_a, x.txn_b, x.status) for x in solved.links] == [
        (1, 2, "linked"),  # the owner removed the other partner, so this pair is unique now
        (2, 3, "candidate"),
    ]


def test_owner_same_elsewhere_keeps_a_rule_from_linking() -> None:
    txns = [autopay(1), card(2, T0 + MIN), txn(9, txn_time_utc=T0 + DAY)]
    result = derive(txns, links({("duplicate", 1, 9): "same"}))
    assert [(x.txn_b, x.status, x.reason, x.decided_by) for x in result.links] == [
        (2, "candidate", "several_partners", "engine"),
        (9, "linked", "owner_same", "owner"),
    ]
    assert roles(result) == {1: "spend", 2: "spend", 9: "duplicate"}


def test_owner_link_decisions_that_cannot_hold_are_refused() -> None:
    txns = [txn(1), txn(2, txn_time_utc=T0 + MIN), txn(3, txn_time_utc=T0 + 2 * MIN)]
    chain = {
        ("duplicate", 1, 2): "same",
        ("duplicate", 2, 3): "same",
        ("duplicate", 1, 3): "different",
    }
    with pytest.raises(ValueError, match="contradict"):
        derive(txns, links(chain))
    for key, verdict in [
        (("duplicate", 2, 1), "same"),  # ids out of order
        (("card_bill", 1, 2), "same"),  # not a link kind yet
        (("duplicate", 1, 2), "yes"),  # the draft wording
    ]:
        with pytest.raises(ValueError, match="owner link decision"):
            derive(txns, links({key: verdict}))
    unfit = [
        ("duplicate", txn(2, amount_paise=1)),
        ("duplicate", credit("TEST", id=2)),
        ("self_transfer", txn(2)),  # two debits
        ("self_transfer", credit("TEST", id=2, amount_paise=1)),
        ("refund", txn(2)),
        ("refund", credit("TEST", id=2, amount_paise=10_001)),  # more than the purchase
        ("fd", credit("TEST", id=2, amount_paise=1)),
    ]
    for kind, second in unfit:
        with pytest.raises(ValueError, match="does not fit the kind"):
            derive([txn(1), second], links({(kind, 1, 2): "same"}))
        different = derive([txn(1), second], links({(kind, 1, 2): "different"}))
        assert not [x for x in different.links if x.kind == kind]


def test_verdict_for_an_id_not_in_the_input_is_ignored() -> None:
    txns = [autopay(1), card(2, T0 + MIN)]
    decisions = {
        ("duplicate", 1, 99): "same",
        ("duplicate", 2, 98): "different",
        ("fd", 97, 99): "same",
    }
    assert derive(txns, links(decisions), [(1, 99), (98, 99)]) == derive(txns)


def test_owner_role_decision_beats_a_duplicate_link() -> None:
    result = derive([autopay(1, T0 + MIN), card(2)], OwnerData(roles={1: "ignored"}))
    assert result.links[0].status == "linked"
    assert (result.roles[1].role, result.roles[1].duplicate_of) == ("ignored", None)


def test_existing_candidates_are_never_lost() -> None:
    txns = [
        autopay(1),
        card(2, T0 + MIN),  # 1-2: found again by the AutoPay rule, linked
        txn(3, amount_paise=500),
        txn(4, amount_paise=500, txn_time_utc=T0 + MIN),  # 3-4: found by the same-amount rule
        txn(5, amount_paise=700),
        txn(6, amount_paise=700, txn_time_utc=T0 + HOUR),  # 5-6: no rule finds it any more
        txn(7, amount_paise=900),
        txn(8, amount_paise=900, txn_time_utc=T0 + MIN),  # 7-8: the owner said different
    ]
    legacy = [(1, 2), (4, 3), (5, 6), (7, 8), (5, 99), (5, 5)]
    result = derive(txns, links({("duplicate", 7, 8): "different"}), legacy)
    assert brief(result) == [
        ("duplicate", 1, 2, "linked", "DUP_autopay_card", "unique_10min", "engine"),
        ("duplicate", 3, 4, "candidate", "DUP_same_amount", "same_amount", "engine"),
        ("duplicate", 5, 6, "candidate", "DUP_legacy", "recorded_at_import", "engine"),
    ]
    assert derive(txns, None, legacy).links[-1].txn_a == 7  # without the verdict it is kept
    confirmed = derive(txns, links({("duplicate", 5, 6): "same"}), legacy)
    assert confirmed.roles[6].role == "duplicate"


# --- self-transfers (B2, second leg) --------------------------------------------


def out_of_hdfc(id: int = 1, party: str | None = "TEST OWNER", **fields) -> Txn:
    return txn(id, party=party, channel="netbanking", **fields)  # HDFC 0001; the text names SBI


def into_sbi(id: int = 2, party: str | None = "test.other@okaxis", at=T0 + HOUR, **fields) -> Txn:
    values = {"bank": "SBI", "account_last4": "0003", "txn_time_utc": at}
    return credit(party, id=id, **(values | fields))


def test_second_leg_of_a_self_transfer_takes_the_role() -> None:
    txns = [out_of_hdfc(), into_sbi()]
    alone = derive([into_sbi()], OWNER).roles[2]
    assert (alone.role, alone.rule) == ("payback", "CR_person_signal")
    result = derive(txns, OWNER)
    assert brief(result) == [
        ("self_transfer", 1, 2, "linked", "ST_pair", "names_partner_account", "engine")
    ]
    second = result.roles[2]
    assert (second.role, second.rule, second.basis) == ("self_transfer", "ST_pair", "owner")
    assert second.reasons == ("ST_pair", "CR_person_signal")
    assert result.roles[1].rule == "ST_own_text"
    t = totals(txns, result.roles, *EVER)
    assert (t.spent_paise, t.paid_back_paise) == (0, 0)


def test_debit_leg_with_no_payee_takes_the_role_from_the_credit_leg() -> None:
    txns = [out_of_hdfc(party=None), into_sbi(party="test.user@okhdfcbank")]  # names HDFC
    assert derive([txns[0]], OWNER).roles[1].rule == "DB_no_counterparty"
    result = derive(txns, OWNER)
    assert roles(result) == {1: "self_transfer", 2: "self_transfer"}
    assert (result.roles[1].rule, result.roles[2].rule) == ("ST_pair", "ST_own_text")


def test_one_leg_case_is_unchanged() -> None:
    result = derive([out_of_hdfc()], OWNER)
    assert result.links == () and result.roles[1].rule == "ST_own_text"
    no_accounts = derive([out_of_hdfc(), into_sbi()])  # nothing listed: no pair rule can run
    assert no_accounts.links == () and roles(no_accounts) == {1: "spend", 2: "payback"}


@pytest.mark.parametrize(
    ("debit", "credit_leg", "expected"),
    [
        (out_of_hdfc(party="TEST SHOP"), into_sbi(), ("candidate", "no_own_text")),
        (
            out_of_hdfc(party="TEST WALLET"),
            into_sbi(),
            ("candidate", "no_own_text"),
        ),  # names a wallet
        (out_of_hdfc(), into_sbi(at=T0 + 24 * HOUR), ("linked", "names_partner_account")),
        (out_of_hdfc(), into_sbi(at=T0 - 24 * HOUR), ("linked", "names_partner_account")),
        (out_of_hdfc(), into_sbi(at=T0 + 24 * HOUR + SEC), None),
        (out_of_hdfc(), into_sbi(amount_paise=9_999), None),
        (out_of_hdfc(), into_sbi(bank="HDFC", account_last4="0002"), None),  # the same account
        (out_of_hdfc(), into_sbi(account_last4="0009"), None),  # not a listed account
        (out_of_hdfc(), into_sbi(party="test.parent@okaxis"), None),  # an owner party: explained
        (out_of_hdfc(), into_sbi(channel="fd"), None),  # an FD credit is explained
        (out_of_hdfc(), replace(into_sbi(), direction="debit", type="debit"), None),
    ],
)
def test_self_transfer_pair_conditions(debit: Txn, credit_leg: Txn, expected) -> None:
    result = derive([debit, credit_leg], OWNER)
    found = [(x.status, x.reason) for x in result.links if x.kind == "self_transfer"]
    assert found == ([expected] if expected else [])
    if not expected or expected[0] == "candidate":  # nothing changes without a link
        alone = {**roles(derive([debit], OWNER)), **roles(derive([credit_leg], OWNER))}
        assert roles(result) == alone


def test_two_possible_second_legs_are_candidates() -> None:
    txns = [out_of_hdfc(), into_sbi(2), into_sbi(3, at=T0 + 2 * HOUR)]
    result = derive(txns, OWNER)
    transfer = [
        (x.txn_a, x.txn_b, x.status, x.reason) for x in result.links if x.kind != "duplicate"
    ]
    assert transfer == [
        (1, 2, "candidate", "several_partners"),
        (1, 3, "candidate", "several_partners"),
    ]
    assert roles(result) == {1: "self_transfer", 2: "payback", 3: "payback"}  # own text stands
    solved = derive(
        txns, OwnerData(OWNER.accounts, OWNER.parties, links={("self_transfer", 1, 3): "different"})
    )
    assert roles(solved) == {1: "self_transfer", 2: "self_transfer", 3: "payback"}


def test_owner_decides_a_self_transfer_pair() -> None:
    txns = [txn(1, party="TEST SHOP"), credit("TEST", id=2, bank="SBI", txn_time_utc=T0 + 5 * DAY)]
    result = derive(txns, links({("self_transfer", 1, 2): "same"}))
    assert brief(result) == [("self_transfer", 1, 2, "linked", "OWNER_link", "owner_same", "owner")]
    assert {(d.role, d.rule, d.basis) for d in result.roles.values()} == {
        ("self_transfer", "OWNER_link", "owner")
    }
    fixed = OwnerData(roles={1: "spend"}, links={("self_transfer", 1, 2): "same"})
    assert roles(derive(txns, fixed)) == {1: "spend", 2: "self_transfer"}  # a role decision wins


def test_one_account_number_under_two_own_accounts_is_refused() -> None:
    twice = OwnerData(
        accounts=(OWNER.accounts[0], replace(OWNER.accounts[1], bank="HDFC", last4=("0002",)))
    )
    with pytest.raises(ValueError, match="listed under two own accounts"):
        derive([txn()], twice)


# --- refunds (B4) ---------------------------------------------------------------


def purchase(id: int = 1, at=T0, **fields) -> Txn:
    values = {"party": "TEST SHOP", "channel": "debit_card", "account_last4": "0002"}
    return txn(id, txn_time_utc=at, **(values | fields))


def test_unique_full_amount_refund_links_and_stays_role_refund() -> None:
    txns = [purchase(), refund(2, T0 + 5 * DAY)]
    result = derive(txns)
    assert brief(result) == [
        ("refund", 1, 2, "linked", "RF_same_amount", "same_merchant", "engine")
    ]
    assert roles(result) == {1: "spend", 2: "refund"} and result.roles[2].rule == "RF_type"
    assert spent(txns, result) == 0
    alone = derive([refund(2)])
    assert alone.links == () and alone.roles[2].role == "refund"  # no partner: standalone
    assert spent([refund(2)], alone) == -10_000


@pytest.mark.parametrize(
    ("bought", "returned", "expected"),
    [
        (
            purchase(party="TEST OTHER SHOP"),
            refund(2, T0 + DAY),
            ("RF_same_amount", "different_merchant"),
        ),
        (
            purchase(party=None),
            refund(2, T0 + DAY, party=None),
            ("RF_same_amount", "different_merchant"),
        ),
        (purchase(amount_paise=30_000), refund(2, T0 + DAY), ("RF_partial", "partial")),
        (purchase(amount_paise=30_000, party="TEST OTHER SHOP"), refund(2, T0 + DAY), None),
        (
            purchase(amount_paise=9_000),
            refund(2, T0 + DAY),
            None,
        ),  # refund larger than the purchase
        (purchase(at=T0 + SEC), refund(2), None),  # bought after the refund
        (purchase(bank="SBI"), refund(2, T0 + DAY), None),
        (
            purchase(account_last4="0001", channel="upi"),
            refund(2, T0 + DAY),
            None,
        ),  # card vs account
        (purchase(), refund(2, T0 + 30 * DAY + SEC), None),
        (purchase(account_last4=None), refund(2, T0 + DAY, account_last4=None), None),
    ],
)
def test_refund_pairs_that_are_never_linked(bought: Txn, returned: Txn, expected) -> None:
    result = derive([bought, returned])
    found = [(x.status, x.rule, x.reason) for x in result.links if x.kind == "refund"]
    assert found == ([("candidate", *expected)] if expected else [])
    assert roles(result) == {1: "spend", 2: "refund"}


def test_refund_window_is_30_days_before_and_on_the_day_counts() -> None:
    for gap in (timedelta(0), 30 * DAY - SEC, 30 * DAY):
        assert derive([purchase(), refund(2, T0 + gap)]).links[0].status == "linked"


def test_refund_to_a_bank_account_links_on_the_same_account() -> None:
    upi = {"channel": "upi", "account_last4": "0001", "party": "test.shop@ybl"}
    result = derive([purchase(**upi), refund(2, T0 + DAY, **upi)])
    assert brief(result) == [
        ("refund", 1, 2, "linked", "RF_same_amount", "same_merchant", "engine")
    ]


def test_two_equal_purchases_are_candidates_and_partial_waits_for_no_full_pair() -> None:
    txns = [
        purchase(1),
        purchase(2, T0 + 2 * DAY),
        purchase(3, amount_paise=50_000),
        refund(4, T0 + 3 * DAY),
    ]
    result = derive(txns)
    assert [(x.txn_a, x.txn_b, x.status, x.rule, x.reason) for x in result.links] == [
        (1, 4, "candidate", "RF_same_amount", "several_partners"),
        (2, 4, "candidate", "RF_same_amount", "several_partners"),
    ]  # 3 is a partial match, not proposed while a full-amount pair exists
    assert spent(txns, result) == 60_000
    solved = derive(txns, links({("refund", 1, 4): "different"}))
    assert [(x.txn_a, x.status) for x in solved.links] == [(2, "linked")]
    two_refunds = derive([purchase(1), refund(2, T0 + DAY), refund(3, T0 + 2 * DAY)])
    assert {x.reason for x in two_refunds.links if x.kind == "refund"} == {"several_partners"}


def test_refund_links_to_the_primary_of_a_duplicate_group() -> None:
    txns = [
        card(1, party="TEST SHOP"),
        autopay(2, T0 + MIN, party="TEST SHOP"),
        refund(3, T0 + DAY),
    ]
    result = derive(txns)
    assert [(x.kind, x.txn_a, x.txn_b, x.status) for x in result.links] == [
        ("duplicate", 1, 2, "linked"),
        ("refund", 1, 3, "linked"),
    ]
    assert spent(txns, result) == 0


def test_owner_links_a_plain_credit_as_a_refund() -> None:
    txns = [
        purchase(amount_paise=30_000),
        credit("TEST", id=2, channel="upi", txn_time_utc=T0 + 40 * DAY),
    ]
    assert roles(derive(txns)) == {1: "spend", 2: "uncertain"}
    result = derive(txns, links({("refund", 1, 2): "same"}))
    assert brief(result) == [("refund", 1, 2, "linked", "OWNER_link", "owner_same", "owner")]
    assert (result.roles[2].role, result.roles[2].rule, result.roles[2].basis) == (
        "refund",
        "OWNER_link",
        "owner",
    )
    assert spent(txns, result) == 20_000
    over = txns + [refund(3, T0 + DAY, amount_paise=25_000)]
    with pytest.raises(ValueError, match="more than the purchase"):
        derive(over, links({("refund", 1, 2): "same", ("refund", 1, 3): "same"}))


def test_a_self_transfer_is_not_a_purchase() -> None:
    txns = [out_of_hdfc(), refund(2, T0 + DAY, account_last4="0001", party="TEST OWNER")]
    result = derive(txns, OwnerData(accounts=OWNER.accounts[:1], roles={1: "self_transfer"}))
    assert not [x for x in result.links if x.kind == "refund"]


# --- FD (B5) --------------------------------------------------------------------


def closure(id: int = 1, **fields) -> Txn:
    return credit(None, id=id, channel="fd", account_last4="0007", amount_paise=500_000, **fields)


def test_fd_second_credit_is_a_candidate_only() -> None:
    second = credit("TEST", id=2, channel="netbanking", amount_paise=500_000)
    for gap in (timedelta(0), 3 * DAY, -3 * DAY):
        result = derive([closure(), replace(second, txn_time_utc=T0 + gap)])
        assert brief(result) == [("fd", 1, 2, "candidate", "FD_pair", "second_credit", "engine")]
        assert roles(result) == {1: "fd_move", 2: "uncertain"}
    for other in (
        replace(second, txn_time_utc=T0 + 3 * DAY + SEC),
        replace(second, bank="SBI"),
        replace(second, amount_paise=499_999),
        replace(second, direction="debit", type="debit"),
        replace(second, type="refund"),  # explained by its own wording
    ):
        assert derive([closure(), other]).links == ()
    looks_like_payback = replace(second, counterparty_raw="test.other@okaxis", channel="upi")
    result = derive([closure(), looks_like_payback])
    assert result.links[0].status == "candidate" and result.roles[2].role == "payback"
    confirmed = derive([closure(), second], links({("fd", 1, 2): "same"}))
    assert brief(confirmed) == [("fd", 1, 2, "linked", "FD_pair", "owner_same", "owner")]
    assert (confirmed.roles[2].role, confirmed.roles[2].rule) == ("fd_move", "OWNER_link")


# --- properties -----------------------------------------------------------------


def clustered_txns(seed: int, n: int = 300) -> list[Txn]:
    """Few amounts, parties and minutes, so that many pairs form."""
    rng = random.Random(seed)
    out = []
    for i in range(1, n + 1):
        direction = rng.choice(["debit", "debit", "credit"])
        channel = rng.choice(["upi", "netbanking", "debit_card", "e_mandate", "fd", "neft"])
        mandate = channel == "e_mandate"
        out.append(
            txn(
                i,
                direction,
                rng.choice(
                    [None, "TEST SHOP", "TEST OWNER", "test.other@okaxis", "TEST", "NETFLIX"]
                ),
                type="refund" if direction == "credit" and rng.random() < 0.3 else direction,
                bank=rng.choice(["HDFC", "HDFC", "SBI"]),
                amount_paise=rng.choice([10_000, 20_000, 50_000]),
                account_last4=rng.choice(["0001", "0002", "0003"]),
                channel=channel,
                txn_time_utc=T0 + rng.randrange(0, 40) * DAY + rng.randrange(0, 30) * MIN,
                hints=("mandate_reference",) if mandate else (),
                reference=rng.choice([None, "000000000001", "000000000002"]),
            )
        )
    return out


def check(txns: list[Txn], result: Result) -> None:
    by_id = {t.id: t for t in txns}
    assert list(result.roles) == sorted(by_id)
    assert list(result.links) == sorted(result.links, key=lambda x: (x.kind, x.txn_a, x.txn_b))
    seen = set()
    for x in result.links:
        assert isinstance(x, Link) and x.txn_a < x.txn_b and {x.txn_a, x.txn_b} <= set(by_id)
        assert x.kind in LINK_KINDS and x.rule in LINK_RULES and x.reason in LINK_REASONS
        assert x.status in ("linked", "candidate") and x.decided_by in ("engine", "owner")
        assert (x.status == "linked") or x.decided_by == "engine"  # an owner link is never open
        assert (x.kind, x.txn_a, x.txn_b) not in seen
        seen.add((x.kind, x.txn_a, x.txn_b))
    engine_linked = [x for x in result.links if x.status == "linked" and x.decided_by == "engine"]
    for kind in LINK_KINDS:  # rule 1: a rule links a transaction to one partner at most
        ids = [i for x in engine_linked if x.kind == kind for i in (x.txn_a, x.txn_b)]
        assert len(ids) == len(set(ids))
    for x in engine_linked:
        a, b = by_id[x.txn_a], by_id[x.txn_b]
        assert a.amount_paise == b.amount_paise  # I19
        assert (a.direction == b.direction) == (x.kind == "duplicate")
    for i, d in result.roles.items():  # I15: a group has one member that is not a duplicate
        assert (d.role == "duplicate") == (d.duplicate_of is not None)
        if d.duplicate_of is not None:
            assert result.roles[d.duplicate_of].role != "duplicate"
            assert by_id[d.duplicate_of].amount_paise == by_id[i].amount_paise


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_links_are_sound_and_do_not_depend_on_input_order(seed: int) -> None:
    txns = clustered_txns(seed)
    rng = random.Random(seed)
    legacy = [tuple(rng.sample(range(1, len(txns) + 1), 2)) for _ in range(20)]
    owner = OwnerData(OWNER.accounts[:2] + OWNER.accounts[3:], OWNER.parties)
    result = derive(txns, owner, legacy)
    check(txns, result)
    assert {x.kind for x in result.links} == set(LINK_KINDS)
    assert {x.status for x in result.links} == {"linked", "candidate"}
    assert derive(txns, owner, legacy) == result  # twice: the same result
    for _ in range(3):
        shuffled = rng.sample(txns, len(txns))
        assert derive(shuffled, owner, rng.sample(legacy, len(legacy))) == result
    in_links = {(x.txn_a, x.txn_b) for x in result.links if x.kind == "duplicate"}
    assert all((min(p), max(p)) in in_links for p in legacy)  # rule 5: none lost


def test_i17_a_candidate_changes_no_role_and_no_total() -> None:
    owner = OwnerData(OWNER.accounts[:2] + OWNER.accounts[3:], OWNER.parties)  # no credit card
    seen_linked = seen_candidates = 0
    for seed in range(21, 27):
        txns = clustered_txns(seed)
        result = derive(txns, owner)
        # The same transactions far apart in time form no pair: roles from one transaction only.
        apart = [replace(t, txn_time_utc=T0 + t.id * 400 * DAY) for t in txns]
        baseline = derive(apart, owner)
        assert baseline.links == ()
        linked = {i for x in result.links if x.status == "linked" for i in (x.txn_a, x.txn_b)}
        seen_linked += len(linked)
        seen_candidates += len({i for x in result.links for i in (x.txn_a, x.txn_b)} - linked)
        for t in txns:
            if t.id not in linked:
                assert result.roles[t.id] == baseline.roles[t.id]
        # A link changes a role only to duplicate or self_transfer.
        for i in linked:
            before, after = baseline.roles[i].role, result.roles[i].role
            assert after == before or after in ("duplicate", "self_transfer")
        everything = totals(txns, result.roles, *EVER)
        unlinked = totals(apart, baseline.roles, T0, T0 + 10**6 * DAY)
        if not linked:
            assert everything == unlinked
    assert seen_linked and seen_candidates
