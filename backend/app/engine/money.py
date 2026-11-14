"""Amount text -> integer paise. Decimal only, never float."""

import re
from decimal import Decimal

RUPEE = chr(0x20B9)

# Optional currency, then digits with Indian grouping (12,34,567) or no commas,
# then 0-2 decimals. Western grouping above 99,999 (e.g. 100,000) is rejected
# as ambiguous, as is any other comma pattern.
AMOUNT_RE = re.compile(
    rf"(?:(?:Rs|INR)\.?|{RUPEE})?\s?"
    r"(?P<int>\d+|\d{1,2}(?:,\d{2})*,\d{3})"
    r"(?:\.(?P<dec>\d{1,2}))?",
    re.I,
)


class AmountError(ValueError):
    """Amount text is missing, malformed or ambiguous."""


def to_paise(text: str) -> int:
    """'Rs.1,25,000.50' -> 12500050. Raises AmountError on anything ambiguous."""
    m = AMOUNT_RE.fullmatch(text.strip())
    if not m:
        raise AmountError(f"not a valid amount: {text!r}")
    integer = m["int"].replace(",", "")
    if len(integer) > 1 and integer.startswith("0"):
        raise AmountError(f"leading zero: {text!r}")
    value = Decimal(f"{integer}.{m['dec'] or '0'}") * 100
    return int(value)
