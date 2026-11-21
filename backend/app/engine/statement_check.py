"""Statement against the app (D-114). Pure: statement rows and app rows in, a report out.

Matching, never one row twice:
  1. the same 12-digit reference and direction (the closest day, then the lowest id);
  2. the same amount and direction, the same IST day, then one day apart.
A pair matched by reference with different amounts is an amount mismatch.

Per IST month (the statement's days, the app's IST days) a pair whose two sides fall in
different months is "month_edge" on both sides. Every other unmatched row gets the first
likely cause that fits:
  statement only  foreign_currency    the narration names a foreign currency or markup
                  reversed_or_failed  a reversal word, or a debit and a credit of the same
                                      amount within 3 days that are both unmatched
                  sms_not_parsed      a stored HDFC message no parser read, within a day,
                                      holds the same amount: the SMS came, its template
                                      is missing (4Z)
                  fd                  FD THROUGH NET, FD interest, FD maturity or closure
                  investment_or_broking  a broker, clearing corporation, fund or SIP
                  card_bill_payment   a debit paying a credit card bill
                  own_or_internal     NEFT, IMPS, RTGS or a transfer (TPT) naming the owner
                                      (name variants) or one of the owner's accounts
                  verification_or_tiny  a credit of Rs 2 or less, an account verification,
                                      an ACH dividend
                  no_sms              NACH, interest, charges, netbanking or IMPS: HDFC sends
                                      no alert for these, or not always
                  likely_spend        a UPI or card (POS) debit to someone else
                  likely_income       any other credit
                  unknown             nothing fits (a debit on another channel)
  app only        duplicate_alert     same amount and direction within a day of an app row
                                      that is matched: a second alert for one statement row
                  card_or_other_account  a credit card, or another account's last 4
                  reversed_or_failed  a debit and a credit of the same amount within 3 days,
                                      both unmatched
                  unknown
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.engine.statement_hdfc import Row
from app.engine.suggest import is_investment, names_owner_in

CAUSES = ("sms_not_parsed", "likely_spend", "likely_income", "no_sms", "month_edge",
          "foreign_currency", "reversed_or_failed", "fd", "investment_or_broking",
          "card_bill_payment", "own_or_internal", "verification_or_tiny", "duplicate_alert",
          "card_or_other_account", "unknown")  # fmt: skip
# Statement-only debits of these causes are not spending: left out when the check counts
# the statement-only debits as spend.
NOT_SPEND_CAUSES = frozenset({
    "reversed_or_failed", "fd", "investment_or_broking", "card_bill_payment",
    "own_or_internal", "verification_or_tiny",
})  # fmt: skip
TINY_PAISE = 200
_FD = re.compile(r"\bFD\b|FIXED DEPOSIT|\bTD\b.*\b(?:INT|MAT)|PREMAT")
_CARD_BILL = re.compile(r"CREDIT CARD|\bCC\b.*(?:PAY|BILL)|CARD ?BILL|\bCCPAY|AUTOPAY.*\bCC\b")
_VERIFY = re.compile(r"^ACH C|VERIF|PENNY|DIVIDEND|\bDIV\b|ACCOUNT VALIDATION")
_TRANSFER = frozenset({"neft", "imps", "rtgs", "other", "netbanking"})
NO_SMS_CHANNELS = frozenset({"nach", "interest", "charges", "netbanking", "imps"})
FOREIGN = ("USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD", "JPY", "CHF", "INTL", "FOREIGN",
           "MARKUP", "CROSS CURR", "DCC", "FX ")  # fmt: skip
REVERSAL = ("REV", "REVERSAL", "REVERSED", "RETURN", "FAILED", "RFND")
REVERSAL_WINDOW = timedelta(days=3)


@dataclass(frozen=True)
class AppRow:
    """One active HDFC transaction of the app, any role but duplicate."""

    id: int
    day: date  # IST calendar day
    direction: str
    amount_paise: int
    ref12: str | None
    account_last4: str | None
    channel: str | None


@dataclass(frozen=True)
class Match:
    stmt: Row
    app: AppRow
    by: str  # reference or amount_day


@dataclass
class Side:
    count: int = 0
    paise: int = 0

    def add(self, paise: int) -> None:
        self.count += 1
        self.paise += paise


@dataclass
class Month:
    month: str
    stmt_debits: Side = field(default_factory=Side)
    stmt_credits: Side = field(default_factory=Side)
    app_debits: Side = field(default_factory=Side)
    app_credits: Side = field(default_factory=Side)
    matched: Counter = field(default_factory=Counter)  # by reference / amount_day
    stmt_only: Side = field(default_factory=Side)
    stmt_only_debits: Side = field(default_factory=Side)  # causes that are spending
    app_only: Side = field(default_factory=Side)
    mismatches: Side = field(default_factory=Side)  # paise: the sum of the differences
    causes: dict[str, Side] = field(default_factory=lambda: {c: Side() for c in CAUSES})
    # (side, cause, row): the unmatched rows, for --details only (PRIVATE)
    unmatched: list[tuple[str, str, object]] = field(default_factory=list)


def _month(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def match(rows: list[Row] | tuple[Row, ...], app: list[AppRow]) -> list[Match]:
    """Pairs of a statement row and an app row; each row is in at most one pair."""
    used: set[int] = set()
    pairs: list[Match] = []
    by_ref: dict[tuple[str, str], list[AppRow]] = defaultdict(list)
    for a in app:
        if a.ref12:
            by_ref[a.ref12, a.direction].append(a)
    open_rows = []
    for row in rows:
        found = [a for a in by_ref.get((row.ref12, row.direction), []) if a.id not in used]
        if row.ref12 and found:
            best = min(found, key=lambda a: (abs((a.day - row.date).days), a.id))
            used.add(best.id)
            pairs.append(Match(row, best, "reference"))
        else:
            open_rows.append(row)
    for gap in (0, 1):  # the same day first, so a near row never takes a better one's partner
        left = []
        for row in open_rows:
            found = [
                a
                for a in app
                if a.id not in used
                and a.direction == row.direction
                and a.amount_paise == row.amount_paise
                and abs((a.day - row.date).days) == gap
            ]
            if found:
                best = min(found, key=lambda a: a.id)
                used.add(best.id)
                pairs.append(Match(row, best, "amount_day"))
            else:
                left.append(row)
        open_rows = left
    return pairs


def _reversal_pairs(items: list[tuple[date, str, int, object]]) -> set[int]:
    """Positions of unmatched debit/credit pairs of the same amount within 3 days."""
    hit: set[int] = set()
    for i, (day_i, dir_i, amt_i, _) in enumerate(items):
        for j, (day_j, dir_j, amt_j, _) in enumerate(items):
            if (
                i < j
                and dir_i != dir_j
                and amt_i == amt_j
                and abs(day_i - day_j) <= REVERSAL_WINDOW
                and i not in hit
                and j not in hit
            ):
                hit |= {i, j}
                break
    return hit


@dataclass(frozen=True)
class Context:
    """What the check knows besides the two sides: the owner's name variants, the last 4 of
    the owner's own accounts, and the stored HDFC messages no parser read: (IST day, the
    amounts in paise their text holds)."""

    owner_names: tuple[str, ...] = ()
    own_last4: frozenset[str] = frozenset()
    unparsed: tuple[tuple[date, frozenset[int]], ...] = ()


def _names_own_account(text: str, own_last4: frozenset[str]) -> bool:
    """A masked account number ending in an own last 4: "XXXXXX0001", "**0001". A masked
    card number ("512345XXXXXX0001": digits before the mask) is not an account."""
    return any(re.search(rf"(?<!\d)[X*]{{2,}}\d{{0,8}}{last4}\b", text) for last4 in own_last4)


NO_CONTEXT = Context()


def stmt_cause(row: Row, reversed_: bool = False, context: Context = NO_CONTEXT) -> str:
    """The likely cause of a statement row the app does not have (order as in the docstring)."""
    text = row.narration.upper()
    if any(word in text for word in FOREIGN):
        return "foreign_currency"
    words = text.replace("-", " ").split()
    if reversed_ or any(word in words for word in REVERSAL):
        return "reversed_or_failed"
    if any(
        abs((day - row.date).days) <= 1 and row.amount_paise in amounts
        for day, amounts in context.unparsed
    ):
        return "sms_not_parsed"
    if _FD.search(text):
        return "fd"
    if is_investment(row.narration):
        return "investment_or_broking"
    if row.direction == "debit" and _CARD_BILL.search(text):
        return "card_bill_payment"
    internal = row.channel in _TRANSFER or "TPT" in words
    if internal and (
        names_owner_in(row.narration, context.owner_names)
        or _names_own_account(text, context.own_last4)
    ):
        return "own_or_internal"
    if row.direction == "credit" and (row.amount_paise <= TINY_PAISE or _VERIFY.search(text)):
        return "verification_or_tiny"
    if row.channel in NO_SMS_CHANNELS:
        return "no_sms"
    if row.direction == "debit" and row.channel in ("upi", "pos"):
        return "likely_spend"
    if row.direction == "credit":
        return "likely_income"
    return "unknown"


def check(
    rows: list[Row] | tuple[Row, ...], app: list[AppRow], context: Context = NO_CONTEXT
) -> dict[str, Month]:
    """Per IST month of the statement: totals, matches, unmatched rows and their causes.

    `app` should hold the app's HDFC rows of the statement's days (the caller selects them).
    """
    pairs = match(rows, app)
    months: dict[str, Month] = {}

    def month(day: date) -> Month:
        key = _month(day)
        return months.setdefault(key, Month(key))

    for row in rows:
        m = month(row.date)
        (m.stmt_credits if row.direction == "credit" else m.stmt_debits).add(row.amount_paise)
    for a in app:
        m = month(a.day)
        (m.app_credits if a.direction == "credit" else m.app_debits).add(a.amount_paise)

    # The statement account: the last 4 most app rows matched by reference are on.
    on = Counter(p.app.account_last4 for p in pairs if p.by == "reference" and p.app.account_last4)
    account = on.most_common(1)[0][0] if on else None

    paired_stmt = {id(p.stmt) for p in pairs}
    paired_app = {p.app.id for p in pairs}
    for p in pairs:
        if _month(p.stmt.date) == _month(p.app.day):
            m = month(p.stmt.date)
            m.matched[p.by] += 1
            if p.stmt.amount_paise != p.app.amount_paise:
                m.mismatches.add(abs(p.stmt.amount_paise - p.app.amount_paise))
        else:
            sides = (
                ("statement", p.stmt.date, p.stmt.amount_paise, p.stmt),
                ("app", p.app.day, p.app.amount_paise, p.app),
            )
            for side, day, paise, item in sides:
                m = month(day)
                (m.stmt_only if side == "statement" else m.app_only).add(paise)
                m.causes["month_edge"].add(paise)
                m.unmatched.append((side, "month_edge", item))

    lone_rows = [r for r in rows if id(r) not in paired_stmt]
    reversed_rows = _reversal_pairs([(r.date, r.direction, r.amount_paise, r) for r in lone_rows])
    for i, row in enumerate(lone_rows):
        cause = stmt_cause(row, i in reversed_rows, context)
        m = month(row.date)
        m.stmt_only.add(row.amount_paise)
        m.causes[cause].add(row.amount_paise)
        m.unmatched.append(("statement", cause, row))
        if row.direction == "debit" and cause not in NOT_SPEND_CAUSES:
            m.stmt_only_debits.add(row.amount_paise)

    matched_app = [a for a in app if a.id in paired_app]
    lone_app = [a for a in app if a.id not in paired_app]
    reversed_app = _reversal_pairs([(a.day, a.direction, a.amount_paise, a) for a in lone_app])
    for i, a in enumerate(lone_app):
        if any(
            b.direction == a.direction
            and b.amount_paise == a.amount_paise
            and abs((b.day - a.day).days) <= 1
            for b in matched_app
        ):
            cause = "duplicate_alert"
        elif a.channel == "credit_card" or (
            account and a.account_last4 and a.account_last4 != account
        ):
            cause = "card_or_other_account"
        elif i in reversed_app:
            cause = "reversed_or_failed"
        else:
            cause = "unknown"
        m = month(a.day)
        m.app_only.add(a.amount_paise)
        m.causes[cause].add(a.amount_paise)
        m.unmatched.append(("app", cause, a))
    return dict(sorted(months.items()))
