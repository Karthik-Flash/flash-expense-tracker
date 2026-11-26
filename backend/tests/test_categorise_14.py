"""categorise-1.4.0 (5G-C, D-155): known names, more keywords, stems and weak words. FAKE."""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.engine import category_words as words14
from app.engine.categorise import CATEGORIES, GUESS_RULES, categorise
from app.engine.reconcile import OwnerData, Party, Txn, derive

NAMES = json.loads(
    (Path(__file__).parent / "fixtures" / "category_names_14.json").read_text(encoding="utf-8")
)["names"]
T = datetime(2026, 1, 1, tzinfo=UTC)


def debit(i: int, name: str, channel: str = "upi") -> Txn:
    return Txn(i, "HDFC", "debit", "debit", 10_000 + i, "0001", channel, name, T)


NO_OWNER = OwnerData()


def one(name: str, owner: OwnerData = NO_OWNER):
    t = debit(1, name)
    c = categorise([t], owner, derive([t], owner))[1]
    return c.category, c.rule


def test_at_least_150_payees_get_their_category() -> None:
    assert len(NAMES) >= 150 and {c for _, c in NAMES} <= set(CATEGORIES)
    txns = [debit(i, name) for i, (name, _) in enumerate(NAMES, 1)]
    got = categorise(txns, OwnerData(), derive(txns))
    wrong = [(name, want, got[i].category, got[i].rule)
             for i, (name, want) in enumerate(NAMES, 1) if got[i].category != want]  # fmt: skip
    assert wrong == []
    assert all(got[i].rule in GUESS_RULES | {"NONE", "KW_conflict"} for i in got)
    # Every category the dictionary serves is reached by some payee.
    assert {c for _, c in NAMES} >= set(words14.KNOWN) - {"emi_loans"}


def test_the_dictionary_has_300_entries_or_more() -> None:
    sizes = words14.size()
    assert sum(sizes.values()) >= 300
    assert set(sizes) <= set(CATEGORIES)
    assert not set(words14.WEAK_WORDS) & set(words14.STRONG_WORDS)  # one kind each


def test_tricky_names() -> None:
    # Personal names that hold a keyword's or brand's letters stay People.
    for name in ("Chaitanya Kumar", "Amulya Reddy", "Saloni Sharma", "Medicherla Ravi",
                 "Rentala Srinivas", "Giftson Raj", "Pizzaro Fernandes"):  # fmt: skip
        assert one(name) == ("people", "PERSON_name"), name
    # A weak word never beats a clearly personal name; with no person, it decides.
    assert one("Gift Mathew") == ("people", "PERSON_name")
    assert one("Lakshmi Temple") == ("people", "PERSON_name")
    assert one("Temple") == ("gifts_donations", "KEYWORD_weak")
    assert one("Sri Rama Temple Trust")[0] == "gifts_donations"  # two weak words agree
    # A business name with no category word, ambiguous words, masked UPI IDs: Uncategorised.
    for name in ("Vijaya Lakshmi Enterprise", "Hotel Annapoorna", "Grab N Go", "*ahad@oksbi",
                 "District Court Fees", "Om Shanti Store"):  # fmt: skip
        assert one(name)[0] == "uncategorised", name
    # Known names: whole words, written as one word, at the start of a word.
    assert one("chaipoint.blr@icici") == ("food_drinks", "KNOWN")
    assert one("stanzaliving@yesbank") == ("rent_hostel", "KNOWN")
    assert one("Hungerhalt Foodfill") == ("food_drinks", "KEYWORD")  # a stem and a keyword
    # The longest name wins: "green trends" (a salon) over "trends" (clothes).
    assert one("Green Trends Salon") == ("personal_care", "KNOWN")


def test_precedence_owner_rule_brand_known_keyword_person_weak() -> None:
    swiggy = "SWIGGY CHAI POINT"  # a brand the merchant engine knows, and a known name
    assert one(swiggy) == ("food_drinks", "BRAND")
    assert one("CHAI POINT PHARMACY") == ("food_drinks", "KNOWN")  # known name over keyword
    assert one("Ravi Pharmacy") == ("health", "KEYWORD")  # keyword over a name's shape
    owner_rule = OwnerData(parties=(Party("business", texts=("CHAI POINT",), category="travel"),))
    assert one("CHAI POINT", owner_rule) == ("travel", "OWNER_party")  # rule over known name
    t = debit(1, "CHAI POINT")
    answered = OwnerData(
        parties=(Party("business", texts=("CHAI POINT",), category="travel"),),
        categories={1: "groceries"},
    )
    assert categorise([t], answered, derive([t], answered))[1].category == "groceries"


def test_a_category_never_moves_a_total() -> None:
    from app.engine.reconcile import totals

    txns = [debit(i, name) for i, (name, _) in enumerate(NAMES, 1)]
    result = derive(txns)
    ever = (datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))
    old = categorise(txns, OwnerData(), result, "1.3.0")
    new = categorise(txns, OwnerData(), result)
    assert old != new  # the split changes
    t = totals(txns, result.roles, *ever)
    assert t.spent_paise == sum(x.amount_paise for x in txns)  # Spent does not
