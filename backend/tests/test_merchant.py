"""Merchant normalisation engine (merchant-1.0.0). Fake values only."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.engine import merchant, parse_message
from app.engine.merchant import (
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
    ("*test@oksbi", "upi", "unsure", "low", "vpa:*test@oksbi", "R5_unsure_none"),
    ("test.user@okaxis", "upi", "unsure", "low", "vpa:test.user@okaxis", "R5_unsure_none"),
    ("TEST PERSON ONE TWO FIVE", "upi", "unsure", "low", "name:test person one two five", None),
]


@pytest.mark.parametrize(("text", "channel", "kind", "confidence", "key", "last"), CASES)
def test_rules(text, channel, kind, confidence, key, last) -> None:
    m = normalise_merchant(text, channel)
    assert (m.kind, m.confidence, m.merchant_key) == (kind, confidence, key)
    if last:
        assert m.reasons[-1] == last
    assert m.version == MERCHANT_VERSION
    branded = last == "R3_brand"
    assert (m.brand_id is not None, m.display_name is not None) == (branded, branded)


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
    assert normalise_merchant("TEST UBER RIDE", "card").brand_id == "uber"


def test_longest_alias_wins_and_tie_is_no_match() -> None:
    assert match_brand(tokens("reliance jio")) == ("jio", False)
    assert match_brand(tokens("ola google")) == ("google", False)  # longer alias
    assert match_brand(tokens("jio ola")) == (None, True)  # same length, two brands
    m = normalise_merchant("JIO OLA", "card")
    assert (m.brand_id, m.reasons) == (None, ("R3_tie", "R4_card"))


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
            assert normalise_merchant(result.counterparty_raw, channel).kind
