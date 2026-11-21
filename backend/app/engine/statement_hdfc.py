"""HDFC NetBanking "Delimited" statement reader (D-114). Pure: text in, rows out.

The file is plain text, comma-separated, each field padded with spaces:

    Date, Narration, Value Dat, Debit Amount, Credit Amount, Chq/Ref Number, Closing Balance

A narration may itself hold a comma, so a row is read from the right: the last five fields
are fixed, the first is the date, and everything between is the narration. Preamble and
footer lines (the bank's address, the account summary, the legend) are not rows and are
skipped. Dates are dd/mm/yy (IST calendar days); amounts carry decimals, and an unused
amount is empty or 0.00.

Each row also gets its narration parts: the channel, and for UPI ("UPI-<NAME>-<VPA>-<IFSC>-
<REF12>-<NOTE>") the counterparty name and UPI ID; for every channel the 12-digit
reference when the narration (or else the reference field) holds exactly one.

1.1.0 (4Z): a comma inside double quotes does not split a field, so a quoted amount may
carry thousands separators
("1,23,456.00" or "123,456.00"); a blank or "-" amount is zero. A row with a negative
amount, or with both a debit and a credit (a card reversal netted on one row, seen in a
real September statement), is one movement: of the readings credit - debit, credit +
debit and the two of their sizes, the one that keeps the balance chain unbroken decides
its direction and amount (the plain credit - debit when no reading or no previous row
fits). Such a row is marked `netted`; a row that nets to zero is skipped.

check_balances() walks the closing balances: each must equal the previous one plus the
credit minus the debit. A break means a row was read wrongly (or the file was edited), so
statement-check reports the count before anything else.
"""

import re
from dataclasses import dataclass
from datetime import date

from app.engine.money import AmountError, to_paise

STATEMENT_VERSION = "stmt-hdfc-1.1.0"
HEADER = ("date", "narration", "value dat", "debit amount", "credit amount",
          "chq/ref number", "closing balance")  # fmt: skip
CHANNELS = ("upi", "neft", "imps", "rtgs", "atm", "pos", "nach", "interest", "charges",
            "netbanking", "cash", "other")  # fmt: skip

_DATE = re.compile(r"(\d{2})/(\d{2})/(\d{2})")
_REF12 = re.compile(r"(?<!\d)\d{12}(?!\d)")
# Narration prefixes, first match wins (upper case, before the first "-" or space).
_PREFIX = (
    ("upi", re.compile(r"UPI\b")),
    ("neft", re.compile(r"NEFT\b")),
    ("imps", re.compile(r"(?:MMT/)?IMPS\b")),
    ("rtgs", re.compile(r"RTGS\b")),
    ("atm", re.compile(r"(?:ATW|ATM|NWD|EAW|CWDR)\b")),
    ("pos", re.compile(r"(?:POS|ME DC|PCD)\b")),
    ("nach", re.compile(r"(?:NACH|ACH|ECS)\b")),
    ("interest", re.compile(r"(?:INT\.?|INTEREST|CREDIT INTEREST)\b")),
    ("charges", re.compile(r"(?:CHG|CHRG|CHARGES?|FEE|GST|SMS ?CHG|DC ANNUAL)\b")),
    ("netbanking", re.compile(r"(?:IB|NETBANKING|BIL|BILLPAY|ONL)\b")),
    ("cash", re.compile(r"(?:CASH|CSH|BY CASH)\b")),
)


class StatementError(ValueError):
    """The text is not an HDFC delimited statement. Never holds a value from the file."""


@dataclass(frozen=True)
class Row:
    line: int  # 1-based line number in the file
    date: date  # IST calendar day of the transaction
    narration: str
    value_date: date | None
    debit_paise: int
    credit_paise: int
    ref: str  # the Chq/Ref Number field, as written
    balance_paise: int
    channel: str
    name: str | None  # UPI: the counterparty name in the narration
    vpa: str | None  # UPI: the counterparty's UPI ID
    ref12: str | None  # the 12-digit UPI/IMPS reference, when there is exactly one
    netted: bool = False  # a negative or two-sided amount, read by the balance chain

    @property
    def direction(self) -> str:
        return "credit" if self.credit_paise else "debit"

    @property
    def amount_paise(self) -> int:
        return self.credit_paise or self.debit_paise


@dataclass(frozen=True)
class Statement:
    rows: tuple[Row, ...]
    skipped: int  # lines that are not rows (preamble, footer, blank)


def _day(text: str) -> date | None:
    m = _DATE.fullmatch(text.strip())
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    try:
        return date(2000 + year, month, day)
    except ValueError:
        return None


_NUMBER = re.compile(r"-?\d+(?:\.\d{1,2})?")


def _paise(text: str) -> int:
    """A statement amount: blank or "-" is 0; thousands separators of any grouping; may be
    negative. The column says it is an amount, so a comma is only a separator here."""
    text = text.strip().strip('"').replace(",", "").replace(" ", "")
    if text in ("", "-"):
        return 0
    if not _NUMBER.fullmatch(text):
        raise AmountError("not an amount")
    negative = text.startswith("-")
    value = to_paise(text.lstrip("-"))
    return -value if negative else value


def _balance(text: str) -> int:
    """A closing balance; an overdrawn one has a minus sign (or "Dr")."""
    text = text.strip()
    negative = text.upper().endswith("DR")
    text = text.removesuffix("Dr").removesuffix("DR").strip()
    return -_paise(text) if negative else _paise(text)


def _netted(debit: int, credit: int, before: int | None, after: int) -> int:
    """The movement of a row with a negative or two-sided amount: the reading that keeps
    the chain (before + movement == after); else the plain credit - debit."""
    readings = [credit - debit, credit + debit, abs(credit) - abs(debit), abs(debit) - abs(credit)]
    if before is not None:
        for movement in readings:
            if before + movement == after:
                return movement
    return credit - debit


def channel_of(narration: str) -> str:
    head = narration.strip().upper()
    for channel, pattern in _PREFIX:
        if pattern.match(head):
            return channel
    return "other"


def narration_parts(
    narration: str, ref_field: str = ""
) -> tuple[str, str | None, str | None, str | None]:
    """(channel, name, UPI ID, 12-digit reference) of one narration."""
    channel = channel_of(narration)
    name = vpa = None
    if channel == "upi":
        parts = [p.strip() for p in narration.split("-")]
        at = next((i for i, p in enumerate(parts) if "@" in p), None)
        if at is not None:
            vpa = parts[at] or None
            name = "-".join(parts[1:at]).strip() or None
    refs = _REF12.findall(narration)
    if len(refs) != 1:  # the reference field: 12 digits, maybe after leading zeros
        digits = ref_field.strip()
        whole = digits.isdigit() and len(digits) >= 12 and not digits[:-12].strip("0")
        refs = [digits[-12:]] if whole and digits[-12:].strip("0") else []
    return channel, name, vpa, refs[0] if len(refs) == 1 else None


def split_fields(line: str) -> list[str]:
    """Split on commas outside double quotes; the text (spaces, commas) is kept as written."""
    fields, current, quoted = [], [], False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            fields.append("".join(current))
            current = []
            continue
        current.append(ch)
    fields.append("".join(current))
    return fields


def _header(fields: list[str]) -> bool:
    return tuple(f.strip().casefold() for f in fields) == HEADER


def read(text: str) -> Statement:
    """Every row of the statement, in file order. Raises StatementError without a header."""
    rows: list[Row] = []
    skipped = 0
    seen_header = False
    before: int | None = None  # the previous row's closing balance
    for number, line in enumerate(text.splitlines(), 1):
        fields = split_fields(line)
        if not seen_header:
            seen_header = len(fields) == len(HEADER) and _header(fields)
            skipped += 1
            continue
        when = _day(fields[0]) if len(fields) >= len(HEADER) else None
        if when is None:
            skipped += 1
            continue
        value_date, debit, credit, ref, balance = (f.strip() for f in fields[-5:])
        try:
            debit_paise, credit_paise = _paise(debit), _paise(credit)
            balance_paise = _balance(balance)
        except AmountError:
            raise StatementError(f"line {number}: an amount is not a number") from None
        netted = debit_paise < 0 or credit_paise < 0 or (debit_paise and credit_paise)
        if netted:
            movement = _netted(debit_paise, credit_paise, before, balance_paise)
            debit_paise, credit_paise = max(-movement, 0), max(movement, 0)
        if not debit_paise and not credit_paise:
            if not netted:
                raise StatementError(f"line {number}: a row needs a debit or a credit")
            skipped += 1  # nets to zero: no money moved
            before = balance_paise
            continue
        narration = ",".join(fields[1:-5]).strip()
        channel, name, vpa, ref12 = narration_parts(narration, ref)
        rows.append(Row(number, when, narration, _day(value_date), debit_paise, credit_paise,
                        ref, balance_paise, channel, name, vpa, ref12, bool(netted)))  # fmt: skip
        before = balance_paise
    if not seen_header:
        raise StatementError("no header line: not an HDFC delimited statement")
    return Statement(tuple(rows), skipped)


def check_balances(rows: tuple[Row, ...] | list[Row]) -> int:
    """Rows whose closing balance is not the previous one plus credit minus debit."""
    return sum(
        1
        for before, row in zip(rows, rows[1:], strict=False)
        if before.balance_paise + row.credit_paise - row.debit_paise != row.balance_paise
    )
