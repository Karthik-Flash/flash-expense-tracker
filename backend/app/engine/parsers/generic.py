"""Generic parser for Indian bank SMS from banks with no dedicated parser yet (D-101).

It reads a message only when every condition holds, and never invents a value:
  1. an INR amount: Rs, Rs., INR or the rupee sign, with or without commas and paise.
     Amounts right after a balance or limit word (Avl Bal, Available limit) are not it;
     two different other amounts are refused.
  2. a completed-action verb, the first of which gives the direction:
     debit: debited, spent, paid, sent, withdrawn, purchase, "txn of ... at";
     credit: credited, received, deposited (refund ... credited is a credit too).
  3. an anchor: an account or card mask (XX1234, x1234, *1234, ending 1234), a
     UPI/IMPS/NEFT/RRN/UTR reference with at least 6 digits, or a UPI ID.
Before that it rejects, by reason: OTPs and verification codes, payment requests,
promotions and loan offers, failed, declined or reversed attempts, mandate and AutoPay
notices that are not executions, card bill reminders, anything scheduled or due, and
balance-only alerts. Foreign currency stays out of totals as before.

Results: a debit or credit ParsedMessage with hint "generic" (the app asks the owner to
check it), or Unknown:
  not_a_transaction  (detail: the reject reason) the message is not a payment
  generic_unsure     (detail: what is missing) it may be one; it stays "not counted yet"
A generic credit is never type refund, so it never lowers Spent by itself (D-101).

Pure: no database, clock or network. The same text always gives the same result.
"""

import re
from datetime import UTC, datetime, timedelta

from app.engine.models import ParsedMessage, Unknown
from app.engine.money import RUPEE, AmountError, to_paise
from app.engine.parsers.base import normalise
from app.engine.timeparse import IST, MONTHS, as_utc

GENERIC_VERSION = "generic-1.0.0"
TEMPLATE_ID = "GEN"
HINT = "generic"  # on every generic result: shown as "Read automatically", needs a check
REFUND_HINT = "generic_refund"  # the text says refund; still a plain credit

# Reject reasons (not_a_transaction), then unsure reasons (generic_unsure).
REJECTS = (
    "otp",
    "request",
    "promo",
    "failed",
    "mandate_notice",
    "card_bill_due",
    "scheduled",
    "balance_only",
    "other",  # no amount and no completed action
)
# An amount with no completed action, an action with no INR amount, and so on.
UNSURE = ("no_verb", "no_amount", "amount_format", "several_amounts", "no_anchor")
# Kinds for the bank survey (keyword heuristics, any bank).
KINDS = (
    "debit", "credit", "card", "atm", "balance", "otp", "promo", "bill_due", "request", "other",
)  # fmt: skip
# A message with an event date further than this from when it arrived keeps the arrival
# time: the date was misread or is not the payment's.
DATE_BEFORE, DATE_AFTER = timedelta(days=45), timedelta(days=1)

_I = re.IGNORECASE
SAME_SENTENCE = r"(?:[^.;]|\.(?=\d))"  # a dot inside an amount does not end a sentence
FOREIGN = re.compile(r"\b(?:USD|EUR|GBP|AED|SGD|AUD|CAD|JPY|CHF) ?\d", _I)
AMOUNT = re.compile(rf"(?:\b(?:Rs|INR)\.?|{RUPEE})\s?(\d[\d,]*(?:\.\d+)?)", _I)
BALANCE_BEFORE = re.compile(
    r"(?:\bbal(?:ance)?|\bavl|\bavail(?:able)?|\blimit|\blmt|\boutstanding|\bo/s)"
    r"(?:\s+(?:bal(?:ance)?|amt|amount|lmt|limit))?\.?\s*(?:is|of|:|-|=)?\s*$",
    _I,
)
OTP_WARNING = re.compile(
    r"(?:(?:never|do\s*not|don'?t|not\s+to)\s+share|never\s+asks?\s+for)\s+"
    r"(?:your\s+|the\s+|this\s+|any\s+)?(?:otp|one[\s-]?time[\s-]?password|pin|cvv)",
    _I,
)
OTP = re.compile(r"\b(?:otp|one[\s-]?time[\s-]?password|verification\s+code)\b", _I)
REQUEST = re.compile(
    r"\b(?:has|have|is|had)\s+(?:requested|requesting)\b|\bcollect\s+request\b"
    r"|\bpayment\s+request\b|\brequested\s+(?:money|payment|rs|inr)\b",
    _I,
)
PROMO = re.compile(
    r"\bpre-?approved\b|\boffers?\b|\beligible\b|\bapply\s+now\b|\bcongrat(?:ulation)?s\b"
    r"|\bvouchers?\b|\blucky\b|\bwin\b|\bhurry\b|\blimited\s+period\b|\binstant\s+loan\b"
    r"|\bloan\s+(?:of|up\s?to|upto)\b|\bget\s+up\s?to\b|\bcashback\s+up\s?to\b",
    _I,
)
FAILED = re.compile(
    r"\b(?:failed|failure|declined|unsuccessful|not\s+successful|could\s*n[o']t\s+be"
    r"|rejected|insufficient|reversed|reversal|cancell?ed)\b",
    _I,
)
MANDATE = re.compile(r"\b(?:e-?mandate|mandate|auto-?pay|standing\s+instruction|si)\b", _I)
MANDATE_NOTICE = re.compile(
    r"\b(?:registered|created|set\s?up|activated|modified|revoked|paused|pre-?debit"
    r"|notification|will|upcoming|scheduled|due)\b",
    _I,
)
BILL = re.compile(r"\b(?:credit\s+card|card\s+bill|statement)\b", _I)
DUE = re.compile(
    r"\bis\s+due\b|\bdue\s+(?:on|date|by)\b|\b(?:payment|amount|amt|total|min(?:imum)?)\.?\s+"
    r"(?:amount\s+|amt\s+)?due\b|\bminimum\s+amount\b|\bmin\.?\s+amt\b",
    _I,
)
SCHEDULED = re.compile(
    r"\bwill\s+be\s+(?:debited|credited|deducted|charged|processed|paid)\b|\bscheduled\b"
    r"|\bupcoming\b|\bto\s+be\s+(?:debited|deducted)\b|\breminder\b|\bshall\s+be\b",
    _I,
)
VERBS = re.compile(
    r"\b(?P<debit>debited|spent|paid|sent|withdrawn|purchased?|(?:txn|transaction)\s+of\b"
    rf"(?={SAME_SENTENCE}{{0,60}}?\bat\b))|\b(?P<credit>credited|received|deposited)\b",
    _I,
)
REFUND = re.compile(r"\brefund", _I)
BALANCE_WORD = re.compile(r"\b(?:bal(?:ance)?|avl|available)\b", _I)
VPA = re.compile(r"(?<![\w.*-])([\w.*-]*\w@[a-z][a-z0-9]+)(?![\w@]|\.\w)", _I)
MASK = re.compile(r"(?<![\w*])[xX*]+[-\s]?(\d{3,4})\b(?!@)")
ENDING = re.compile(r"\bending\s+(?:in\s+|with\s+)?[xX*]*(\d{4})\b", _I)
REFERENCES = (
    re.compile(r"\b(?:upi|imps|neft|rtgs)/(?:p2[pam]/)?([a-z0-9]{6,22})(?=/)", _I),
    re.compile(
        r"\b(?:ref(?:erence)?|rrn|utr|txn|transaction)\.?(?:\s*(?:no|number|id))?\.?"
        r"\s*[:#-]?\s*([a-z0-9]{6,22})\b",
        _I,
    ),
    re.compile(r"\b(?:upi|imps|neft|rtgs)[:\s-]+(\d{9,22})\b", _I),
)
ATM = re.compile(r"\batm\b", _I)
CASH = re.compile(r"\b(?:withdrawn|withdrawal|cash)\b", _I)
CARD = re.compile(
    r"\bcard\b[^.;]{0,20}?(?:[xX*]+\d{3,4}|\bending\b|\bno\b)"
    r"|\b(?:spent|purchased?|txn|transaction)\b[^.;]{0,40}?\bcard\b",
    _I,
)
CREDIT_CARD = re.compile(r"\bcredit\s+card\b", _I)
CARD_PAYMENT = re.compile(
    rf"\b(?:payment|paid)\b{SAME_SENTENCE}{{0,60}}\b(?:received|credited)\b", _I
)
CHANNELS = (
    ("upi", re.compile(r"\bupi\b", _I)),
    ("imps", re.compile(r"\bimps\b", _I)),
    ("neft", re.compile(r"\b(?:neft|rtgs)\b", _I)),
    ("netbanking", re.compile(r"\b(?:net\s?banking|internet\s+banking)\b", _I)),
)
# Counterparty slots. Only what follows one of these words is ever a counterparty.
NAME_WORD = r"[A-Za-z][A-Za-z.&'-]*"
# A lookahead, so a name never swallows the next slot word ("by NEFT from NAME").
NAME = rf"(?=({NAME_WORD}(?:\s+{NAME_WORD}){{0,4}}))"
SLOTS = {
    "debit": re.compile(rf"\b(?:to|at|towards)\s+(?:(?:vpa|beneficiary|merchant)\s+)?{NAME}", _I),
    "credit": re.compile(rf"\b(?:from|by)\s+{NAME}", _I),
}
PATH_NAME = re.compile(rf"\b(?:upi|imps|neft)/(?:p2[pam]/)?[^/\s]+/{NAME}", _I)
# "debited ...; NAME credited": the other side of a debit
BENEFICIARY = re.compile(rf";\s*({NAME_WORD}(?:\s+{NAME_WORD}){{0,4}})\s+credited\b", _I)
# The bank's closing wording: no counterparty is read after it ("call ... to report").
TRAILER = re.compile(
    r"\bnot\s+(?:you|done|initiated|by\s+you)\b|\bif\s+not\b|\bcall\b|\bsms\b"
    r"|\bto\s+block\b|\bdispute\b|\bin\s+case\b|\bhelpline\b|\bt&c\b",
    _I,
)
# Words that end a name (message wording), and words that mean it is no counterparty.
STOP = frozenset(
    """on via ref refno rrn utr upi imps neft rtgs info avl bal balance not if call sms dt
    date at for in is was has from by to and the with txn of using thru through towards
    rs inr your a/c ac acct credited debited received sent paid spent deposited withdrawn
    autopay mandate""".split()
)
NOT_A_NAME = frozenset(
    """a/c ac acct account card bank you your atm self cash vpa upi imps neft rtgs
    linked mobile number customer wallet""".split()
)
DATES = (
    re.compile(r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})"),
    re.compile(r"(?<!\d)(?P<d>\d{1,2})[-/.](?P<m>\d{1,2})[-/.](?P<y>\d{4}|\d{2})(?!\d)"),
    re.compile(
        r"(?<!\d)(?P<d>\d{1,2})[- ]?(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
        r"[a-z]*[- ,]*(?P<y>\d{4}|\d{2})(?!\d)",
        _I,
    ),
)
TIME = re.compile(  # used with match() at the end of a date
    r"(?:\s*,?\s*(?:at\s+)?|:)(?P<h>\d{1,2}):(?P<mi>\d{2})(?::(?P<s>\d{2}))?\s*(?P<ap>am|pm)?",
    _I,
)


def _clean(text: str) -> str:
    """Normalised text without "never share your OTP" warnings."""
    return OTP_WARNING.sub(" ", normalise(text))


def _amounts(text: str) -> list[str]:
    """The amount texts that are not right after a balance or limit word."""
    return [
        m.group(1)
        for m in AMOUNT.finditer(text)
        if not BALANCE_BEFORE.search(text[max(0, m.start() - 30) : m.start()])
    ]


def _direction(text: str) -> str | None:
    m = VERBS.search(text)
    return None if m is None else ("debit" if m.group("debit") else "credit")


def _negative(text: str) -> str | None:
    """The reason a message is not a payment, before anything else is read."""
    if OTP.search(text):
        return "otp"
    if REQUEST.search(text):
        return "request"
    if PROMO.search(text):
        return "promo"
    if FAILED.search(text):
        return "failed"
    if MANDATE.search(text) and MANDATE_NOTICE.search(text):
        return "mandate_notice"
    if BILL.search(text) and DUE.search(text):
        return "card_bill_due"
    if SCHEDULED.search(text) or DUE.search(text):
        return "scheduled"
    return None


def kind_of(body: str) -> str:
    """The survey kind of any bank message (keyword heuristics; never used for totals)."""
    text = _clean(body)
    reason = _negative(text)
    if reason in ("otp", "request", "promo"):
        return {"otp": "otp", "request": "request", "promo": "promo"}[reason]
    if reason in ("card_bill_due", "scheduled", "mandate_notice"):
        return "bill_due"
    direction = _direction(text)
    if direction == "debit" and ATM.search(text) and CASH.search(text):
        return "atm"
    if direction == "debit" and CARD.search(text):
        return "card"
    if direction:
        return direction
    return "balance" if BALANCE_WORD.search(text) else "other"


def _mask(text: str) -> str | None:
    """The account or card last digits, when the message names only one."""
    found = {m.group(1) for rx in (MASK, ENDING) for m in rx.finditer(text)}
    return found.pop() if len(found) == 1 else None


def _reference(text: str) -> str | None:
    for rx in REFERENCES:
        for m in rx.finditer(text):
            value = m.group(1)
            if sum(c.isdigit() for c in value) >= 6:
                return value
    return None


def _name(raw: str) -> str | None:
    words = []
    for word in raw.split():
        if word.lower().strip(".") in STOP:
            break
        words.append(word.rstrip("."))
    if not words or any(w.lower() in NOT_A_NAME for w in words):
        return None
    name = " ".join(words)
    return name if sum(c.isalpha() for c in name) >= 2 else None


def _counterparty(text: str, direction: str, vpas: list[str]) -> str | None:
    """A UPI ID when the message has exactly one, else a name in an explicit slot before
    the bank's closing wording. Never a guess: no slot, no counterparty."""
    if len(set(vpas)) == 1:
        return vpas[0]
    if vpas:
        return None  # two UPI IDs: which one is the other side is a guess
    head = text[: m.start()] if (m := TRAILER.search(text)) else text
    slots = (PATH_NAME, BENEFICIARY) if direction == "debit" else (PATH_NAME,)
    for rx in (*slots, SLOTS[direction]):
        for m in rx.finditer(head):
            if name := _name(m.group(1)):
                return name
    return None


def _channel(text: str, direction: str, vpas: list[str]) -> str | None:
    if direction == "debit" and ATM.search(text) and CASH.search(text):
        return "atm"
    if CARD.search(text):
        # A guess never lowers Net: a card the text does not call a credit card is a
        # debit card, so no credit card bill payment is ever left out because of it.
        return "credit_card" if CREDIT_CARD.search(text) else "debit_card"
    if vpas:
        return "upi"
    return next((name for name, rx in CHANNELS if rx.search(text)), None)


def _event_time(text: str, received_at: datetime) -> tuple[datetime, bool]:
    """(UTC time, inferred). A date with a time right after it, in IST, when it is near the
    arrival time; else the arrival time."""
    received = as_utc(received_at)
    for rx in DATES:
        for m in rx.finditer(text):
            t = TIME.match(text, m.end())
            if t is None:
                continue
            try:
                found = _datetime(m, t)
            except ValueError:
                continue
            if received - DATE_BEFORE <= found <= received + DATE_AFTER:
                return found, False
    return received, True


def _datetime(d: re.Match[str], t: re.Match[str]) -> datetime:
    groups = d.groupdict()
    month = MONTHS[groups["mon"].upper()] if groups.get("mon") else int(groups["m"])
    year = int(groups["y"]) + (2000 if len(groups["y"]) == 2 else 0)
    hour = int(t["h"])
    if t["ap"]:
        if not 1 <= hour <= 12:
            raise ValueError("12-hour clock out of range")
        hour = hour % 12 + (12 if t["ap"].lower() == "pm" else 0)
    local = datetime(year, month, int(groups["d"]), hour, int(t["mi"]), int(t["s"] or 0))
    return local.replace(tzinfo=IST).astimezone(UTC)


def parse(bank: str, body: str, received_at: datetime) -> ParsedMessage | Unknown:
    """One message of a bank with no dedicated parser. received_at must be aware."""
    as_utc(received_at)  # a naive datetime is a caller bug
    text = _clean(body)
    if FOREIGN.search(text):
        return Unknown("foreign_currency_deferred", bank)
    if reason := _negative(text):
        return Unknown("not_a_transaction", bank, reason)

    direction = _direction(text)
    amounts = _amounts(text)
    if direction is None:
        if BALANCE_WORD.search(text):
            return Unknown("not_a_transaction", bank, "balance_only")
        if amounts:
            return Unknown("generic_unsure", bank, "no_verb")
        return Unknown("not_a_transaction", bank, "other")
    if not amounts:
        return Unknown("generic_unsure", bank, "no_amount")
    try:
        values = {to_paise(a) for a in amounts}
    except AmountError:
        return Unknown("generic_unsure", bank, "amount_format")
    if len(values) > 1:
        return Unknown("generic_unsure", bank, "several_amounts")

    vpas = VPA.findall(text)
    without_vpas = VPA.sub(" ", text)
    last4 = _mask(without_vpas)
    reference = _reference(without_vpas)
    if not (last4 or reference or vpas):
        return Unknown("generic_unsure", bank, "no_anchor")

    hints = [HINT]
    if direction == "credit" and REFUND.search(text):
        hints.append(REFUND_HINT)
    if direction == "credit" and CREDIT_CARD.search(text) and CARD_PAYMENT.search(text):
        hints.append("card_bill_payment")  # a payment received on a credit card: no income
    channel = _channel(without_vpas, direction, vpas)
    when, inferred = _event_time(without_vpas, received_at)
    return ParsedMessage(
        bank=bank,
        template_id=TEMPLATE_ID,
        parser_version=GENERIC_VERSION,
        type=direction,
        direction=direction,
        amount_paise=values.pop(),
        currency="INR",
        account_last4=last4,
        channel=channel,
        counterparty_raw=None if channel == "atm" else _counterparty(text, direction, vpas),
        reference=reference,
        balance_paise=None,
        txn_time_utc=when,
        time_inferred=inferred,
        hints=tuple(hints),
    )
