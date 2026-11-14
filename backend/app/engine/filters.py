"""Messages that are never stored: OTPs and promotional SMS.

Same OTP rule as scripts/redact_sms.py (that script stays standalone). Both
implementations must pass backend/tests/fixtures/otp_cases.json.
"""

import re

# ponytail: keyword heuristic. "Never share your OTP" warnings inside real
# transaction alerts are stripped first so those alerts survive.
OTP_WARNING_RE = re.compile(
    r"(?:never|do\s*not|don'?t|not\s+to)\s+share\s+(?:your\s+|the\s+|this\s+)?"
    r"(?:otp|one[\s-]?time[\s-]?password|pin|cvv)",
    re.IGNORECASE,
)
OTP_RE = re.compile(r"\b(?:otp|one[\s-]?time[\s-]?password|verification\s+code)\b", re.IGNORECASE)


def is_otp(body: str) -> bool:
    return bool(OTP_RE.search(OTP_WARNING_RE.sub("", body)))


def is_promotional(suffix: str) -> bool:
    """TRAI suffix P marks promotional senders (from senders.parse_sender)."""
    return suffix == "P"
