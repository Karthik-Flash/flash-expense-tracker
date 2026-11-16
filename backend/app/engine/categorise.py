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
  KEYWORD         every category keyword in the name agrees       that category engine
  KW_conflict     keywords of two categories                      Uncategorised engine
  PERSON          debit to a person                               People        engine
  NONE            nothing matched                                 Uncategorised engine
A linked refund takes the category (and basis) of its purchase: RF_linked. An unlinked
refund is categorised by its own merchant (owner party, brand, keyword), else NONE.

A transaction that is not spending (payback, income, self_transfer, card_bill_excluded,
fd_move, duplicate, ignored, uncertain) carries a fixed category for its role, rule
NS_<role>; it is never part of a breakdown. An owner decision still wins on it.

breakdown() sums a date range by category; its values add up exactly to Spent.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from app.engine.merchant import brands, parts
from app.engine.reconcile import COUNTED, Derived, OwnerData, Result, Totals, Txn, totals

CATEGORISE_VERSION = "categorise-1.0.0"

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

# Whole words of the merchant name. Only business keywords whose meaning is clear; generic
# ones (store, traders, services, hotel, ...) are left out on purpose.
_KEYWORDS = {
    "food_drinks": (
        "restaurant restaurants cafe dhaba bakery bakers sweets foods kitchen canteen caterers "
        "catering mess tiffin tiffins bhojanalaya juice juices tea chai coffee snacks biryani "
        "pizza wines bar"
    ),
    "groceries": "kirana provision provisions supermarket dairy milk fruits vegetables chicken "
    "mutton meat",
    "travel": "travels tours cabs taxi fuels petroleum petrol lodge inn residency resort resorts",
    "shopping": (
        "garments textiles fashion fashions boutique tailors footwear sarees silks electronics "
        "electricals mobiles computers furniture jewellers jewellery emporium showroom"
    ),
    "health": (
        "pharmacy pharma medical medicals medicos chemist chemists drugs surgicals hospital "
        "hospitals clinic diagnostics diagnostic labs lab dental opticals optical"
    ),
    "personal_care": "salon saloon parlour laundry cleaners gym fitness",
    "education": (
        "college school university academy institute coaching classes tuition tutorials "
        "stationery stationers books library"
    ),
    "rent_hostel": "hostel hostels",
    "bills_recharges": "telecom communications insurance",
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


def categorise(txns: Iterable[Txn], owner: OwnerData, result: Result) -> dict[int, Categorised]:
    """One Categorised per transaction, keyed and ordered by transaction id."""
    stated = [p.category for p in owner.parties if p.category] + list(owner.categories.values())
    if any(slug not in CATEGORIES for slug in stated):
        raise ValueError("owner category: not a category of the list")
    rows = sorted(txns, key=lambda t: t.id)
    out = {t.id: _one(t, result.roles[t.id], owner, result) for t in rows}
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


def _one(t: Txn, d: Derived, owner: OwnerData, result: Result) -> Categorised:
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
    found = {KEYWORD_CATEGORIES[w] for w in (p.tokens if p else ()) if w in KEYWORD_CATEGORIES}
    if len(found) == 1:
        return Categorised(found.pop(), "KEYWORD", "engine")
    if found:
        return Categorised(UNCATEGORISED, "KW_conflict", "engine")
    if t.direction == "debit" and (party.kind if party else merchant.kind) == "person":
        return Categorised("people", "PERSON", "engine")
    return Categorised(UNCATEGORISED, "NONE", "engine")


def breakdown(
    txns: Iterable[Txn],
    roles: Mapping[int, Derived],
    categories: Mapping[int, Categorised],
    start: datetime,
    end: datetime,
) -> dict[str, int]:
    """Signed paise per category for start <= txn_time_utc < end. The values sum to Spent.

    A refund lowers its category in the range it arrives in, so a category can be negative.
    """
    out: Counter[str] = Counter()
    for t in txns:
        total, sign = COUNTED.get(roles[t.id].role, (None, 0))
        if total == "spent" and start <= t.txn_time_utc < end:
            out[categories[t.id].category] += sign * t.amount_paise
    return {slug: out[slug] for slug in CATEGORIES if slug in out}


def label_view(
    txns: Iterable[Txn],
    roles: Mapping[int, Derived],
    categories: Mapping[int, Categorised],
    labelled: Iterable[int],
) -> tuple[Totals, dict[str, int]]:
    """Spent, Paid back, Net and the category breakdown of one label, across all dates.

    `labelled`: the transactions that carry the label. A label never changes a category.
    """
    ids = set(labelled)
    mine = [t for t in txns if t.id in ids]
    return totals(mine, roles, *_EVER), breakdown(mine, roles, categories, *_EVER)


def check_brand_categories() -> None:
    """Every brand has exactly one category of the list."""
    if set(BRAND_CATEGORIES) != set(brands()) or not set(BRAND_CATEGORIES.values()) <= set(
        CATEGORIES
    ):
        raise ValueError("brand categories do not match the brand dictionary")
