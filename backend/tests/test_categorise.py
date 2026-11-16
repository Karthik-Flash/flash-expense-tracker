"""Categorise (categorise-1.0.0): precedence, refunds, labels, breakdown. Fake values only."""

import json
import random
from datetime import datetime, timedelta

import pytest

from app.engine import parse_message
from app.engine.categorise import (
    BRAND_CATEGORIES,
    CATEGORIES,
    INVESTMENT_WORDS,
    KEYWORD_CATEGORIES,
    NOT_SPENDING,
    RULES,
    SPENDING_ROLES,
    Categorised,
    breakdown,
    categorise,
    check_brand_categories,
    label_view,
)
from app.engine.merchant import BUSINESS_WORDS, brands
from app.engine.reconcile import ROLES, OwnAccount, OwnerData, Party, Txn, derive, totals
from tests.test_reconcile import DAY, OWNER, SAMPLE, T0, credit, random_txns, txn

EVER = (T0 - 1000 * DAY, T0 + 1000 * DAY)


def run(txns: list[Txn], owner: OwnerData | None = None) -> dict[int, Categorised]:
    owner = owner or OwnerData()
    return categorise(txns, owner, derive(txns, owner))


def one(t: Txn, owner: OwnerData | None = None) -> tuple[str, str, str]:
    c = run([t], owner)[t.id]
    return c.category, c.rule, c.basis


def party(text: str, category: str | None = None, kind: str = "business") -> OwnerData:
    return OwnerData(parties=(Party(kind, texts=(text,), category=category),))


def with_decision(owner: OwnerData, category: str, txn_id: int = 1) -> OwnerData:
    return OwnerData(owner.accounts, owner.parties, owner.roles, owner.links, {txn_id: category})


# --- the list -------------------------------------------------------------------


def test_the_fixed_list_and_the_tables() -> None:
    assert list(CATEGORIES.values()) == [
        "Food & Drinks",
        "Groceries",
        "Travel",
        "Shopping",
        "Bills & Recharges",
        "Subscriptions",
        "Health",
        "Personal Care",
        "Entertainment",
        "Education",
        "Rent & Hostel",
        "EMI & Loans",
        "Investments",
        "Gifts & Donations",
        "People",
        "Cash",
        "Card bill",
        "Fees & Charges",
        "Other",
        "Uncategorised",
    ]
    assert all(slug == slug.lower() and " " not in slug for slug in CATEGORIES)
    check_brand_categories()  # every brand has one valid category
    assert set(BRAND_CATEGORIES) == set(brands()) and len(BRAND_CATEGORIES) == 74
    assert set(KEYWORD_CATEGORIES.values()) <= set(CATEGORIES)
    assert set(KEYWORD_CATEGORIES) - INVESTMENT_WORDS <= BUSINESS_WORDS  # business keywords only
    assert set(NOT_SPENDING) | SPENDING_ROLES == set(ROLES)
    assert set(NOT_SPENDING.values()) <= set(CATEGORIES)


# --- each precedence level ------------------------------------------------------

LEVELS = [
    (
        txn(party="TEST SHOP"),
        with_decision(OwnerData(), "gifts_donations"),
        "gifts_donations",
        "OWNER_txn",
        "owner",
    ),
    (
        txn(party="TEST SHOP"),
        party("TEST SHOP", "entertainment"),
        "entertainment",
        "OWNER_party",
        "owner",
    ),
    (txn(party="TEST ATM 0001", channel="atm"), None, "cash", "CH_atm", "engine"),
    (
        txn(party="TEST CARD BILLER"),
        OwnerData(accounts=(OwnAccount("credit_card", "HDFC", ("0004",), ("TEST CARD BILLER",)),)),
        "card_bill",
        "ROLE_card_bill",
        "engine",
    ),
    (txn(party=None, channel="emi"), None, "emi_loans", "CH_emi", "engine"),
    (
        txn(party=None, channel="netbanking", hints=("bank_charge",)),
        None,
        "fees_charges",
        "HINT_fee",
        "engine",
    ),
    (txn(party="SWIGGY"), None, "food_drinks", "BRAND", "engine"),
    (txn(party="PAYTM"), None, "uncategorised", "BRAND", "engine"),  # a wallet says nothing
    (txn(party="TEST PHARMACY"), None, "health", "KEYWORD", "engine"),
    (txn(party="TEST HOSTEL"), None, "rent_hostel", "KEYWORD", "engine"),
    (txn(party="TEST MUTUAL FUND", channel="nach"), None, "investments", "KEYWORD", "engine"),
    (txn(party="TEST MEDICAL COLLEGE"), None, "uncategorised", "KW_conflict", "engine"),
    (txn(party="MR TEST PERSON"), None, "people", "PERSON", "engine"),
    (txn(party="TEST PERSON"), None, "people", "PERSON", "engine"),  # low confidence counts too
    (txn(party="TEST SHOP 7"), party("TEST SHOP 7", kind="person"), "people", "PERSON", "engine"),
    (txn(party="TEST SHOP", channel="debit_card"), None, "uncategorised", "NONE", "engine"),
    (txn(party=None, channel="netbanking"), None, "uncategorised", "NONE", "engine"),
    (credit("test.other@okaxis"), None, "people", "NS_payback", "engine"),
    (credit("TEST PARENT"), OWNER, "other", "NS_income", "engine"),
    (txn(party="TEST OWNER"), OWNER, "other", "NS_self_transfer", "engine"),
    (
        credit(None, channel="credit_card", hints=("card_bill_payment",)),
        None,
        "card_bill",
        "NS_card_bill_excluded",
        "engine",
    ),
    (credit(None, channel="fd"), None, "investments", "NS_fd_move", "engine"),
    (txn(), OwnerData(roles={1: "ignored"}), "other", "NS_ignored", "engine"),
    (credit("TEST"), None, "other", "NS_uncertain", "engine"),
    (
        credit("TEST"),
        with_decision(OwnerData(), "gifts_donations"),
        "gifts_donations",
        "OWNER_txn",
        "owner",
    ),
]


@pytest.mark.parametrize(("t", "owner", "category", "rule", "basis"), LEVELS)
def test_each_level(t, owner, category, rule, basis) -> None:
    assert one(t, owner) == (category, rule, basis)


def test_every_rule_and_every_category_is_reachable() -> None:
    reached_rules = {rule for *_, rule, _ in LEVELS} | {"RF_linked", "NS_duplicate"}
    assert reached_rules == set(RULES)  # the two others: the refund and duplicate tests below
    by_engine = {c for *_, c, _, basis in LEVELS if basis == "engine"}
    by_engine |= set(BRAND_CATEGORIES.values()) | set(KEYWORD_CATEGORIES.values())
    assert by_engine == set(CATEGORIES) - {"gifts_donations"}  # only the owner can give that one
    for slug in CATEGORIES:  # the owner can give every category
        assert one(txn(), with_decision(OwnerData(), slug))[0] == slug
        assert one(txn(party="TEST SHOP"), party("TEST SHOP", slug))[0] == slug


# --- neighbouring levels: the higher one wins -----------------------------------


def test_neighbouring_levels() -> None:
    shop = party("SWIGGY", "groceries")
    assert one(txn(party="SWIGGY"), with_decision(shop, "other"))[1] == "OWNER_txn"  # 1 over 2
    atm = txn(party="TEST ATM 0001", channel="atm")
    assert one(atm, party("TEST ATM 0001", "other"))[1] == "CH_atm"  # an ATM has no merchant
    emi_brand = txn(party="SWIGGY", channel="emi")
    assert one(emi_brand, party("SWIGGY", "groceries"))[1] == "OWNER_party"  # 2 over 3
    assert one(emi_brand)[1] == "CH_emi"  # 3 over 4
    assert one(txn(party="SWIGGY PHARMACY")) == ("food_drinks", "BRAND", "engine")  # 4 over 5
    assert one(txn(party="MR TEST PHARMACY"))[1] == "KEYWORD"  # 5 over 6
    assert one(txn(party="MR TEST PERSON"))[1] == "PERSON"  # 6 over 7
    person = party("TEST PERSON", "rent_hostel", kind="person")  # the landlord
    assert one(txn(party="TEST PERSON"), person) == ("rent_hostel", "OWNER_party", "owner")
    assert one(txn(party="TEST PERSON"), party("TEST PERSON", kind="person"))[1] == "PERSON"
    # A decision on one transaction does not touch the merchant's other payments.
    two = [txn(1, party="TEST SHOP"), txn(2, party="TEST SHOP")]
    result = run(two, with_decision(party("TEST SHOP", "shopping"), "gifts_donations", 2))
    assert [result[i].category for i in (1, 2)] == ["shopping", "gifts_donations"]


def test_keywords_match_whole_words_only() -> None:
    assert one(txn(party="TEST CAFE"))[0] == "food_drinks"
    assert one(txn(party="TESTCAFE"))[1] == "NONE"
    assert one(txn(party="TEST CAFETERIA 9"))[1] == "NONE"
    assert one(txn(party="TEST CAFE AND BAKERY"))[1] == "KEYWORD"  # two words, one category
    assert one(txn(party="TEST STORES PVT LTD"))[1] == "NONE"  # generic words are not mapped
    assert one(txn(party="TEST HOTEL 4"))[1] == "NONE"
    assert one(txn(party="test.cafe@ybl"))[1] == "NONE"  # the name only, not the UPI ID


def test_bad_owner_category_is_refused_without_naming_it() -> None:
    for owner in (party("TEST SHOP", "TEST SECRET"), with_decision(OwnerData(), "Food & Drinks")):
        with pytest.raises(ValueError, match="not a category of the list") as error:
            run([txn()], owner)
        assert "SECRET" not in str(error.value)


# --- refunds --------------------------------------------------------------------


def purchase(id: int = 1, **fields) -> Txn:
    values = {"party": "SWIGGY", "channel": "debit_card", "account_last4": "0002"}
    return txn(id, **(values | fields))


def refund(id: int = 2, **fields) -> Txn:
    values = {"party": "SWIGGY", "channel": "debit_card", "account_last4": "0002"}
    return credit(id=id, type="refund", txn_time_utc=T0 + DAY, **(values | fields))


def test_linked_refund_takes_its_purchases_category() -> None:
    txns = [purchase(), refund()]
    result = run(txns)
    assert result[2] == Categorised("food_drinks", "RF_linked", "engine")
    owner = with_decision(OwnerData(), "gifts_donations", 1)  # the purchase was a gift
    assert run(txns, owner)[2] == Categorised("gifts_donations", "RF_linked", "owner")
    assert run(txns, with_decision(OwnerData(), "other", 2))[2].rule == "OWNER_txn"
    roles = derive(txns).roles
    assert breakdown(txns, roles, result, *EVER) == {"food_drinks": 0}
    # The owner links a refund to a purchase at another merchant: the purchase decides.
    other = [purchase(party="TEST PHARMACY"), refund(party="TEST SHOP", amount_paise=4_000)]
    linked = OwnerData(links={("refund", 1, 2): "same"})
    assert run(other)[2].rule == "NONE" and run(other, linked)[2].category == "health"


def test_unlinked_refund_is_categorised_by_its_own_merchant() -> None:
    assert one(refund()) == ("food_drinks", "BRAND", "engine")
    assert one(refund(party="TEST PHARMACY")) == ("health", "KEYWORD", "engine")
    assert one(refund(party="TEST SHOP"), party("TEST SHOP", "shopping"))[1] == "OWNER_party"
    assert one(refund(party="TEST SHOP")) == ("uncategorised", "NONE", "engine")
    assert one(refund(party="MR TEST PERSON"))[1] == "NONE"  # People is for debits
    alone = [refund(amount_paise=7_000)]
    assert breakdown(alone, derive(alone).roles, run(alone), *EVER) == {"food_drinks": -7_000}


def test_a_duplicate_is_not_spending() -> None:
    txns = [
        txn(1, party="NETFLIX", channel="debit_card", account_last4="0002"),
        txn(
            2,
            party="NETFLIX",
            channel="e_mandate",
            account_last4="0002",
            txn_time_utc=T0 + DAY / 1000,
        ),
    ]
    result = run(txns)
    assert (result[1].rule, result[2]) == ("BRAND", Categorised("other", "NS_duplicate", "engine"))
    assert breakdown(txns, derive(txns).roles, result, *EVER) == {"subscriptions": 10_000}


# --- breakdown and labels -------------------------------------------------------


@pytest.mark.parametrize("seed", [31, 32, 33])
def test_i23_breakdown_adds_up_to_spent_for_any_range(seed: int) -> None:
    txns = random_txns(seed)
    owner = OwnerData(
        OWNER.accounts,
        (*OWNER.parties, Party("business", texts=("TEST SHOP",), category="shopping")),
        categories={5: "gifts_donations", 6: "other"},
    )
    result = derive(txns, owner)
    categories = categorise(txns, owner, result)
    assert list(categories) == [t.id for t in txns]  # I22: one each
    assert all(c.category in CATEGORIES and c.rule in RULES for c in categories.values())
    assert all(c.basis in ("engine", "owner") for c in categories.values())
    assert categorise(random.Random(seed).sample(txns, len(txns)), owner, result) == categories
    rng = random.Random(seed)
    ranges = [EVER, (T0, T0)]
    ranges += [(T0 + a * DAY, T0 + (a + rng.randrange(1, 90)) * DAY) for a in range(0, 200, 17)]
    for start, end in ranges:
        parts = breakdown(txns, result.roles, categories, start, end)
        assert sum(parts.values()) == totals(txns, result.roles, start, end).spent_paise
        assert set(parts) <= set(CATEGORIES)
    whole = breakdown(txns, result.roles, categories, *EVER)
    assert len(whole) >= 5 and list(whole) == [s for s in CATEGORIES if s in whole]  # list order


def test_label_view_across_all_dates() -> None:
    txns = [
        txn(1, party="SWIGGY", amount_paise=30_000),
        txn(2, party="TEST TRAVELS", amount_paise=200_000, txn_time_utc=T0 + 40 * DAY),
        credit("test.other@okaxis", id=3, amount_paise=50_000, txn_time_utc=T0 + 45 * DAY),
        txn(4, party="SWIGGY", amount_paise=99_000),  # not labelled
        refund(5, amount_paise=10_000, account_last4="0001", channel="upi"),
    ]
    result = derive(txns)
    categories = categorise(txns, OwnerData(), result)
    trip, parts = label_view(txns, result.roles, categories, [1, 2, 3, 5, 99])
    assert (trip.spent_paise, trip.paid_back_paise, trip.net_paise) == (220_000, 50_000, 170_000)
    assert parts == {"food_drinks": 20_000, "travel": 200_000}  # sums to Spent; payback is apart
    assert sum(parts.values()) == trip.spent_paise
    assert categorise(txns, OwnerData(), result) == categories  # a label changes no category
    nothing, no_parts = label_view(txns, result.roles, categories, [])
    assert (nothing.spent_paise, no_parts) == (0, {})


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
    categories = categorise(txns, OwnerData(), result)
    assert list(categories) == [t.id for t in txns]
    assert all(c.category in CATEGORIES and c.basis == "engine" for c in categories.values())
    times = [t.txn_time_utc for t in txns]
    span = (min(times), max(times) + timedelta(seconds=1))
    parts = breakdown(txns, result.roles, categories, *span)
    assert sum(parts.values()) == totals(txns, result.roles, *span).spent_paise
