"""Suggestions the engine may make, never decisions (D-117, D-118). Pure, stdlib only.

is_owner_name(): does a text look like one of the owner's own names, as banks write them?
Token-based and tolerant: any order, honorifics ignored, an initial matches a word that
starts with it ("T NAME", "NAME TEST O"). Every token of the text must be matched by a
different token of one variant (so "RAVI NAME" is not "TEST NAME"), except one extra
initial; at least one match must be a whole word of three letters or more (two with the
extra initial), and a single word never matches a longer name. Words of the text that are
not part of a name (the bank's, NEFT, TPT, a branch) are left to the caller: it passes name
segments.

is_investment(): does a text name a broker, a clearing corporation, a mutual fund or an
SIP? Words and phrases only; an amount or a time never makes an investment.
"""

import re

HONORIFICS = frozenset({"mr", "mrs", "ms", "miss", "dr", "shri", "sri", "smt", "kum", "md"})
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

INVESTMENT_WORDS = frozenset({
    "zerodha", "groww", "upstox", "angelone", "kite", "iccl", "nsccl", "mf", "sip", "amc",
    "mutual", "smallcase", "kuvera", "paytmmoney", "dhan", "fyers", "icicidirect",
    "hdfcsec", "motilal", "sharekhan", "coin", "nsdl", "cdsl", "demat", "broking",
    "securities", "stocks",
})  # fmt: skip
INVESTMENT_PHRASES = (
    "angel one", "angel broking", "indian clearing", "clearing corp", "nse clearing",
    "bse clearing", "mutual fund", "asset management", "paytm money", "icici direct",
    "hdfc securities", "motilal oswal", "systematic investment",
)  # fmt: skip


def name_tokens(text: str | None) -> list[str]:
    """Letter words, casefolded, without honorifics."""
    return [w for w in _WORD.findall((text or "").casefold()) if w not in HONORIFICS]


def _fits(token: str, word: str) -> bool:
    return (
        token == word
        or (len(token) == 1 and word.startswith(token))
        or (len(word) == 1 and token.startswith(word))
    )


def _covers(text: list[str], variant: list[str]) -> bool:
    """Every text token matched by a different variant token, one extra initial allowed
    (a father's initial); a whole-word match of three letters or more; and a lone word only
    when the variant is one word too (a surname alone is the whole family's)."""
    if len(text) == 1 and len(variant) > 1:
        return False
    free = list(variant)
    whole, spare = 0, 1
    for token in sorted(text, key=len, reverse=True):  # whole words first, then initials
        match = next((w for w in free if w == token), None) or next(
            (w for w in free if _fits(token, w)), None
        )
        if match is None:
            if len(token) == 1 and spare:
                spare -= 1
                continue
            return False
        free.remove(match)
        whole += token == match and len(token) >= 3
    return whole >= (2 if spare == 0 else 1)


def is_owner_name(text: str | None, variants: list[str] | tuple[str, ...]) -> bool:
    tokens = name_tokens(text)
    if not tokens:
        return False
    return any(_covers(tokens, name_tokens(v)) for v in variants if name_tokens(v))


def names_owner_in(text: str | None, variants: list[str] | tuple[str, ...]) -> bool:
    """A narration or counterparty text with one of the owner's names among its parts (split
    on "-", "/", ":" and ","), or as the whole text."""
    if not variants or not text:
        return False
    parts = [p for p in re.split(r"[-/:,]", text) if p.strip()]
    return is_owner_name(text, variants) or any(is_owner_name(p, variants) for p in parts)


def is_investment(text: str | None) -> bool:
    low = (text or "").casefold()
    if any(phrase in low for phrase in INVESTMENT_PHRASES):
        return True
    return bool(set(_WORD.findall(low)) & INVESTMENT_WORDS)
