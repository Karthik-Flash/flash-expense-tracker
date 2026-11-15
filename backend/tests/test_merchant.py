"""Merchant normalisation engine (merchant-1.1.0). Fake values only."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.engine import merchant, parse_message
from app.engine.merchant import (
    BUSINESS_WORDS,
    GATEWAY_PREFIXES,
    MERCHANT_VERSION,
    PARSER_CHANNELS,
    Merchant,
    alias_index,
    brands,
    channel_for,
    match_brand,
    normalise_merchant,
    tokens,
)
from app.engine.parsers.hdfc import TEMPLATES

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample" / "redacted_sample.json"

# (text, channel, kind, confidence, key, last reason)
CASES = [
    # R0
    (None, "upi", "none", "high", None, "R0_no_text"),
    ("", "upi", "none", "high", None, "R0_no_text"),
    ("   \t ", "card", "none", "high", None, "R0_no_text"),
    ("...", "upi", "none", "high", None, "R0_no_text"),
    ("TEST ATM 0001", "atm", "none", "high", None, "R0_atm"),
    # R3 dictionary
    ("SWIGGY", "upi", "business", "high", "brand:swiggy", "R3_brand"),
    ("www.flipkart.com", "bank_transfer", "business", "high", "brand:flipkart", "R3_brand"),
    ("swiggy.test@okicici", "upi", "business", "high", "brand:swiggy", "R3_brand"),
    # R4 channel
    ("TEST SHOP", "card", "business", "high", "name:test shop", "R4_card"),
    ("TEST STREAMING", "autopay", "business", "high", "name:test streaming", "R4_autopay"),
    # R5 business only
    ("TEST TRADERS PVT LTD", "upi", "business", "high", "name:test traders pvt ltd", "R5_business"),
    ("M/S TEST", "upi", "business", "high", "name:m s test", "R5_business"),
    ("testshop.in", "bank_transfer", "business", "high", "name:testshop in", "R5_business"),
    ("q900000001@ybl", "upi", "business", "high", "vpa:q900000001@ybl", "R5_business"),
    ("paytmqr9000@paytm", "upi", "business", "high", "vpa:paytmqr9000@paytm", "R5_business"),
    ("TESTCO 9001", "upi", "business", "low", "name:testco 9001", "R5_business"),
    # R5 person only
    ("MR TEST PERSON", "upi", "person", "high", "name:test person", "R5_person"),
    ("Smt. Test", "bank_transfer", "person", "high", "name:test", "R5_person"),
    ("TEST PERSON 9000000001@ybl", "upi", "person", "high", "vpa:9000000001@ybl", "R5_person"),
    ("9000000001@ybl", "upi", "person", "low", "vpa:9000000001@ybl", "R5_person"),
    ("TEST PERSON", "upi", "person", "low", "name:test person", "R5_person"),
    # R5 both or neither
    ("MR TEST STORES", "upi", "unsure", "low", "name:test stores", "R5_unsure_mixed"),
    ("TEST", "upi", "unsure", "low", "name:test", "R5_unsure_none"),
    ("*test@ybl", "upi", "unsure", "low", "vpa:*test@ybl", "R5_unsure_none"),
    ("test.user@ybl", "upi", "unsure", "low", "vpa:test.user@ybl", "R5_unsure_none"),
    ("TEST PERSON ONE TWO FIVE", "upi", "unsure", "low", "name:test person one two five", None),
]


@pytest.mark.parametrize(("text", "channel", "kind", "confidence", "key", "last"), CASES)
def test_rules(text, channel, kind, confidence, key, last) -> None:
    m = normalise_merchant(text, channel)
    assert (m.kind, m.confidence, m.merchant_key) == (kind, confidence, key)
    if last:
        assert m.reasons[-1] == last
    assert m.version == MERCHANT_VERSION
    assert (m.brand_id is not None) == (last == "R3_brand")
    assert (m.display_name is None) == (kind == "none")
    if m.display_name:
        assert normalise_merchant(m.display_name, channel).merchant_key == key


@pytest.mark.parametrize("prefix", GATEWAY_PREFIXES)
def test_each_gateway_prefix_is_stripped(prefix: str) -> None:
    for text in (f"{prefix.upper()}*SWIGGY", f"{prefix} * Swiggy"):
        m = normalise_merchant(text, "card")
        assert m.merchant_key == "brand:swiggy"
        assert m.reasons == ("R2_gateway", "R3_brand")


def test_gateway_prefix_needs_a_star_and_a_rest() -> None:
    assert normalise_merchant("PAYTM*", "card").merchant_key == "brand:paytm"
    assert "R2_gateway" not in normalise_merchant("RAZORPAY TEST", "upi").reasons
    assert "R2_gateway" not in normalise_merchant("TEST*SHOP", "card").reasons


def test_whole_tokens_only() -> None:
    assert match_brand(tokens("swiggyfan test")) == (None, False)
    assert normalise_merchant("TESTOLA", "card").brand_id is None


def test_brand_is_anchored_at_the_start() -> None:
    assert normalise_merchant("UBER TEST RIDE", "card").brand_id == "uber"
    assert normalise_merchant("TEST UBER RIDE", "card").brand_id is None  # later: no match
    assert normalise_merchant("RAZ*UBER TEST", "card").brand_id == "uber"  # after a gateway
    assert normalise_merchant("www.uber.com", "other").brand_id == "uber"  # after "www"
    assert normalise_merchant("uber.test@ybl", "upi").brand_id == "uber"  # UPI local part
    assert normalise_merchant("test.uber@ybl", "upi").brand_id is None
    assert normalise_merchant("TEST uber@ybl", "upi").brand_id == "uber"  # name misses, UPI hits


def test_longest_alias_wins_and_tie_is_no_match() -> None:
    assert match_brand(tokens("reliance jio")) == ("jio", False)
    assert match_brand(tokens("google play test")) == ("google", False)
    assert match_brand(tokens("tata sky test"), tokens("jio")) == ("tata_play", False)  # longer
    assert match_brand(tokens("jio"), tokens("ola")) == (None, True)  # same length, two brands
    m = normalise_merchant("JIO ola@ybl", "upi")
    assert m.brand_id is None and "R3_tie" in m.reasons


@pytest.mark.parametrize(
    ("text", "channel", "display"),
    [
        ("SWIGGY", "upi", "Swiggy"),  # dictionary
        ("www.flipkart.com", "other", "Flipkart"),
        ("RAZ*TEST SHOP", "card", "Test Shop"),  # name, title case, gateway removed
        ("mr. test person", "upi", "Mr. Test Person"),
        ("M/S TEST TRADERS", "upi", "M/s Test Traders"),
        ("Test.User@OKAXIS", "upi", "test.user@okaxis"),  # UPI ID only, lower case
        ("TEST PERSON test.user@ybl", "upi", "test.user@ybl"),  # UPI ID is the key
        ("TEST ATM 0001", "atm", None),
        (None, "upi", None),
    ],
)
def test_display_name_forms_and_round_trip(text, channel, display) -> None:
    m = normalise_merchant(text, channel)
    assert m.display_name == display
    if display:
        assert normalise_merchant(display, channel).merchant_key == m.merchant_key


@pytest.mark.parametrize(
    ("text", "kind", "confidence", "signal"),
    [
        ("test.user@okaxis", "person", "low", "R5_consumer_vpa"),
        ("test.user@okhdfcbank", "person", "low", "R5_consumer_vpa"),
        ("test.user@okicici", "person", "low", "R5_consumer_vpa"),
        ("*test@oksbi", "person", "low", "R5_consumer_vpa"),
        ("TEST PERSON 9000000001@okaxis", "person", "high", "R5_consumer_vpa"),
        ("test.shop@okbizaxis", "business", "high", "R5_business_handle"),
        ("test.shop@okbizicici", "business", "high", "R5_business_handle"),
        ("TEST STORES test.user@okaxis", "unsure", "low", "R5_consumer_vpa"),  # both kinds
        ("test.user@okaxisbank", "unsure", "low", None),  # not on the list
    ],
)
def test_upi_handle_signals(text, kind, confidence, signal) -> None:
    m = normalise_merchant(text, "upi")
    assert (m.kind, m.confidence) == (kind, confidence)
    if signal:
        assert signal in m.reasons


@pytest.mark.parametrize(
    "name",
    [
        "TEST TIFFIN CENTRE",  # food
        "TEST MESS",
        "TEST KIRANA",  # grocery
        "TEST PROVISION",
        "TEST JUICE POINT",
        "TEST HOSTEL",  # stay
        "TEST XEROX",  # print
        "TEST TRAVELS",  # travel
        "TEST AGENCIES",  # trade
        "TEST MEDICALS",  # health
    ],
)
def test_business_keyword_groups(name: str) -> None:
    m = normalise_merchant(name, "upi")
    assert (m.kind, m.confidence) == ("business", "high")
    assert "R5_keyword" in m.reasons


def test_no_keyword_of_one_or_two_letters() -> None:
    assert not [w for w in BUSINESS_WORDS if len(w) <= 2]
    assert normalise_merchant("TEST CO", "upi").kind == "person"  # "co" is not a keyword


@pytest.mark.parametrize(
    "variant",
    [
        "Test Person",
        "TEST  PERSON",
        " test person. ",
        "Test-Person",
        "MR. TEST PERSON",
        "(test person)",
    ],
)
def test_key_stable_across_case_spacing_punctuation_honorific(variant: str) -> None:
    assert normalise_merchant(variant, "upi").merchant_key == "name:test person"


def test_vpa_key_and_malformed_vpa() -> None:
    assert normalise_merchant(" TEST.User@OKAXIS. ", "upi").merchant_key == "vpa:test.user@okaxis"
    for bad in ("@okaxis", "test@", "a@b@c", "test@x"):
        m = normalise_merchant(bad, "upi")
        assert "R1_vpa_malformed" in m.reasons and m.merchant_key.startswith("name:")


def test_non_ascii_input() -> None:
    m = normalise_merchant("टेस्ट व्यक्ति", "upi")  # two Devanagari words
    assert (m.kind, m.merchant_key) == ("person", "name:टेस्ट व्यक्ति")
    assert normalise_merchant("ＳＷＩＧＧＹ", "upi").brand_id == "swiggy"  # NFKC fullwidth
    assert normalise_merchant("Domino’s", "card").brand_id == "dominos"
    m = normalise_merchant("ＴＥＳＴ ｓｈｏｐ", "card")  # fullwidth name: display round trip
    assert normalise_merchant(m.display_name, "card").merchant_key == m.merchant_key


def test_deterministic_and_frozen() -> None:
    a, b = normalise_merchant("MR TEST PERSON", "upi"), normalise_merchant("MR TEST PERSON", "upi")
    assert a == b and isinstance(a, Merchant)
    with pytest.raises(AttributeError):
        a.kind = "business"  # type: ignore[misc]


def test_display_name_normalises_to_the_same_key() -> None:
    for brand in brands().values():
        for channel in ("upi", "card"):
            m = normalise_merchant(brand.name, channel)
            assert m.merchant_key == f"brand:{brand.id}", brand.id
            assert normalise_merchant(m.display_name, channel).merchant_key == m.merchant_key


def test_dictionary_file() -> None:
    data = json.loads(Path(merchant.__file__).with_name("brands.json").read_text("utf-8"))["brands"]
    ids = [b["id"] for b in data]
    assert len(ids) == len(set(ids)) and 60 <= len(ids) <= 100
    alias_index()  # raises when two brands share an alias (display names included)
    for b in data:
        assert len(set(b["aliases"])) == len(b["aliases"])
        assert all(tokens(a) for a in b["aliases"])


def test_channel_for_every_hdfc_template_channel() -> None:
    assert {t.channel for t in TEMPLATES} - {None} - {"fd", "emi", "cash"} <= set(PARSER_CHANNELS)
    assert channel_for("upi", ["autopay"]) == "autopay"
    assert channel_for("upi") == "upi"
    assert channel_for("debit_card") == channel_for("credit_card") == "card"
    assert channel_for("fd") == channel_for(None) == "other"


@pytest.mark.skipif(not SAMPLE.exists(), reason="redacted sample not present (CI)")
def test_engine_runs_over_the_redacted_sample() -> None:
    for msg in json.loads(SAMPLE.read_text(encoding="utf-8")):
        result = parse_message(msg["sender"], msg["body"], datetime.fromisoformat(msg["date_utc"]))
        if getattr(result, "is_money", False):
            channel = channel_for(result.channel, result.hints)
            m = normalise_merchant(result.counterparty_raw, channel)
            if m.display_name:
                assert normalise_merchant(m.display_name, channel).merchant_key == m.merchant_key
