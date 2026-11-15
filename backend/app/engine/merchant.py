"""Merchant normalisation: raw counterparty text -> a stable merchant.

normalise_merchant() decides whether a transaction's counterparty is a
business, a person, unsure or none, and gives it a stable merchant_key.
Pure: no database, clock, network or randomness. The only I/O is loading
brands.json once. Ambiguity always gives "unsure", never a guess.

Rules, in order (codes appear in Merchant.reasons):
  R0 no counterparty text, or channel atm: kind none
  R1 clean (NFKC, casefold, whitespace, outer punctuation); split a UPI ID
  R2 strip a payment-gateway prefix from the name (PAYTM*, RAZ*, ...)
  R3 brand dictionary, whole tokens, anchored at the start of the name (after a
     leading "www") or of the UPI local part; longest alias wins, a tie is no match
  R4 channel card or autopay: business
  R5 business and person signals; both or neither: unsure

Rules, signal lists, the dictionary and the key format are all part of
MERCHANT_VERSION: any change that can alter a key, a kind or a display name
bumps it. Owner data stores text, never a merchant_key (D-065).
"""

import json
import re
import string
import unicodedata
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

MERCHANT_VERSION = "merchant-1.1.1"

Kind = Literal["business", "person", "unsure", "none"]
Confidence = Literal["high", "low"]
Channel = Literal["card", "upi", "bank_transfer", "atm", "autopay", "other"]

# Parser channel (stored on every transaction) -> merchant channel.
PARSER_CHANNELS: dict[str, Channel] = {
    "debit_card": "card",
    "credit_card": "card",
    "upi": "upi",
    "netbanking": "bank_transfer",
    "neft": "bank_transfer",
    "imps": "bank_transfer",
    "atm": "atm",
    "e_mandate": "autopay",  # card AutoPay (SI Hub, Mandate ID)
    "nach": "autopay",  # ACH debit: always against a mandate
}

GATEWAY_PREFIXES = ("paytm", "raz", "pyu", "cca")  # only when followed by "*"
HONORIFICS = frozenset("mr mrs ms dr shri smt".split())
# Whole tokens only. Never a word of one or two letters, and never a word that
# is also a common Indian given name or surname.
BUSINESS_WORDS = frozenset(
    """
    pvt private ltd limited llp inc corp corporation company enterprise enterprises
    traders trading industries services solutions technologies agency agencies
    associates consultants consultancy ventures group distributors suppliers
    wholesale wholesalers exports imports impex infotech logistics
    store stores mart supermarket bazaar retail shop shoppe emporium depot outlet
    showroom kirana provision provisions bhandar general centre center corner point
    restaurant restaurants cafe hotel hotels dhaba bakery bakers sweets foods kitchen
    canteen caterers catering mess tiffin tiffins bhojanalaya juice juices tea chai
    coffee snacks biryani pizza dairy milk fruits vegetables chicken mutton meat
    wines bar lounge hostel hostels lodge inn residency resort resorts
    pharmacy pharma medical medicals medicos chemist chemists drugs surgicals hospital
    hospitals clinic diagnostics diagnostic labs lab dental opticals optical
    college school university academy institute coaching classes tuition tutorials
    xerox photostat stationery stationers printers books library
    motors automobiles garage tyres spares fuels petroleum petrol
    garments textiles fashion fashions boutique tailors footwear sarees silks
    electronics electricals mobiles computers telecom communications hardware paints
    furniture steel cement builders developers constructions properties realty
    jewellers jewellery salon saloon parlour laundry cleaners gym fitness studio
    travels tours cabs taxi couriers packers movers transport
    bank finance insurance
    """.split()
)
# UPI handles (the part after "@"). Consumer apps' handles are a person signal;
# business handles a business signal, like a merchant-style local part.
CONSUMER_HANDLES = frozenset("okaxis okhdfcbank okicici oksbi".split())
BUSINESS_HANDLE_PREFIXES = ("okbiz",)
TLDS = "com|in|net|org|io|app"

_DOMAIN = re.compile(rf"(?<![\w@])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:{TLDS})(?![\w@])")
_MESSRS = re.compile(r"(?<!\w)m/s(?!\w)")  # "M/S ABC" is a business form
_VPA = re.compile(r"(?<![\w.*@-])([a-z0-9.\-_*]+)@([a-z][a-z0-9.\-]*[a-z0-9])(?![\w@.\-])")
_GATEWAY = re.compile(rf"^(?:{'|'.join(GATEWAY_PREFIXES)}) ?\* ?")
_MOBILE = re.compile(r"(?:91)?[6-9]\d{9}")
_MERCHANT_LOCAL = re.compile(r"(?:paytmqr|bharatpe|vyapar|gpay-).*|q\d{6,}")
_OUTER = " \t.,;:!?'\"`()[]{}<>-_/\\|#~=+^"  # outer strip; "*" kept (UPI ID mask)
_APOSTROPHES = "'’"  # removed inside words: domino's -> dominos


@dataclass(frozen=True)
class Merchant:
    kind: Kind
    confidence: Confidence
    merchant_key: str | None
    display_name: str | None
    brand_id: str | None
    reasons: tuple[str, ...]
    version: str = MERCHANT_VERSION


@dataclass(frozen=True)
class Parts:
    """A counterparty split into what the rules look at."""

    name: str  # cleaned, casefolded, without the UPI ID and gateway prefix
    tokens: tuple[str, ...]  # name words: letters, marks and digits only
    vpa: str | None  # "local@handle", casefolded
    vpa_malformed: bool  # an "@" that is not a valid UPI ID
    gateway: bool  # a gateway prefix was removed


def tokens(text: str) -> tuple[str, ...]:
    """Words of letters, marks and digits. Apostrophes vanish; other characters split."""
    out = []
    for ch in text:
        if ch in _APOSTROPHES:
            continue
        out.append(ch if unicodedata.category(ch)[0] in "LMN" else " ")
    return tuple("".join(out).split())


def clean(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split()).strip(_OUTER)


def parts(counterparty: str | None) -> Parts | None:
    """R1 and R2. None when there is no text left to work with."""
    text = clean(counterparty or "")
    vpa = None
    if m := _VPA.search(text):
        vpa = m.group(0)
        text = clean(text[: m.start()] + " " + text[m.end() :])
    gateway = False
    if (stripped := _GATEWAY.sub("", text, count=1)) != text and tokens(stripped):
        text, gateway = stripped, True
    words = tokens(text)
    if not words and vpa is None:
        return None
    return Parts(text, words, vpa, vpa is None and "@" in text, gateway)


@dataclass(frozen=True)
class Brand:
    id: str
    name: str
    aliases: tuple[str, ...]


@cache
def brands() -> dict[str, Brand]:
    data = json.loads(Path(__file__).with_name("brands.json").read_text(encoding="utf-8"))
    out = {}
    for b in data["brands"]:
        if b["id"] in out:
            raise ValueError(f"duplicate brand id {b['id']}")
        out[b["id"]] = Brand(b["id"], b["name"], tuple(b["aliases"]))
    return out


@cache
def alias_index() -> dict[tuple[str, ...], str]:
    """Alias tokens -> brand id. Each brand's display name is an alias too."""
    index: dict[tuple[str, ...], str] = {}
    for b in brands().values():
        for alias in {*b.aliases, b.name}:
            key = tokens(clean(alias))
            if index.setdefault(key, b.id) != b.id:
                raise ValueError(f"alias {alias!r} belongs to two brands")
    return index


def match_brand(*starts: tuple[str, ...]) -> tuple[str | None, bool]:
    """(brand_id, tie). Aliases match whole tokens at the start of each word list.

    Callers pass the name words and the UPI local part words. The longest alias
    wins (tokens, then characters); two brands of the same length: a tie, no match.
    """
    index = alias_index()
    found = {
        (n, len(" ".join(words[:n])), index[words[:n]])
        for words in starts
        for n in range(1, len(words) + 1)
        if words[:n] in index
    }
    if not found:
        return None, False
    best = max(size for *size, _ in found)
    ids = {bid for *size, bid in found if size == best}
    return (ids.pop(), False) if len(ids) == 1 else (None, True)


def channel_for(parser_channel: str | None, hints: tuple[str, ...] | list[str] = ()) -> Channel:
    """Merchant channel from a transaction's stored channel and hints."""
    if parser_channel == "upi" and "autopay" in hints:  # HDFC H17, UPI AutoPay
        return "autopay"
    return PARSER_CHANNELS.get(parser_channel or "", "other")


def _key(p: Parts) -> str:
    if p.vpa:
        return f"vpa:{p.vpa}"
    words = list(p.tokens)
    while len(words) > 1 and words[0] in HONORIFICS:
        words.pop(0)
    return "name:" + " ".join(words)


def _vpa_words(vpa: str | None) -> tuple[str, ...]:
    return tuple(w for w in re.split(r"[.\-_*]+", vpa.split("@")[0]) if w) if vpa else ()


def _name_words(words: tuple[str, ...]) -> tuple[str, ...]:
    return words[1:] if words[:1] == ("www",) else words


def _display(p: Parts) -> str | None:
    """The name in title case when there is name text, else the UPI ID in lower case."""
    return string.capwords(p.name) if p.tokens else p.vpa  # parts() never returns neither


def normalise_merchant(counterparty: str | None, channel: Channel) -> Merchant:
    """Raw counterparty text plus merchant channel -> Merchant (see module docstring)."""
    if channel == "atm":
        return Merchant("none", "high", None, None, None, ("R0_atm",))
    p = parts(counterparty)
    if p is None:
        return Merchant("none", "high", None, None, None, ("R0_no_text",))

    reasons = []
    if p.vpa:
        reasons.append("R1_vpa")
    if p.vpa_malformed:
        reasons.append("R1_vpa_malformed")
    if p.gateway:
        reasons.append("R2_gateway")

    brand_id, tie = match_brand(_name_words(p.tokens), _vpa_words(p.vpa))
    if brand_id:
        brand = brands()[brand_id]
        reasons.append("R3_brand")
        return Merchant("business", "high", f"brand:{brand_id}", brand.name, brand_id, (*reasons,))
    if tie:
        reasons.append("R3_tie")

    key, display = _key(p), _display(p)
    if channel in ("card", "autopay"):
        reasons.append(f"R4_{channel}")
        return Merchant("business", "high", key, display, None, (*reasons,))

    business, person = _signals(p)
    reasons += business + person
    if business and not person:
        low = business == ["R5_digits"]
        reasons.append("R5_business")
        return Merchant("business", "low" if low else "high", key, display, None, (*reasons,))
    if person and not business:
        sure = "R5_honorific" in person or {"R5_mobile_vpa", "R5_person_name"} <= set(person)
        reasons.append("R5_person")
        return Merchant("person", "high" if sure else "low", key, display, None, (*reasons,))
    reasons.append("R5_unsure_mixed" if business else "R5_unsure_none")
    return Merchant("unsure", "low", key, display, None, (*reasons,))


def _signals(p: Parts) -> tuple[list[str], list[str]]:
    words = p.tokens
    local, _, handle = (p.vpa or "").partition("@")
    has_keyword = any(w in BUSINESS_WORDS for w in words) or bool(_MESSRS.search(p.name))
    has_domain = bool(_DOMAIN.search(p.name))
    business = [
        code
        for code, hit in (
            ("R5_keyword", has_keyword),
            ("R5_domain", has_domain),
            ("R5_merchant_vpa", bool(local and _MERCHANT_LOCAL.fullmatch(local))),
            ("R5_business_handle", handle.startswith(BUSINESS_HANDLE_PREFIXES)),
            ("R5_digits", any(ch.isdigit() for w in words for ch in w)),
        )
        if hit
    ]
    named = [w for w in words if w not in HONORIFICS]
    person_name = (
        2 <= len(named) <= 4
        and all(unicodedata.category(ch)[0] in "LM" for w in named for ch in w)
        and not (has_keyword or has_domain)  # "shop.in" is a domain, not two names
    )
    person = [
        code
        for code, hit in (
            ("R5_honorific", bool(words) and words[0] in HONORIFICS and len(words) > 1),
            ("R5_mobile_vpa", bool(local and _MOBILE.fullmatch(local))),
            ("R5_consumer_vpa", handle in CONSUMER_HANDLES),
            ("R5_person_name", person_name),
        )
        if hit
    ]
    return business, person
