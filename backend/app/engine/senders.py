"""Sender ID normalisation and the sender -> bank registry.

Same rules as scripts/redact_sms.py (that script stays standalone). Both
implementations must pass backend/tests/fixtures/sender_ids.json.
"""

TRAI_SUFFIXES = frozenset("STPG")  # service, transactional, promotional, government

# Normalised sender core -> bank code. A bank is parsed only if it also has an
# entry in app.engine.parsers.PARSERS.
SENDER_BANKS: dict[str, str] = {
    "HDFCBK": "HDFC",
    "HDFCBN": "HDFC",
    "SBIBNK": "SBI",
    "CBSSBI": "SBI",
    "SBIUPI": "SBI",
    "SBIINB": "SBI",
    "SBYONO": "SBI",
    "SBIPSG": "SBI",
    "ICICIT": "ICICI",
    "AXISBK": "AXIS",
    "KOTAKM": "KOTAK",
    "YESBNK": "YES",
    "DOPBNK": "INDIA_POST",
    "PHONPE": "PHONEPE",
}


def parse_sender(address: str) -> tuple[str, str]:
    """Normalise a sender ID to (core, TRAI suffix).

    With hyphens: optional 2-letter prefix, core, optional S/T/P/G suffix.
    Without hyphens, by length: 9 chars ending S/T/P/G drop prefix and suffix;
    8 chars drop the prefix; 7 chars ending S/T/P/G drop the suffix; digits
    with a 2-letter prefix drop the prefix. Anything else is unchanged.
    """
    sid = address.upper().replace(" ", "")
    if "-" in sid and sid.replace("-", "").isalnum():
        parts = [p for p in sid.split("-") if p]
        suffix = parts.pop() if len(parts) > 1 and parts[-1] in TRAI_SUFFIXES else ""
        if len(parts) > 1 and len(parts[0]) == 2 and parts[0].isalpha():
            parts = parts[1:]
        return "".join(parts), suffix
    if sid[2:].isdigit() and (sid[:2].isalpha() or sid[:2].isdigit()):
        return (sid[2:] if sid[:2].isalpha() else sid), ""
    if not sid.isalnum():
        return sid, ""
    if len(sid) == 9 and sid[:2].isalpha() and sid[-1] in TRAI_SUFFIXES:
        return sid[2:-1], sid[-1]
    if len(sid) == 8 and sid[:2].isalpha():
        return sid[2:], ""
    if len(sid) == 7 and sid[-1] in TRAI_SUFFIXES:
        return sid[:-1], sid[-1]
    return sid, ""


def bank_for(core: str) -> str | None:
    """Bank code for a normalised core, or None if the sender is not a known bank."""
    return SENDER_BANKS.get(core) if core.isalnum() else None
