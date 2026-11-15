"""Reconcile roles from one transaction (step 3C-2). Fake values only.

Links between transactions: test_reconcile_links.py.
"""

import json
import random
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.engine import parse_message
from app.engine.reconcile import (
    COUNTED,
    CREDIT_ONLY,
    DEBIT_ONLY,
    LINK_KINDS,
    LINK_REASONS,
    LINK_RULES,
    RECONCILE_VERSION,
    ROLES,
    RULES,
    VERSIONS,
    Derived,
    OwnAccount,
    OwnerData,
    Party,
    Totals,
    Txn,
    derive,
    totals,
)

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample" / "redacted_sample.json"
IST = timezone(timedelta(hours=5, minutes=30))
T0 = datetime(2026, 1, 20, 6, 30, tzinfo=UTC)
DAY = timedelta(days=1)

CARD = OwnAccount("credit_card", "HDFC", ("0004",), ("TEST CARD BILLER",))
OWNER = OwnerData(
    accounts=(
        OwnAccount("bank_account", "HDFC", ("0001", "0002"), ("test.user@okhdfcbank",)),
        OwnAccount("bank_account", "SBI", ("0003",), ("TEST OWNER", "test.user@oksbi")),
        CARD,
        OwnAccount("wallet", texts=("TEST WALLET",)),
        OwnAccount("fd", "HDFC", texts=("TEST FD BOOKING",)),
    ),
    parties=(
        Party("person", income=True, texts=("test.parent@okaxis", "TEST PARENT")),
        Party("person", texts=("PERSON_901", "test.friend@ybl")),
        Party("business", texts=("TEST FOODS 12",)),
        Party("business", income=True, texts=("TEST EMPLOYER PVT LTD",)),
    ),
)


def txn(id: int = 1, direction: str = "debit", party: str | None = "TEST SHOP", **fields) -> Txn:
    values = {
        "bank": "HDFC",
        "type": direction,
        "amount_paise": 10_000,
        "account_last4": "0001",
        "channel": "upi",
        "txn_time_utc": T0,
    }
    return Txn(id=id, direction=direction, counterparty_raw=party, **(values | fields))


def credit(party: str | None, **fields) -> Txn:
    return txn(direction="credit", party=party, **fields)


def one(t: Txn, owner: OwnerData | None = None) -> Derived:
    return derive([t], owner).roles[t.id]


# (transaction, owner data, role, rule, basis): one row or more for every rule code.
CASES = [
    (credit(None, channel="fd"), None, "fd_move", "FD_channel", "engine"),
    (txn(party="Test FD booking"), OWNER, "fd_move", "FD_own_text", "owner"),
    (
        credit(None, channel="credit_card", hints=("card_bill_payment",)),
        None,
        "card_bill_excluded",
        "CB_hint",
        "engine",
    ),
    (txn(party="TEST CARD BILLER"), OWNER, "card_bill_counted", "CB_own_text", "owner"),
    (txn(party="test owner", channel="netbanking"), OWNER, "self_transfer", "ST_own_text", "owner"),
    (credit("Test.User@OKSBI"), OWNER, "self_transfer", "ST_own_text", "owner"),
    (txn(party="TEST WALLET"), OWNER, "self_transfer", "ST_own_text", "owner"),
    (credit("TEST SHOP", type="refund", channel="debit_card"), None, "refund", "RF_type", "engine"),
    (credit("*user@oksbi"), OWNER, "uncertain", "ST_masked", "owner"),
    (credit("test.parent@okaxis"), OWNER, "income", "CR_income_party", "owner"),
    (credit("TEST EMPLOYER PVT LTD", channel="neft"), OWNER, "income", "CR_income_party", "owner"),
    (credit("test.friend@ybl"), OWNER, "payback", "CR_person_party", "owner"),
    (credit("MR TEST PERSON", channel="neft"), None, "payback", "CR_person_signal", "engine"),
    (credit("9000000001@ybl"), None, "payback", "CR_person_signal", "engine"),
    (credit("test.other@okaxis"), None, "payback", "CR_person_signal", "engine"),
    (credit("*user@oksbi"), None, "payback", "CR_person_signal", "engine"),  # no own UPI ID listed
    (credit("TEST PERSON", channel="neft"), None, "uncertain", "CR_name_only", "engine"),
    (credit("TEST TRADERS PVT LTD"), None, "uncertain", "CR_business", "engine"),
    (credit("TEST STORES test.other@okaxis"), None, "uncertain", "CR_unsure", "engine"),
    (credit("TEST FOODS 12"), OWNER, "uncertain", "CR_business", "owner"),
    (credit("TEST"), None, "uncertain", "CR_unsure", "engine"),
    (credit(None), None, "uncertain", "CR_no_text", "engine"),
    (credit("TEST CARD BILLER"), OWNER, "uncertain", "CR_own_account", "owner"),
    (txn(party=None, channel="netbanking"), None, "spend", "DB_no_counterparty", "engine"),
    (txn(party=None, channel="atm"), None, "spend", "DB_spend", "engine"),
    (txn(party="TEST SHOP", channel="debit_card"), None, "spend", "DB_spend", "engine"),
    (txn(party="PERSON_901"), OWNER, "spend", "DB_spend", "engine"),  # paying a person is spend
    (txn(party="TEST PARENT"), OWNER, "spend", "DB_spend", "engine"),  # also an income source
    (txn(), OwnerData(roles={1: "ignored"}), "ignored", "OWNER_role", "owner"),
]


@pytest.mark.parametrize(("t", "owner", "role", "rule", "basis"), CASES)
def test_one_case_per_rule(t, owner, role, rule, basis) -> None:
    d = one(t, owner)
    assert (d.role, d.rule, d.basis) == (role, rule, basis)
    assert d.reasons[0] == rule and d.transaction_id == t.id


def test_every_role_and_every_rule_is_reached() -> None:
    # No rule gives "duplicate" before step 3C-3, and the owner cannot set it as a role.
    # The role duplicate and these three rules need two transactions: test_reconcile_links.py.
    by_link = {"OWNER_link", "DUP_autopay_card", "ST_pair"}
    assert {role for _, _, role, _, _ in CASES} | {"duplicate"} == set(ROLES)
    assert {rule for _, _, _, rule, _ in CASES} | by_link == set(RULES)
    assert len(ROLES) == 11 and set(COUNTED) | DEBIT_ONLY | CREDIT_ONLY <= set(ROLES)
    assert VERSIONS["reconcile"] == RECONCILE_VERSION == "reconcile-1.1.0"


def test_unexplained_debit_is_spend_and_unexplained_credit_is_uncertain() -> None:
    assert one(txn(party="TEST UNSEEN THING")).role == "spend"
    assert one(credit("TEST UNSEEN THING 7", channel="neft")).role == "uncertain"
    assert one(credit(None, channel=None)).role == "uncertain"


def test_income_is_checked_before_payback() -> None:
    money_in = credit("test.parent@okaxis")  # a consumer handle: the engine alone says payback
    assert one(money_in).rule == "CR_person_signal"
    person = OwnerData(parties=(Party("person", texts=("test.parent@okaxis",)),))
    assert (one(money_in, person).role, one(money_in, person).basis) == ("payback", "owner")
    income = OwnerData(parties=(Party("person", income=True, texts=("test.parent@okaxis",)),))
    assert (one(money_in, income).role, one(money_in, income).basis) == ("income", "owner")


def test_a_party_overrides_the_engine_both_ways() -> None:
    shop = OwnerData(parties=(Party("business", texts=("test.other@okaxis",)),))
    assert one(credit("test.other@okaxis"), shop).role == "uncertain"  # engine alone: payback
    friend = OwnerData(parties=(Party("person", texts=("TEST TRADERS PVT LTD",)),))
    assert one(credit("TEST TRADERS PVT LTD"), friend).role == "payback"  # engine alone: uncertain


@pytest.mark.parametrize(("days", "role"), [(59, "excluded"), (60, "excluded"), (61, "counted")])
def test_card_bill_tracked_test_at_59_60_and_61_days(days: int, role: str) -> None:
    purchase = txn(1, party="TEST SHOP", channel="credit_card", account_last4="0004")
    payment = txn(2, party="TEST CARD BILLER", txn_time_utc=T0 + days * DAY)
    d = derive([purchase, payment], OWNER).roles
    assert (d[2].role, d[2].rule, d[2].basis) == (f"card_bill_{role}", "CB_own_text", "owner")
    assert d[1].role == "spend"


@pytest.mark.parametrize(
    "purchase",
    [
        {"txn_time_utc": T0 + timedelta(days=10, seconds=1)},  # after the payment
        {"account_last4": "0005"},  # another card
        {"bank": "SBI"},  # another bank
        {"channel": "debit_card"},  # a debit card has no bill
        {"direction": "credit", "type": "refund"},  # not a purchase
    ],
)
def test_card_bill_counts_when_no_purchase_proves_tracking(purchase: dict) -> None:
    fields = {"channel": "credit_card", "account_last4": "0004"} | purchase
    payment = txn(2, party="TEST CARD BILLER", txn_time_utc=T0 + 10 * DAY)
    roles = derive([txn(1, **fields), payment], OWNER).roles
    assert roles[2].role == "card_bill_counted"
    at_payment_time = txn(
        1, channel="credit_card", account_last4="0004", txn_time_utc=T0 + 10 * DAY
    )
    roles = derive([at_payment_time, payment], OWNER).roles
    assert roles[2].role == "card_bill_excluded"


def test_masked_upi_id_must_fit_handle_and_end() -> None:
    assert one(credit("**ser@oksbi"), OWNER).rule == "ST_masked"
    assert one(credit("*other@oksbi"), OWNER).rule == "CR_person_signal"  # another ending
    assert one(credit("*user@okaxis"), OWNER).rule == "CR_person_signal"  # another handle
    assert one(credit("*@oksbi"), OWNER).rule == "ST_masked"  # nothing visible: fits any ID
    assert one(credit("*@okaxis"), OWNER).rule == "CR_person_signal"
    assert one(txn(party="*user@oksbi"), OWNER).role == "spend"  # debits: text match only


def test_owner_decision_beats_the_engine_and_keeps_the_engine_reason() -> None:
    assert one(txn()).role == "spend" and one(txn(), OwnerData()).basis == "engine"
    d = one(txn(), OwnerData(roles={1: "self_transfer", 99: "ignored"}))  # 99: not in the input
    assert (d.role, d.rule, d.basis, d.reasons) == (
        "self_transfer",
        "OWNER_role",
        "owner",
        ("OWNER_role", "DB_spend"),
    )
    as_refund = one(credit("TEST SHOP"), OwnerData(roles={1: "refund"}))  # a credit worded plainly
    assert (as_refund.role, as_refund.basis) == ("refund", "owner")


@pytest.mark.parametrize(
    ("t", "role"),
    [
        (txn(), "duplicate"),  # decided as a link, never as a role
        (txn(), "unknown"),  # the draft name of "uncertain"
        (txn(), "payback"),
        (txn(), "refund"),
        (credit("TEST SHOP"), "spend"),
        (credit("TEST SHOP"), "card_bill_counted"),
    ],
)
def test_owner_decision_that_cannot_hold_is_refused(t: Txn, role: str) -> None:
    with pytest.raises(ValueError, match="owner role decision"):
        one(t, OwnerData(roles={1: role}))


def test_earlier_rule_wins_and_every_match_is_kept() -> None:
    d = one(credit("TEST OWNER", channel="fd"), OWNER)
    assert (d.role, d.rule, d.reasons) == ("fd_move", "FD_channel", ("FD_channel", "ST_own_text"))
    d = one(credit("test.user@oksbi", type="refund"), OWNER)
    assert (d.role, d.reasons) == ("self_transfer", ("ST_own_text", "RF_type"))


def test_owner_text_listed_in_two_places_is_refused_without_naming_it() -> None:
    twice = OwnerData(
        accounts=(OwnAccount("wallet", texts=("TEST SECRET NAME",)),),
        parties=(Party("person", texts=("test  secret-name",)),),  # the same merchant key
    )
    with pytest.raises(ValueError, match="listed in two places") as error:
        derive([txn()], twice)
    assert "secret" not in str(error.value).lower()
    with pytest.raises(ValueError, match="no letters or digits"):
        derive([], OwnerData(parties=(Party("person", texts=("...",)),)))
    same_place = OwnerData(parties=(Party("person", texts=("TEST PERSON", "test person")),))
    assert one(credit("Test Person", channel="neft"), same_place).role == "payback"


def test_bad_input_is_refused() -> None:
    with pytest.raises(ValueError, match="share one id"):
        derive([txn(1), txn(1)])
    with pytest.raises(ValueError, match="integer number of paise"):
        txn(amount_paise=100.0)
    with pytest.raises(ValueError, match="time zone"):
        txn(txn_time_utc=datetime(2026, 1, 20, 6, 30))
    with pytest.raises(ValueError, match="direction"):
        txn(direction="refund")
    with pytest.raises(ValueError, match="kind"):
        OwnAccount("savings")
    with pytest.raises(ValueError, match="kind"):
        Party("friend")


TEXTS = [
    None,
    "TEST SHOP",
    "TEST PERSON",
    "MR TEST PERSON",
    "test.other@okaxis",
    "9000000001@ybl",
    "*user@oksbi",
    "TEST TRADERS PVT LTD",
    "SWIGGY",
    *(text for entry in (*OWNER.accounts, *OWNER.parties) for text in entry.texts),
]


def random_txns(seed: int, n: int = 400) -> list[Txn]:
    rng = random.Random(seed)
    out = []
    for i in range(1, n + 1):
        direction = rng.choice(["debit", "debit", "credit"])
        out.append(
            txn(
                i,
                direction,
                rng.choice(TEXTS),
                type="refund" if direction == "credit" and rng.random() < 0.1 else direction,
                amount_paise=rng.randrange(1, 5_000_000),
                account_last4=rng.choice(["0001", "0004", None]),
                channel=rng.choice(
                    ["upi", "netbanking", "debit_card", "credit_card", "atm", "fd", "neft", None]
                ),
                txn_time_utc=T0 + timedelta(minutes=rng.randrange(0, 200 * 24 * 60)),
                hints=rng.choice([(), (), ("card_bill_payment",), ("autopay",)]),
            )
        )
    return out


def test_exactly_one_role_each_same_output_in_any_order() -> None:
    txns = random_txns(1)
    owner = OwnerData(OWNER.accounts, OWNER.parties, {5: "ignored", 6: "self_transfer"})
    result = derive(txns, owner)
    first = result.roles
    assert list(first) == [t.id for t in txns]  # one result per transaction, ordered by id
    assert all(
        d.role in ROLES and d.rule in RULES and d.reasons[0] == d.rule for d in first.values()
    )
    assert all(d.basis in ("engine", "owner") for d in first.values())
    assert derive(txns, owner) == result
    shuffled = random.Random(2).sample(txns, len(txns))
    assert derive(shuffled, owner) == result
    assert list(derive(shuffled, owner).roles) == list(first)
    assert {d.role for d in first.values()} >= set(ROLES) - {"duplicate", "card_bill_counted"}
    assert all(d.basis == "engine" for d in derive(txns).roles.values())  # no owner data


def test_i18_roles_respect_direction() -> None:
    txns = random_txns(3)
    derived = derive(txns, OWNER).roles
    for t in txns:
        role = derived[t.id].role
        assert not (role in DEBIT_ONLY and t.direction != "debit")
        assert not (role in CREDIT_ONLY and t.direction != "credit")


def naive_totals(txns: list[Txn], derived: dict[int, Derived], start, end) -> tuple[int, ...]:
    inside = [t for t in txns if start <= t.txn_time_utc < end]

    def of(role: str) -> int:
        return sum(t.amount_paise for t in inside if derived[t.id].role == role)

    spent = of("spend") + of("card_bill_counted") - of("refund")
    return spent, of("payback"), spent - of("payback"), of("income")


@pytest.mark.parametrize("seed", [4, 5, 6])
def test_i16_totals_equal_the_sums_over_roles(seed: int) -> None:
    txns = random_txns(seed)
    derived = derive(txns, OWNER).roles
    assert sum(Counter(d.role for d in derived.values()).values()) == len(txns)
    rng = random.Random(seed)
    ranges = [(T0 - DAY, T0 + 400 * DAY), (T0, T0)]
    ranges += [(T0 + a * DAY, T0 + (a + rng.randrange(1, 90)) * DAY) for a in range(0, 200, 13)]
    for start, end in ranges:
        t = totals(txns, derived, start, end)
        assert isinstance(t.spent_paise, int)
        assert (t.spent_paise, t.paid_back_paise, t.net_paise, t.income_paise) == naive_totals(
            txns, derived, start, end
        )
    assert totals(txns, derived, T0, T0) == Totals()
    whole = totals(txns, derived, T0 - DAY, T0 + 400 * DAY)
    assert whole.spent_paise and whole.paid_back_paise and whole.income_paise


def test_totals_range_is_start_inclusive_end_exclusive_and_ist_months_work() -> None:
    november = (datetime(2026, 11, 1, tzinfo=IST), datetime(2026, 12, 1, tzinfo=IST))
    first_minute = datetime(2026, 10, 31, 18, 30, tzinfo=UTC)  # 1 Nov 00:00 IST
    txns = [
        txn(1, amount_paise=100, txn_time_utc=first_minute - timedelta(seconds=1)),  # October
        txn(2, amount_paise=20_000, txn_time_utc=first_minute),
        credit("TEST SHOP", id=3, type="refund", amount_paise=5_000, txn_time_utc=first_minute),
        credit("9000000001@ybl", id=4, amount_paise=3_000, txn_time_utc=first_minute + DAY),
        credit("TEST", id=5, amount_paise=7, txn_time_utc=first_minute + DAY),  # uncertain
        txn(6, amount_paise=900, txn_time_utc=datetime(2026, 11, 30, 18, 30, tzinfo=UTC)),  # Dec
    ]
    t = totals(txns, derive(txns).roles, *november)
    assert (t.spent_paise, t.paid_back_paise, t.net_paise, t.income_paise) == (
        15_000,
        3_000,
        12_000,
        0,
    )


@pytest.mark.skipif(not SAMPLE.exists(), reason="redacted sample not present (CI)")
def test_engine_runs_over_the_redacted_sample() -> None:
    txns = []
    for i, msg in enumerate(json.loads(SAMPLE.read_text(encoding="utf-8")), 1):
        p = parse_message(msg["sender"], msg["body"], datetime.fromisoformat(msg["date_utc"]))
        if getattr(p, "is_money", False):
            txns.append(
                Txn(
                    i,
                    p.bank,
                    p.type,
                    p.direction,
                    p.amount_paise,
                    p.account_last4,
                    p.channel,
                    p.counterparty_raw,
                    p.txn_time_utc,
                    p.hints,
                    p.reference,
                )
            )
    result = derive(txns)
    derived = result.roles
    assert all(x.kind in LINK_KINDS and x.rule in LINK_RULES for x in result.links)
    assert all(x.decided_by == "engine" and x.reason in LINK_REASONS for x in result.links)
    linked = {i for x in result.links if x.status == "linked" for i in (x.txn_a, x.txn_b)}
    assert all(d.duplicate_of in derived for d in derived.values() if d.role == "duplicate")
    assert all(d.rule.startswith(("DUP_", "ST_pair")) <= (i in linked) for i, d in derived.items())
    assert txns and list(derived) == [t.id for t in txns]
    assert all(d.role in ROLES and d.basis == "engine" for d in derived.values())
    times = [t.txn_time_utc for t in txns]
    whole = totals(txns, derived, min(times), max(times) + DAY)
    assert whole.net_paise == whole.spent_paise - whole.paid_back_paise and whole.income_paise == 0
