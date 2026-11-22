"""Categorise: exactly one category for every transaction, never blank.

Runs after Reconcile, on its result. Pure: no database, clock, network or randomness.
A category is stored as a stable slug and shown by its name; the list is fixed (D-056).

Precedence for a transaction that counts in Spent (role spend, card_bill_counted, or an
unlinked refund). The first match decides; each result has a rule code and a basis:
  OWNER_txn       the owner's decision on this transaction                      owner
  OWNER_party     the default category of the owner party it matches            owner
  CH_atm          debit, channel atm                              Cash          engine
  ROLE_card_bill  role card_bill_counted                          Card bill     engine
  CH_emi          debit, channel emi                              EMI & Loans   engine
  HINT_fee        debit with hint bank_charge                     Fees & Charges engine
  BRAND           the merchant is in the brand dictionary         its category  engine
  KEYWORD         every category keyword in the name, or in the words of its UPI ID,
                  agrees (D-119: a curated list per category)     that category engine
  KW_conflict     keywords of two categories                      Uncategorised engine
  PERSON          debit to an owner party of kind person (the owner answered Friend)
                                                                  People        engine
  Since categorise-1.3.0 (D-133) a debit is People on its own only when it is clearly a
  person's, and never with anything business-like (business_like(): a business word in the
  name or the UPI ID, a gateway prefix, a domain, digits in the name, a merchant UPI ID or
  handle, a card or AutoPay payment). A party of kind business is never People.
  PERSON_name     2 to 4 words of letters, one of 3+ letters (initials allowed), or an
                  honorific (Mr/Ms/Mrs/Dr/Shri/Smt) and up to 4 words  People    engine
  PERSON_vpa      a personal UPI ID (a mobile number, or letters, digits and dots, at a
                  consumer app's or a bank's handle) with no name, or with one word
                                                                  People        engine
  NONE            anything else: a business-looking or an ambiguous name (one word, five
                  words, a masked UPI ID): To-do asks             Uncategorised engine
BRAND, KEYWORD, PERSON_name and PERSON_vpa are guesses from the name: the app says so
(GUESS_RULES). Totals never depend on a category.
categorise(rules="1.2.0") still gives the 1.2.0 answer (PERSON from the merchant engine's
kind, NAME_person), for `category-diff` only.
A linked refund takes the category (and basis) of its purchase: RF_linked. An unlinked
refund is categorised by its own merchant (owner party, brand, keyword), else NONE.

A transaction that is not spending (payback, income, self_transfer, card_bill_excluded,
fd_move, investment, duplicate, ignored, uncertain) carries a fixed category for its role, rule
NS_<role>; it is never part of a breakdown. An owner decision still wins on it.

breakdown() sums a date range by category; its values add up exactly to Spent.
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from app.engine.merchant import BUSINESS_WORDS, HONORIFICS, brands, parts
from app.engine.reconcile import (
    COUNTED,
    Derived,
    OwnerData,
    Result,
    Totals,
    Txn,
    counted,
    totals,
)

CATEGORISE_VERSION = "categorise-1.3.0"

# slug -> name. The slug is stored and never changes; a new category needs no migration.
CATEGORIES = {
    "food_drinks": "Food & Drinks",
    "groceries": "Groceries",
    "travel": "Travel",
    "shopping": "Shopping",
    "bills_recharges": "Bills & Recharges",
    "subscriptions": "Subscriptions",
    "health": "Health",
    "personal_care": "Personal Care",
    "entertainment": "Entertainment",
    "education": "Education",
    "rent_hostel": "Rent & Hostel",
    "emi_loans": "EMI & Loans",
    "investments": "Investments",
    "gifts_donations": "Gifts & Donations",
    "people": "People",
    "cash": "Cash",
    "card_bill": "Card bill",
    "fees_charges": "Fees & Charges",
    "other": "Other",
    "uncategorised": "Uncategorised",
}
UNCATEGORISED = "uncategorised"
# Roles that count in Spent; a refund counts with a minus sign.
SPENDING_ROLES = frozenset(role for role, (total, _) in COUNTED.items() if total == "spent")
# What a transaction that is not spending carries, so the column is never blank.
NOT_SPENDING = {
    "payback": "people",
    "income": "other",
    "self_transfer": "other",
    "card_bill_excluded": "card_bill",
    "fd_move": "investments",
    "investment": "investments",
    "duplicate": "other",
    "ignored": "other",
    "uncertain": "other",
}
RULES = (
    "OWNER_txn",
    "OWNER_party",
    "RF_linked",
    "CH_atm",
    "ROLE_card_bill",
    "CH_emi",
    "HINT_fee",
    "BRAND",
    "KEYWORD",
    "KW_conflict",
    "PERSON",
    "PERSON_name",
    "PERSON_vpa",
    "NAME_person",  # categorise-1.2.0 only (category-diff)
    "NONE",
    *(f"NS_{role}" for role in NOT_SPENDING),
)

# Every brand in brands.json has one category (checked by a test). A wallet or payment
# app says nothing about what was bought, so it stays Uncategorised for the owner.
BRAND_CATEGORIES = {
    "amazon": "shopping",
    "flipkart": "shopping",
    "myntra": "shopping",
    "ajio": "shopping",
    "meesho": "shopping",
    "nykaa": "personal_care",
    "tata_cliq": "shopping",
    "swiggy": "food_drinks",
    "zomato": "food_drinks",
    "blinkit": "groceries",
    "zepto": "groceries",
    "bigbasket": "groceries",
    "jiomart": "groceries",
    "dmart": "groceries",
    "reliance_digital": "shopping",
    "croma": "shopping",
    "vijay_sales": "shopping",
    "decathlon": "shopping",
    "ikea": "shopping",
    "lenskart": "health",
    "firstcry": "shopping",
    "shoppers_stop": "shopping",
    "westside": "shopping",
    "pantaloons": "shopping",
    "tanishq": "shopping",
    "pharmeasy": "health",
    "tata_1mg": "health",
    "apollo_pharmacy": "health",
    "medplus": "health",
    "netmeds": "health",
    "uber": "travel",
    "ola": "travel",
    "rapido": "travel",
    "irctc": "travel",
    "makemytrip": "travel",
    "goibibo": "travel",
    "cleartrip": "travel",
    "redbus": "travel",
    "ixigo": "travel",
    "indigo": "travel",
    "air_india": "travel",
    "oyo": "travel",
    "bookmyshow": "entertainment",
    "pvr_inox": "entertainment",
    "netflix": "subscriptions",
    "spotify": "subscriptions",
    "google": "subscriptions",
    "microsoft": "subscriptions",
    "openai": "subscriptions",
    "jiohotstar": "subscriptions",
    "sonyliv": "subscriptions",
    "zee5": "subscriptions",
    "jio": "bills_recharges",
    "airtel": "bills_recharges",
    "vi": "bills_recharges",
    "bsnl": "bills_recharges",
    "tata_play": "bills_recharges",
    "paytm": "uncategorised",
    "phonepe": "uncategorised",
    "cred": "card_bill",
    "mobikwik": "uncategorised",
    "lic": "bills_recharges",
    "starbucks": "food_drinks",
    "dominos": "food_drinks",
    "mcdonalds": "food_drinks",
    "kfc": "food_drinks",
    "pizza_hut": "food_drinks",
    "burger_king": "food_drinks",
    "subway": "food_drinks",
    "haldirams": "food_drinks",
    "indian_oil": "travel",
    "bharat_petroleum": "travel",
    "hindustan_petroleum": "travel",
    "urban_company": "other",
}

# Whole words of the merchant name or of its UPI ID (D-119). Only words whose meaning is
# clear; generic ones (store, shop, traders, services, hotel, hall, depot, ...) are left out
# on purpose: a business with no keyword stays Uncategorised and To-do asks.
_KEYWORDS = {
    "food_drinks": (
        "restaurant restaurants cafe cafes dhaba bakery bakers bakes sweets food foods foodfill "
        "foodie kitchen canteen caterers catering mess tiffin tiffins bhojanalaya juice juices "
        "tea chai coffee snacks biryani pizza pizzeria burger burgers shawarma momos eatery "
        "eats bistro wines bar swiggy zomato"
    ),
    "groceries": (
        "kirana provision provisions supermarket supermart hypermarket mart grocery groceries "
        "dairy milk fruits vegetables veggies chicken mutton meat dmart bigbasket "
        "blinkit zepto instamart"
    ),
    "travel": (
        "travels travel tours cabs cab taxi fuels petroleum petrol lodge inn residency resort "
        "resorts irctc rail railway railways uber ola rapido metro bus buses airlines airways "
        "indigo airport parking fastag"
    ),
    "shopping": (
        "garments textiles fashion fashions boutique tailors footwear sarees silks electronics "
        "electricals mobiles computers furniture jewellers jewellery emporium showroom "
        "collections apparel toys"
    ),
    "health": (
        "pharmacy pharma medical medicals medicos chemist chemists drugs surgicals hospital "
        "hospitals clinic clinics diagnostics diagnostic labs lab dental dentist opticals "
        "optical homoeo homeo homoeopathy ayurveda ayurvedic apollo 1mg healthcare"
    ),
    "personal_care": "salon saloon parlour laundry cleaners gym fitness spa barber",
    "subscriptions": "netflix hotstar subscription subscriptions spotify youtube",
    "entertainment": "cinema cinemas cineplex movies theatre theatres multiplex pvr inox gaming",
    "education": (
        "college school university academy institute coaching classes tuition tutorials "
        "stationery stationers books book library"
    ),
    "rent_hostel": "hostel hostels",
    "bills_recharges": (
        "telecom communications insurance electricity power recharge broadband gas water "
        "bescom tneb mseb"
    ),
    "emi_loans": "finance",
    # Not business keywords of the merchant engine: the only words that name an investment
    # on text alone. Investment senders themselves stay excluded until Phase 6 (D-026).
    "investments": "mutual securities broking demat",
}
KEYWORD_CATEGORIES = {word: slug for slug, words in _KEYWORDS.items() for word in words.split()}
INVESTMENT_WORDS = frozenset(_KEYWORDS["investments"].split())

_EVER = (datetime.min.replace(tzinfo=UTC), datetime.max.replace(tzinfo=UTC))


@dataclass(frozen=True)
class Categorised:
    category: str  # a slug of CATEGORIES
    rule: str
    basis: str  # engine or owner


def categorise(
    txns: Iterable[Txn], owner: OwnerData, result: Result, rules: str = "1.3.0"
) -> dict[int, Categorised]:
    """One Categorised per transaction, keyed and ordered by transaction id.

    `rules="1.2.0"`: the person rules of categorise-1.2.0, for category-diff only."""
    if rules not in ("1.2.0", "1.3.0"):
        raise ValueError("rules must be 1.2.0 or 1.3.0")
    stated = [p.category for p in owner.parties if p.category] + list(owner.categories.values())
    if any(slug not in CATEGORIES for slug in stated):
        raise ValueError("owner category: not a category of the list")
    rows = sorted(txns, key=lambda t: t.id)
    out = {t.id: _one(t, result.roles[t.id], owner, result, rules) for t in rows}
    by_id = {t.id: t for t in rows}
    for link in result.links:  # ordered by ids: a refund takes its first linked purchase
        if link.kind != "refund" or link.status != "linked":
            continue
        a, b = by_id[link.txn_a], by_id[link.txn_b]
        purchase, refund = (a, b) if a.direction == "debit" else (b, a)
        is_refund = result.roles[refund.id].role == "refund"
        if is_refund and out[refund.id].rule not in ("RF_linked", "OWNER_txn"):
            bought = out[purchase.id]
            out[refund.id] = Categorised(bought.category, "RF_linked", bought.basis)
    return out


def _one(t: Txn, d: Derived, owner: OwnerData, result: Result, rules: str) -> Categorised:
    if (slug := owner.categories.get(t.id)) is not None:
        return Categorised(slug, "OWNER_txn", "owner")
    if d.role not in SPENDING_ROLES:
        return Categorised(NOT_SPENDING[d.role], f"NS_{d.role}", "engine")
    party = None if d.party is None else owner.parties[d.party]
    if party and party.category:
        return Categorised(party.category, "OWNER_party", "owner")
    merchant = result.merchants[t.id]
    if t.direction == "debit":  # role and channel
        if t.channel == "atm":
            return Categorised("cash", "CH_atm", "engine")
        if d.role == "card_bill_counted":
            return Categorised("card_bill", "ROLE_card_bill", "engine")
        if t.channel == "emi":
            return Categorised("emi_loans", "CH_emi", "engine")
        if "bank_charge" in t.hints:
            return Categorised("fees_charges", "HINT_fee", "engine")
    if merchant.brand_id:
        return Categorised(BRAND_CATEGORIES[merchant.brand_id], "BRAND", "engine")
    p = parts(t.counterparty_raw)
    words = (*p.tokens, *vpa_words(p.vpa)) if p else ()
    found = {KEYWORD_CATEGORIES[w] for w in words if w in KEYWORD_CATEGORIES}
    if len(found) == 1:
        return Categorised(found.pop(), "KEYWORD", "engine")
    if found:
        return Categorised(UNCATEGORISED, "KW_conflict", "engine")
    named = party.kind if party and party.kind in ("person", "business") else None
    if rules == "1.2.0":
        return _person_120(t, named or merchant.kind, named, p)
    if t.direction == "debit" and named == "person":  # the owner answered: a party wins
        return Categorised("people", "PERSON", "engine")
    if t.direction == "debit" and named is None and p and (rule := person_rule(p, merchant)):
        return Categorised("people", rule, "engine")
    return Categorised(UNCATEGORISED, "NONE", "engine")


def _person_120(t: Txn, kind: str, named: str | None, p) -> Categorised:
    """categorise-1.2.0, kept for category-diff: the merchant engine's kind decides, a
    business word of the 1.2.0 list stops it, NAME_person for an unsure name."""
    business_word = not named and bool(p and set(p.tokens) & _NOT_PERSON_120)
    if t.direction == "debit" and kind == "person" and not business_word:
        return Categorised("people", "PERSON", "engine")
    if t.direction == "debit" and kind == "unsure" and p and _looks_like_person_120(p):
        return Categorised("people", "NAME_person", "engine")
    return Categorised(UNCATEGORISED, "NONE", "engine")


# Words that make a name a business's, on top of the merchant engine's list (D-119).
_NOT_PERSON_120 = (
    BUSINESS_WORDS
    | frozenset(KEYWORD_CATEGORIES)
    | frozenset(
        "hall depot hotel hotels agency centre center solutions services technologies store "
        "stores traders enterprises pvt ltd llp works point house block".split()
    )
)
# categorise-1.3.0 (D-133): more words no Indian given name or surname is, so a name with one
# is never People. Whole words of the name or of the UPI ID's local part.
NOT_PERSON = _NOT_PERSON_120 | frozenset(
    """
    tech techno co and sons bros brothers india international global systems online digital
    payments pay media network networks infra exim plaza mall market complex palace bhavan
    court club station fuel auto autos cars estate farm farms garden gardens kart zone hub
    express care life world factory studios merchant merchants
    """.split()
)
# Payment gateways, aggregators and merchant QR schemes, in a UPI ID's local part or handle
# (whole words): a merchant collecting money, never a person (D-133).
MERCHANT_VPA_WORDS = frozenset(
    """
    rzp razorpay cashfree payu billdesk ccavenue juspay instamojo pinelabs mswipe ezetap
    easebuzz paytmqr bharatpe phonepe gpay mab biz qr pos upiqr payout collect billpay
    fbpe yespay
    """.split()
)
# Handles of consumer UPI apps and banks, where a person's UPI ID lives (D-133); never one
# that starts okbiz (a business account on Google Pay).
PERSONAL_HANDLE = re.compile(
    r"ok(?!biz)\w+|ybl|ibl|axl|apl|yapl|rapl|paytm|pt(?:yes|axis|hdfc|sbi)|upi|axisbank"
    r"|hdfcbank|icici|sbi|kotak|pnb|barodampay|aubank|idfcbank|indus|federal|rbl|yesbank"
)
_PERSONAL_LOCAL = re.compile(r"(?=.*[a-z])[a-z0-9.]{3,}")
_MOBILE_LOCAL = re.compile(r"(?:91)?[6-9]\d{9}")
# What the merchant engine reads as business-like: a card or AutoPay payment, a business
# word, a domain, a merchant UPI ID or handle, digits in the name, a gateway prefix, two
# brands at once.
BUSINESS_REASONS = frozenset(
    "R4_card R4_autopay R5_keyword R5_domain R5_merchant_vpa R5_business_handle R5_digits "
    "R2_gateway R3_tie".split()
)
GUESS_RULES = frozenset({"BRAND", "KEYWORD", "PERSON_name", "PERSON_vpa", "NAME_person"})


def business_like(p, merchant) -> bool:
    """Anything that says business: the 1.3.0 rules never call such a payee a person."""
    if BUSINESS_REASONS & set(merchant.reasons):
        return True
    local, _, handle = (p.vpa or "").partition("@")
    words = {*p.tokens, *vpa_words(p.vpa)}
    handle_words = {w for w in re.split(r"[^a-z]+", handle) if w}
    return bool(
        words & NOT_PERSON or (words | handle_words) & MERCHANT_VPA_WORDS or "biz" in handle
    )


def personal_vpa(vpa: str | None) -> bool:
    """A mobile number, or letters, digits and dots, at a consumer app's or a bank's handle.
    A masked UPI ID ("*k77@okhdfcbank") says too little."""
    local, _, handle = (vpa or "").partition("@")
    if not handle or not PERSONAL_HANDLE.fullmatch(handle):
        return False
    return bool(_MOBILE_LOCAL.fullmatch(local) or _PERSONAL_LOCAL.fullmatch(local))


def person_rule(p, merchant) -> str | None:
    """PERSON_name, PERSON_vpa, or None (Uncategorised) for a debit no owner party names."""
    if business_like(p, merchant):
        return None
    named = [w for w in p.tokens if w not in HONORIFICS]
    letters = bool(named) and all(w.isalpha() for w in named)
    if named:
        honorific = p.tokens[0] in HONORIFICS and len(named) <= 4  # "Mrs Kavitha"
        shaped = 2 <= len(named) <= 4 and any(len(w) >= 3 for w in named)
        if letters and (honorific or shaped):
            return "PERSON_name"
        # One word is a shop as often as a person: only with a personal UPI ID beside it.
        if letters and len(named) == 1 and personal_vpa(p.vpa):
            return "PERSON_vpa"
        return None
    return "PERSON_vpa" if personal_vpa(p.vpa) else None


def vpa_words(vpa: str | None) -> tuple[str, ...]:
    """The words of a UPI ID's local part: "swiggy.food@x" -> swiggy, food."""
    local = (vpa or "").partition("@")[0]
    return tuple(w for w in re.split(r"[^a-z]+", local.casefold()) if len(w) > 1)


_PERSONAL_HANDLE_120 = re.compile(r"ok\w+|axisbank|hdfcbank|icici|sbi|kotak|pnb|barodampay|upi")


def _looks_like_person_120(p) -> bool:
    """categorise-1.2.0's NAME_person: 2 to 4 words of letters (initials allowed),
    honorifics ignored, no business word; or no name and a personal-looking UPI ID."""
    named = [w for w in p.tokens if w not in HONORIFICS]
    if named:
        return (
            2 <= len(named) <= 4
            and all(w.isalpha() for w in named)
            and any(len(w) >= 3 for w in named)
            and not any(w in _NOT_PERSON_120 for w in named)
        )
    local, _, handle = (p.vpa or "").partition("@")
    return bool(
        handle and _PERSONAL_HANDLE_120.fullmatch(handle) and _PERSONAL_LOCAL.fullmatch(local)
    )


def breakdown(
    txns: Iterable[Txn],
    roles: Mapping[int, Derived],
    categories: Mapping[int, Categorised],
    start: datetime,
    end: datetime,
    invest: bool = False,
) -> dict[str, int]:
    """Signed paise per category for start <= txn_time_utc < end. The values sum to Spent
    (with the same `invest`, see reconcile.counted).

    A refund lowers its category in the range it arrives in, so a category can be negative.
    """
    out: Counter[str] = Counter()
    for t in txns:
        total, sign = counted(roles[t.id].role, t.direction, invest) or (None, 0)
        if total == "spent" and start <= t.txn_time_utc < end:
            out[categories[t.id].category] += sign * t.amount_paise
    return {slug: out[slug] for slug in CATEGORIES if slug in out}


def label_view(
    txns: Iterable[Txn],
    roles: Mapping[int, Derived],
    categories: Mapping[int, Categorised],
    labelled: Iterable[int],
    invest: bool = False,
) -> tuple[Totals, dict[str, int]]:
    """Spent, Paid back, Net and the category breakdown of one label, across all dates.

    `labelled`: the transactions that carry the label. A label never changes a category.
    """
    ids = set(labelled)
    mine = [t for t in txns if t.id in ids]
    return totals(mine, roles, *_EVER, invest), breakdown(mine, roles, categories, *_EVER, invest)


def check_brand_categories() -> None:
    """Every brand has exactly one category of the list."""
    if set(BRAND_CATEGORIES) != set(brands()) or not set(BRAND_CATEGORIES.values()) <= set(
        CATEGORIES
    ):
        raise ValueError("brand categories do not match the brand dictionary")
