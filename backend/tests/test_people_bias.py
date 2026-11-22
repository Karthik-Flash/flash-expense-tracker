"""People only when clearly personal (categorise-1.3.0, D-133). FAKE counterparties only.

Under 1.2.0 a debit was People when the merchant engine said person (a consumer UPI handle
alone, a mobile number UPI ID, an honorific, two to four plain words) and no business word
was in the name, or when the engine was unsure and the name looked like a person's
(NAME_person), even with a merchant QR UPI ID beside it. 1.3.0 asks for a clearly personal
name or UPI ID and nothing business-like anywhere (business_like()); anything else is
Uncategorised for the owner to answer, never People.
"""

from datetime import UTC, datetime

import pytest

from app.engine.categorise import categorise
from app.engine.credits import PaybackRow, payback_links
from app.engine.reconcile import OwnerData, Party, Txn, derive, totals

T = datetime(2026, 3, 2, tzinfo=UTC)
EVER = (datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))

# (counterparty as the bank wrote it, channel, kind of payee, category 1.3.0 gives)
TABLE = [
    # person: a personal-looking name, a personal UPI ID, or both
    ("Ravi Teja", "upi", "person", "people"),
    ("Mr Kiran Rao", "upi", "person", "people"),
    ("Smt Lakshmi", "upi", "person", "people"),
    ("Dr Anand Kumar", "neft", "person", "people"),
    ("A Srinivas", "imps", "person", "people"),
    ("Priya Nair", "upi", "person", "people"),
    ("Mohammed Irfan Khan", "upi", "person", "people"),
    ("test.ravi92@okaxis", "upi", "person", "people"),
    ("9000000021@ybl", "upi", "person", "people"),
    ("919000000022@paytm", "upi", "person", "people"),
    ("test.priya@okhdfcbank", "upi", "person", "people"),
    ("Arun test.arun7@oksbi", "upi", "person", "people"),
    ("Neha Gupta test.neha@okicici", "upi", "person", "people"),
    ("test.gopal@ibl", "upi", "person", "people"),
    ("Suresh Babu", "netbanking", "person", "people"),
    # business: a business word, a merchant UPI ID or handle, a gateway, a card, digits
    ("Ravi Teja Enterprises", "upi", "business", "uncategorised"),
    ("Sharma and Sons", "upi", "business", "uncategorised"),
    ("Kumar Traders", "upi", "business", "uncategorised"),
    ("Lakshmi Stores", "upi", "business", "uncategorised"),
    ("Test Infotech Pvt Ltd", "neft", "business", "uncategorised"),
    ("Sai Tech Solutions", "upi", "business", "uncategorised"),
    ("Royal Agency", "upi", "business", "uncategorised"),
    ("Balaji Mart", "upi", "business", "groceries"),
    ("Fresh Foods Co", "upi", "business", "food_drinks"),
    ("Sunrise Hospital", "upi", "business", "health"),
    ("Apex Pharma", "upi", "business", "health"),
    ("Hotel Green Park", "upi", "business", "uncategorised"),
    ("City Cafe", "upi", "business", "food_drinks"),
    ("Venkat Medical", "upi", "business", "health"),
    ("Mohan Lal paytmqr1234567@paytm", "upi", "business", "uncategorised"),
    ("Q123456789@ybl", "upi", "business", "uncategorised"),
    ("Suresh Kumar test.merchant@okbizaxis", "upi", "business", "uncategorised"),
    ("Anil Kumar bharatpe.9000000023@fbpe", "upi", "business", "uncategorised"),
    ("test.shop.rzp@icici", "upi", "business", "uncategorised"),
    ("PAYTM*Ravi Kumar", "upi", "business", "uncategorised"),
    ("Ravi Kumar", "debit_card", "business", "uncategorised"),
    ("Priya Sharma", "e_mandate", "business", "uncategorised"),
    ("Kiran 24x7", "upi", "business", "uncategorised"),
    ("Test India Payments", "upi", "business", "uncategorised"),
    ("testshop.in", "upi", "business", "uncategorised"),
    # ambiguous: too little to tell; never People
    ("Ganesh", "upi", "ambiguous", "uncategorised"),
    ("Sri Lakshmi Venkateswara Swamy Seva", "upi", "ambiguous", "uncategorised"),
    ("*k77@okhdfcbank", "upi", "ambiguous", "uncategorised"),
    ("test.sai@unknownbank", "upi", "ambiguous", "uncategorised"),
    ("Krishna test.kk@yesbankltd", "upi", "ambiguous", "uncategorised"),
    ("Raju 9000000024@unknownpsp", "upi", "ambiguous", "uncategorised"),
]


def debits() -> list[Txn]:
    return [Txn(i, "HDFC", "debit", "debit", 10_000 + i, "0001", channel, text, T)
            for i, (text, channel, _, _) in enumerate(TABLE, 1)]  # fmt: skip


def both() -> tuple[list[Txn], dict, dict]:
    txns = debits()
    result = derive(txns)
    return (
        txns,
        categorise(txns, OwnerData(), result, "1.2.0"),
        categorise(txns, OwnerData(), result),
    )


def test_the_regression_table() -> None:
    assert len(TABLE) >= 40 and {kind for *_, kind, _ in TABLE} == {
        "person",
        "business",
        "ambiguous",
    }
    txns, _, new = both()
    wrong = [(TABLE[i - 1][0], TABLE[i - 1][3], new[i].category, new[i].rule)
             for i in new if new[i].category != TABLE[i - 1][3]]  # fmt: skip
    assert wrong == []
    for i, (_, _, kind, _) in enumerate(TABLE, 1):
        assert (new[i].category == "people") == (kind == "person")  # People only for persons
        if kind == "person":
            assert new[i].rule in ("PERSON_name", "PERSON_vpa")


def test_what_changed_from_1_2_0() -> None:
    """The People bias: 1.2.0 called these business or ambiguous payees People."""
    _, old, new = both()
    leaving = sorted(TABLE[i - 1][0] for i in old if old[i].category == "people" != new[i].category)
    assert leaving == [
        "*k77@okhdfcbank",  # a masked UPI ID says too little
        "Anil Kumar bharatpe.9000000023@fbpe",  # a merchant QR scheme (NAME_person)
        "Mohan Lal paytmqr1234567@paytm",  # the same (NAME_person)
        "PAYTM*Ravi Kumar",  # a gateway prefix: a merchant
        "Raju 9000000024@unknownpsp",  # a mobile number, but not at a consumer app's handle
        "Sharma and Sons",  # "and sons": a business
        "Suresh Kumar test.merchant@okbizaxis",  # a business handle (NAME_person)
        "Test India Payments",  # business words
        "test.shop.rzp@icici",  # a gateway (Razorpay) UPI ID (NAME_person)
    ]
    # The one payee that becomes People: a name handle at PhonePe's ibl, a consumer app.
    entering = [TABLE[i - 1][0] for i in new if new[i].category == "people" != old[i].category]
    assert entering == ["test.gopal@ibl"]


def test_an_owner_answer_still_wins_both_ways() -> None:
    """Friend on a business-looking name is People; a party of kind business never is."""
    shop = Txn(1, "HDFC", "debit", "debit", 10_000, "0001", "upi", "Kumar Traders", T)
    named = OwnerData(parties=(Party("person", texts=("Kumar Traders",)),))
    assert categorise([shop], named, derive([shop], named))[1].rule == "PERSON"
    ravi = Txn(2, "HDFC", "debit", "debit", 10_000, "0001", "upi", "Ravi Teja", T)
    business = OwnerData(parties=(Party("business", texts=("Ravi Teja",)),))
    assert categorise([ravi], business, derive([ravi], business))[2].category == "uncategorised"


@pytest.mark.parametrize("rules", ["1.2.0", "1.3.0"])
def test_the_people_change_moves_no_role_link_or_total(rules) -> None:
    """Categories come after roles: a People change cannot touch a payback, a link or Net."""
    txns = debits()
    friend = TABLE[7][0]  # test.ravi92@okaxis, paid above
    txns.append(Txn(999, "HDFC", "credit", "credit", 5_000, "0001", "upi", friend, T))
    result = derive(txns)
    categories = categorise(txns, OwnerData(), result, rules)
    assert result.roles[999].role == "payback"  # the same under either rule set
    t = totals(txns, result.roles, *EVER)
    assert (t.spent_paise, t.paid_back_paise, t.to_confirm_paise) == (
        sum(x.amount_paise for x in txns if x.direction == "debit"), 0, 5_000,
    )  # fmt: skip
    rows = [PaybackRow(x.id, x.direction, x.amount_paise, x.txn_time_utc,
                       result.merchants[x.id].merchant_key, result.roles[x.id].role)
            for x in txns]  # fmt: skip
    assert [(x.debit, x.credit) for x in payback_links(rows)] == [(8, 999)]
    assert categories[999].category == "people"  # NS_payback either way
