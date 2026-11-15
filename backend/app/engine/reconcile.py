"""Reconcile: exactly one role for every transaction.

Design: docs/design/phase-3-backbone.md (D-059 to D-067). derive() gives each
transaction a role, the rule code that decided it and its basis: "engine" when
the transaction's own wording decided, "owner" when the rule read owner data.
Pure: no database, clock, network or randomness; the same input in any order
gives the same output.

Step 3C-2 holds every rule that reads one transaction only. Duplicates (3C-3)
and pair links (3C-5) are not here yet, so no rule gives the role "duplicate".

Rules in order; the first match decides, every match is kept in `reasons`:
  OWNER_role          an owner role decision
  FD_channel          channel fd                                  fd_move
  FD_own_text         text of an own FD                           fd_move
  CB_hint             credit with hint card_bill_payment          card_bill_excluded
  CB_own_text         debit to an own credit card                 card_bill_excluded when that
                      card's purchases are tracked, else card_bill_counted
  ST_own_text         text of an own bank account or wallet       self_transfer
  RF_type             type refund                                 refund
  ST_masked           credit from a masked UPI ID that fits an own UPI ID    uncertain
Only when none of these matched:
  CR_income_party     credit from an owner party marked as income           income
  CR_person_party     credit from an owner party of kind person             payback
  CR_person_signal    credit, engine says person on a strong signal         payback
  CR_name_only, CR_business, CR_unsure, CR_no_text, CR_own_account          uncertain
  DB_no_counterparty  debit with no payee text (not an ATM)                 spend
  DB_spend            any other debit                                       spend

A guess never lowers Net: an unexplained debit is spend, an unexplained credit
is uncertain. Error messages never hold a value from the data.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.engine.merchant import MERCHANT_VERSION, Merchant, channel_for, normalise_merchant, parts

RECONCILE_VERSION = "reconcile-1.0.0"
VERSIONS = {"merchant": MERCHANT_VERSION, "reconcile": RECONCILE_VERSION}

ROLES = (
    "spend",
    "card_bill_counted",
    "refund",
    "payback",
    "income",
    "self_transfer",
    "card_bill_excluded",
    "fd_move",
    "duplicate",
    "ignored",
    "uncertain",
)
DEBIT_ONLY = frozenset({"spend", "card_bill_counted"})
CREDIT_ONLY = frozenset({"refund", "payback", "income", "uncertain"})
# role -> (total, sign). Every other role is in no total.
COUNTED = {
    "spend": ("spent", 1),
    "card_bill_counted": ("spent", 1),
    "refund": ("spent", -1),
    "payback": ("paid_back", 1),
    "income": ("income", 1),
}
RULES = (
    "OWNER_role",
    "FD_channel",
    "FD_own_text",
    "CB_hint",
    "CB_own_text",
    "ST_own_text",
    "RF_type",
    "ST_masked",
    "CR_income_party",
    "CR_person_party",
    "CR_person_signal",
    "CR_name_only",
    "CR_business",
    "CR_unsure",
    "CR_no_text",
    "CR_own_account",
    "DB_no_counterparty",
    "DB_spend",
)
ACCOUNT_KINDS = ("bank_account", "credit_card", "wallet", "fd")
PARTY_KINDS = ("person", "business")
# Engine reason codes that are enough to call a credit a payback (D-061).
PAYBACK_SIGNALS = frozenset({"R5_honorific", "R5_mobile_vpa", "R5_consumer_vpa"})
# A card's purchases are tracked when one is in the data this long before the bill payment.
TRACKED_WINDOW = timedelta(days=60)

Match = tuple[str, str, str]  # role, rule code, basis


@dataclass(frozen=True)
class Txn:
    """The fields of one active transaction that Reconcile reads."""

    id: int
    bank: str
    type: str  # debit, credit or refund
    direction: str  # debit or credit
    amount_paise: int
    account_last4: str | None
    channel: str | None
    counterparty_raw: str | None
    txn_time_utc: datetime
    hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.amount_paise) is not int:
            raise ValueError("amount must be an integer number of paise")
        if self.direction not in ("debit", "credit"):
            raise ValueError("direction must be debit or credit")
        if self.txn_time_utc.tzinfo is None:
            raise ValueError("transaction time must carry a time zone")


@dataclass(frozen=True)
class OwnAccount:
    """One of the owner's accounts: its last 4 digits and the texts it shows up as."""

    kind: str  # bank_account, credit_card, wallet or fd
    bank: str | None = None
    last4: tuple[str, ...] = ()
    texts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in ACCOUNT_KINDS:
            raise ValueError("own account: kind is not one of " + ", ".join(ACCOUNT_KINDS))


@dataclass(frozen=True)
class Party:
    """A person or business the owner named, by the texts it shows up as."""

    kind: str  # person or business
    income: bool = False  # an income source: pocket money, stipend, salary
    texts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in PARTY_KINDS:
            raise ValueError("party: kind is not one of " + ", ".join(PARTY_KINDS))


@dataclass(frozen=True)
class OwnerData:
    """What the owner told the app. Empty is valid. Never written by the engine."""

    accounts: tuple[OwnAccount, ...] = ()
    parties: tuple[Party, ...] = ()
    roles: Mapping[int, str] = field(default_factory=dict)  # transaction id -> role decision


@dataclass(frozen=True)
class Derived:
    transaction_id: int
    role: str
    rule: str  # the rule code that decided the role
    basis: str  # engine or owner
    reasons: tuple[str, ...]  # every rule code that matched, deciding rule first


@dataclass(frozen=True)
class Totals:
    spent_paise: int = 0
    paid_back_paise: int = 0
    income_paise: int = 0

    @property
    def net_paise(self) -> int:
        return self.spent_paise - self.paid_back_paise


def derive(txns: Iterable[Txn], owner: OwnerData | None = None) -> dict[int, Derived]:
    """One Derived per transaction, keyed and ordered by transaction id."""
    owner = owner or OwnerData()
    rows = sorted(txns, key=lambda t: t.id)
    if len({t.id for t in rows}) != len(rows):
        raise ValueError("two transactions share one id")
    entries: list[OwnAccount | Party] = [*owner.accounts, *owner.parties]
    index = _text_index(entries)
    own_upi = [v for a in owner.accounts for text in a.texts if (v := _vpa(text)) and "*" not in v]
    card_spends = [t for t in rows if t.direction == "debit" and t.channel == "credit_card"]

    out = {}
    for t in rows:
        merchant = normalise_merchant(t.counterparty_raw, channel_for(t.channel, t.hints))
        position = index.get(merchant.merchant_key or "")
        own = None if position is None else entries[position]
        matches = list(_own_evidence(t, own, own_upi, card_spends)) or [_default(t, merchant, own)]
        if (decided := owner.roles.get(t.id)) is not None:
            _check_decision(t, decided)
            matches.insert(0, (decided, "OWNER_role", "owner"))
        role, rule, basis = matches[0]
        out[t.id] = Derived(t.id, role, rule, basis, tuple(code for _, code, _ in matches))
    return out


def totals(
    txns: Iterable[Txn], derived: Mapping[int, Derived], start: datetime, end: datetime
) -> Totals:
    """Spent, Paid back, Net and Income as sums over roles, for start <= txn_time_utc < end."""
    sums = {"spent": 0, "paid_back": 0, "income": 0}
    for t in txns:
        counted = COUNTED.get(derived[t.id].role)
        if counted and start <= t.txn_time_utc < end:
            total, sign = counted
            sums[total] += sign * t.amount_paise
    return Totals(sums["spent"], sums["paid_back"], sums["income"])


def _text_index(entries: list[OwnAccount | Party]) -> dict[str, int]:
    """Merchant key of every owner text -> position of the account or party it belongs to."""
    index: dict[str, int] = {}
    for position, entry in enumerate(entries):
        for text in entry.texts:
            key = normalise_merchant(text, "other").merchant_key
            if key is None:
                raise ValueError("an owner text has no letters or digits")
            if index.setdefault(key, position) != position:
                raise ValueError("one owner text is listed in two places")
    return index


def _vpa(text: str | None) -> str | None:
    p = parts(text)
    return p.vpa if p else None


def _fits_own_upi(counterparty: str | None, own_upi: list[str]) -> bool:
    """A masked UPI ID whose handle and visible end match one of the owner's UPI IDs.

    A mask with nothing visible fits every ID on that handle.
    """
    vpa = _vpa(counterparty)
    if not vpa or "*" not in vpa:
        return False
    local, _, handle = vpa.partition("@")
    visible = local.rpartition("*")[2]
    return any(
        own.partition("@")[2] == handle and own.partition("@")[0].endswith(visible)
        for own in own_upi
    )


def _tracked(card: OwnAccount, payment: Txn, card_spends: list[Txn]) -> bool:
    """D-059: a credit card purchase on this card in the 60 days up to the payment."""
    return any(
        s.bank == card.bank
        and s.account_last4 in card.last4
        and payment.txn_time_utc - TRACKED_WINDOW <= s.txn_time_utc <= payment.txn_time_utc
        for s in card_spends
    )


def _own_evidence(
    t: Txn, own: OwnAccount | Party | None, own_upi: list[str], card_spends: list[Txn]
) -> Iterator[Match]:
    """Design B7 step 3, rows 1 to 5: evidence the transaction carries itself."""
    account = own if isinstance(own, OwnAccount) else None
    if t.channel == "fd":
        yield "fd_move", "FD_channel", "engine"
    if account and account.kind == "fd":
        yield "fd_move", "FD_own_text", "owner"
    if t.direction == "credit" and "card_bill_payment" in t.hints:
        yield "card_bill_excluded", "CB_hint", "engine"
    if t.direction == "debit" and account and account.kind == "credit_card":
        tracked = _tracked(account, t, card_spends)
        yield "card_bill_excluded" if tracked else "card_bill_counted", "CB_own_text", "owner"
    if account and account.kind in ("bank_account", "wallet"):
        yield "self_transfer", "ST_own_text", "owner"
    if t.type == "refund" and t.direction == "credit":
        yield "refund", "RF_type", "engine"
    if t.direction == "credit" and _fits_own_upi(t.counterparty_raw, own_upi):
        yield "uncertain", "ST_masked", "owner"


def _default(t: Txn, merchant: Merchant, own: OwnAccount | Party | None) -> Match:
    """Design B7 step 3, rows 6 and 7: the credit rules (B6), else spend."""
    if t.direction == "debit":
        no_payee = "R0_no_text" in merchant.reasons  # an ATM withdrawal is R0_atm
        return "spend", "DB_no_counterparty" if no_payee else "DB_spend", "engine"
    if isinstance(own, Party):
        if own.income:
            return "income", "CR_income_party", "owner"
        if own.kind == "person":
            return "payback", "CR_person_party", "owner"
        return "uncertain", "CR_business", "owner"
    if own is not None:  # a credit from an own credit card or FD text that no rule explains
        return "uncertain", "CR_own_account", "owner"
    if merchant.kind == "person":
        if PAYBACK_SIGNALS & set(merchant.reasons):
            return "payback", "CR_person_signal", "engine"
        return "uncertain", "CR_name_only", "engine"
    rule = {"business": "CR_business", "unsure": "CR_unsure"}.get(merchant.kind, "CR_no_text")
    return "uncertain", rule, "engine"


def _check_decision(t: Txn, role: str) -> None:
    if role not in ROLES or role == "duplicate":  # a duplicate is decided as a link (3C-3)
        raise ValueError("owner role decision: not a role the owner can set")
    wrong_side = (role in DEBIT_ONLY and t.direction != "debit") or (
        role in CREDIT_ONLY and t.direction != "credit"
    )
    if wrong_side:
        raise ValueError("owner role decision: the role does not fit the direction")
