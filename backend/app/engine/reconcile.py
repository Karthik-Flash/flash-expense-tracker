"""Reconcile: exactly one role for every transaction, and the links between them.

Design: docs/design/phase-3-backbone.md (D-059 to D-067). derive() gives each
transaction a role, the rule code that decided it and its basis ("engine": the
transaction's own wording; "owner": the rule read owner data), plus the links:
pairs of transactions that are, or may be, one event. Pure: no database, clock,
network or randomness; the same input in any order gives the same output.

Roles from one transaction. The first match decides, every match is kept:
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

Links (kind: rule). A rule links a pair only when each side has exactly one
compatible partner for that rule; otherwise every pair is a candidate. A
candidate changes no role and no total.
  duplicate: DUP_autopay_card   AutoPay success + card spend, same bank, card and amount.
                                Unique inside 10 minutes: linked. Up to 24 hours: candidate
             DUP_same_amount    same bank, account, direction and amount inside 10 minutes,
                                not two different references: always a candidate
             DUP_legacy         a pair recorded at import that no rule found: candidate
  self_transfer: ST_pair        debit on one own account, credit on another, same amount,
                                24 hours. Unique and one leg names the other's account:
                                linked, and both legs are self_transfer. Else candidate
  refund: RF_same_amount        refund and an earlier purchase on the same card or account,
                                same amount, 30 days. Unique and same merchant: linked
          RF_partial            larger purchase, same merchant: always a candidate
  fd: FD_pair                   an unexplained credit equal to an FD closure, same bank,
                                3 days: always a candidate
  any kind: OWNER_link          the owner said "same". "different" removes a pair for good

In a linked duplicate group the earliest transaction keeps its role; the others
get role duplicate. A guess never lowers Net: an unexplained debit is spend, an
unexplained credit is uncertain. Error messages never hold a value from the data.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

from app.engine.merchant import MERCHANT_VERSION, Merchant, channel_for, normalise_merchant, parts

RECONCILE_VERSION = "reconcile-1.2.1"
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
# Rule codes that can decide a role.
RULES = (
    "OWNER_role",
    "OWNER_link",
    "DUP_autopay_card",
    "ST_pair",
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
LINK_KINDS = ("duplicate", "self_transfer", "refund", "fd")
LINK_RULES = (
    "DUP_autopay_card",
    "DUP_same_amount",
    "DUP_legacy",
    "ST_pair",
    "RF_same_amount",
    "RF_partial",
    "FD_pair",
    "OWNER_link",
)
LINK_REASONS = (
    "unique_10min",  # DUP_autopay_card, linked
    "within_24h",  # DUP_autopay_card, more than 10 minutes apart
    "same_amount",  # DUP_same_amount
    "recorded_at_import",  # DUP_legacy
    "different_references",  # DUP_legacy, the two sides carry different references
    "names_partner_account",  # ST_pair, linked
    "no_own_text",  # ST_pair, neither leg names the other's account
    "same_merchant",  # RF_same_amount, linked
    "different_merchant",  # RF_same_amount
    "partial",  # RF_partial
    "second_credit",  # FD_pair
    "several_partners",  # any rule that could link: a side has more than one partner
    "owner_same",  # an owner link decision
)
VERDICTS = ("same", "different")
ACCOUNT_KINDS = ("bank_account", "credit_card", "wallet", "fd")
PARTY_KINDS = ("person", "business")
CARD_CHANNELS = ("debit_card", "credit_card")
# Engine reason codes that are enough to call a credit a payback (D-061).
PAYBACK_SIGNALS = frozenset({"R5_honorific", "R5_mobile_vpa", "R5_consumer_vpa"})
# A card's purchases are tracked when one is in the data this long before the bill payment.
TRACKED_WINDOW = timedelta(days=60)
# Windows compare txn_time_utc; both ends count ("at most this far apart").
DUP_LINK_WINDOW = timedelta(minutes=10)
DUP_CANDIDATE_WINDOW = timedelta(hours=24)
TRANSFER_WINDOW = timedelta(hours=24)
FD_WINDOW = timedelta(days=3)
REFUND_WINDOW = timedelta(days=30)

Match = tuple[str, str, str]  # role, rule code, basis
Pair = tuple[int, int]  # two transaction ids, lower first


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
    reference: str | None = None

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
    # (kind, lower id, higher id) -> "same" or "different"
    links: Mapping[tuple[str, int, int], str] = field(default_factory=dict)


@dataclass(frozen=True)
class Derived:
    transaction_id: int
    role: str
    rule: str  # the rule code that decided the role
    basis: str  # engine or owner
    reasons: tuple[str, ...]  # every rule code that matched, deciding rule first
    duplicate_of: int | None = None  # the primary of its group, only for role duplicate
    # The owner entry whose text this transaction matches, as a position in
    # OwnerData.accounts or OwnerData.parties. Set whatever rule decided the role.
    own_account: int | None = None
    party: int | None = None


@dataclass(frozen=True)
class Link:
    """Two transactions that are (linked) or may be (candidate) one event."""

    kind: str  # duplicate, self_transfer, refund or fd
    txn_a: int  # the lower id
    txn_b: int
    status: str  # linked or candidate
    rule: str
    reason: str
    decided_by: str  # engine or owner


@dataclass(frozen=True)
class Result:
    roles: dict[int, Derived]  # one per transaction, ordered by id
    links: tuple[Link, ...]  # ordered by kind and ids
    merchants: dict[int, Merchant] = field(default_factory=dict)  # the engine's merchant


@dataclass(frozen=True)
class Totals:
    spent_paise: int = 0
    paid_back_paise: int = 0
    income_paise: int = 0

    @property
    def net_paise(self) -> int:
        return self.spent_paise - self.paid_back_paise


@dataclass
class _Run:
    """Working state of one derive() call."""

    by_id: dict[int, Txn]
    merchants: dict[int, Merchant]
    matches: dict[int, list[Match]]  # deciding match first
    same: dict[str, set[Pair]]  # owner link decisions, by kind
    different: dict[str, set[Pair]]
    fixed: frozenset[int]  # transactions whose role the owner decided
    links: dict[tuple[str, int, int], Link] = field(default_factory=dict)
    duplicate_of: dict[int, int] = field(default_factory=dict)

    def role(self, i: int) -> str:
        return self.matches[i][0][0]

    def unexplained(self, i: int) -> bool:
        """The role is the engine's default guess, so a link may still explain it."""
        _, rule, basis = self.matches[i][0]
        return rule == "ST_masked" or (basis == "engine" and rule.startswith(("CR_", "DB_")))

    def put(self, i: int, match: Match) -> None:
        """A link sets a role, unless the owner decided that transaction's role."""
        if i not in self.fixed and self.matches[i][0] != match:
            self.matches[i].insert(0, match)

    def linked(self, kind: str) -> list[Link]:
        return [x for x in self.links.values() if x.kind == kind and x.status == "linked"]


def derive(
    txns: Iterable[Txn], owner: OwnerData | None = None, legacy_pairs: Iterable[Pair] = ()
) -> Result:
    """Roles and links. `legacy_pairs`: the pairs recorded in duplicate_candidates at import."""
    owner = owner or OwnerData()
    rows = sorted(txns, key=lambda t: t.id)
    by_id = {t.id: t for t in rows}
    if len(by_id) != len(rows):
        raise ValueError("two transactions share one id")
    entries: list[OwnAccount | Party] = [*owner.accounts, *owner.parties]
    index = _text_index(entries)
    own_upi = [v for a in owner.accounts for text in a.texts if (v := _vpa(text)) and "*" not in v]
    card_spends = [t for t in rows if t.direction == "debit" and t.channel == "credit_card"]

    same, different = _link_decisions(owner, by_id)
    run = _Run(by_id, {}, {}, same, different, frozenset(i for i in owner.roles if i in by_id))
    points_at: dict[int, int] = {}  # transaction -> the own account its text names
    matched: dict[int, int] = {}  # transaction -> position in entries of its owner text
    for t in rows:
        merchant = normalise_merchant(t.counterparty_raw, channel_for(t.channel, t.hints))
        position = index.get(merchant.merchant_key or "")
        own = None if position is None else entries[position]
        if position is not None:
            matched[t.id] = position
        if isinstance(own, OwnAccount):
            points_at[t.id] = position
        run.merchants[t.id] = merchant
        run.matches[t.id] = list(_own_evidence(t, own, own_upi, card_spends)) or [
            _default(t, merchant, own)
        ]
        if t.id in run.fixed:
            _check_decision(t, owner.roles[t.id])
            run.matches[t.id].insert(0, (owner.roles[t.id], "OWNER_role", "owner"))

    _duplicates(run, rows, legacy_pairs)
    _transfers(run, rows, owner.accounts, points_at)
    _fd_pairs(run, rows)
    _refunds(run, rows)

    roles = {}
    for t in rows:
        role, rule, basis = run.matches[t.id][0]
        reasons = tuple(dict.fromkeys(code for _, code, _ in run.matches[t.id]))
        primary = run.duplicate_of.get(t.id) if role == "duplicate" else None
        entry, accounts = matched.get(t.id), len(owner.accounts)
        roles[t.id] = Derived(
            t.id,
            role,
            rule,
            basis,
            reasons,
            primary,
            own_account=entry if entry is not None and entry < accounts else None,
            party=entry - accounts if entry is not None and entry >= accounts else None,
        )
    return Result(roles, tuple(run.links[key] for key in sorted(run.links)), run.merchants)


IST = timezone(timedelta(hours=5, minutes=30))  # fixed offset, no zoneinfo (D-002)
_MONTH = re.compile(r"(\d{4})-(\d{2})")


def ist_month(month: str) -> tuple[datetime, datetime]:
    """ "YYYY-MM" -> (start, end) in UTC of that IST calendar month, for totals()."""
    m = _MONTH.fullmatch(month)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError("month must look like 2026-01")
    year, number = int(m.group(1)), int(m.group(2))
    start = datetime(year, number, 1, tzinfo=IST)
    end = datetime(year + number // 12, number % 12 + 1, 1, tzinfo=IST)
    return start.astimezone(UTC), end.astimezone(UTC)


def totals(
    txns: Iterable[Txn], roles: Mapping[int, Derived], start: datetime, end: datetime
) -> Totals:
    """Spent, Paid back, Net and Income as sums over roles, for start <= txn_time_utc < end."""
    sums = {"spent": 0, "paid_back": 0, "income": 0}
    for t in txns:
        counted = COUNTED.get(roles[t.id].role)
        if counted and start <= t.txn_time_utc < end:
            total, sign = counted
            sums[total] += sign * t.amount_paise
    return Totals(sums["spent"], sums["paid_back"], sums["income"])


# --- owner data ---------------------------------------------------------------


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


def _account_index(accounts: tuple[OwnAccount, ...]) -> dict[tuple[str | None, str], int]:
    """(bank, last 4) -> position of the own bank account or wallet it belongs to."""
    index: dict[tuple[str | None, str], int] = {}
    for position, account in enumerate(accounts):
        for last4 in account.last4 if account.kind in ("bank_account", "wallet") else ():
            if index.setdefault((account.bank, last4), position) != position:
                raise ValueError("one account number is listed under two own accounts")
    return index


def _link_decisions(
    owner: OwnerData, by_id: dict[int, Txn]
) -> tuple[dict[str, set[Pair]], dict[str, set[Pair]]]:
    """Owner link decisions by verdict and kind. One about a missing transaction is ignored."""
    same: dict[str, set[Pair]] = {kind: set() for kind in LINK_KINDS}
    different: dict[str, set[Pair]] = {kind: set() for kind in LINK_KINDS}
    for (kind, a, b), verdict in owner.links.items():
        if kind not in LINK_KINDS or verdict not in VERDICTS or not a < b:
            raise ValueError("owner link decision: unknown kind or verdict, or ids out of order")
        if a not in by_id or b not in by_id:
            continue
        if verdict == "same" and not _fits(kind, by_id[a], by_id[b]):
            raise ValueError("owner link decision: the pair does not fit the kind")
        (same if verdict == "same" else different)[kind].add((a, b))
    return same, different


def _fits(kind: str, a: Txn, b: Txn) -> bool:
    """The least a pair must satisfy before the owner can call it one event of this kind."""
    if kind == "duplicate":
        return (a.bank, a.direction, a.amount_paise) == (b.bank, b.direction, b.amount_paise)
    if kind == "fd":
        return a.amount_paise == b.amount_paise
    if a.direction == b.direction:
        return False
    debit, credit = (a, b) if a.direction == "debit" else (b, a)
    if kind == "self_transfer":
        return debit.amount_paise == credit.amount_paise
    return credit.amount_paise <= debit.amount_paise  # refund: never more than the purchase


def _check_decision(t: Txn, role: str) -> None:
    if role not in ROLES or role == "duplicate":  # a duplicate is decided as a link
        raise ValueError("owner role decision: not a role the owner can set")
    wrong_side = (role in DEBIT_ONLY and t.direction != "debit") or (
        role in CREDIT_ONLY and t.direction != "credit"
    )
    if wrong_side:
        raise ValueError("owner role decision: the role does not fit the direction")


# --- roles from one transaction -------------------------------------------------


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


# --- links ----------------------------------------------------------------------


def _pair(a: Txn, b: Txn) -> Pair:
    return (a.id, b.id) if a.id < b.id else (b.id, a.id)


def _close_pairs(
    left: list[Txn], right: list[Txn], key: Callable[[Txn], object], window: timedelta
) -> Iterator[tuple[Txn, Txn]]:
    """Every (l, r) with the same key and times at most `window` apart."""
    buckets: dict[object, list[Txn]] = defaultdict(list)
    for r in right:
        buckets[key(r)].append(r)
    # ponytail: quadratic inside one bucket; sort each bucket by time and sweep if one grows large
    for one in left:
        for r in buckets.get(key(one), ()):
            if one.id != r.id and abs(one.txn_time_utc - r.txn_time_utc) <= window:
                yield one, r


def _emit(run: _Run, kind: str, rule: str, compatible: dict[Pair, tuple[str, str]]) -> None:
    """Turn one rule's compatible pairs into links.

    `compatible` maps a pair to the (status, reason) it gets when it is unique. A pair the
    owner called different is dropped. A pair that could link, but where a side has another
    partner (for this rule, or by an owner "same"), is a candidate: nothing is greedy.
    """
    live = {p: v for p, v in compatible.items() if p not in run.different[kind]}
    partners = Counter(i for p in {*live, *run.same[kind]} for i in p)
    for (a, b), (status, reason) in live.items():
        if (a, b) in run.same[kind]:
            link = Link(kind, a, b, "linked", rule, "owner_same", "owner")
        elif status == "linked" and (partners[a] > 1 or partners[b] > 1):
            link = Link(kind, a, b, "candidate", rule, "several_partners", "engine")
        else:
            link = Link(kind, a, b, status, rule, reason, "engine")
        run.links[kind, a, b] = link


def _owner_only(run: _Run, kind: str) -> None:
    """Pairs the owner called the same that no rule proposed."""
    for a, b in run.same[kind]:
        if (kind, a, b) not in run.links:
            run.links[kind, a, b] = Link(kind, a, b, "linked", "OWNER_link", "owner_same", "owner")


def reference_kind(reference: str | None, hints: Iterable[str]) -> str | None:
    """mandate (repeats every month, D-046), payment, or None for no reference."""
    if not reference:
        return None
    return "mandate" if "mandate_reference" in hints else "payment"


def _two_payments(a: Txn, b: Txn) -> bool:
    """Two references of the same kind that differ: two payments (D-069, D-072).

    A mandate ID and a payment reference are different kinds and say nothing.
    """
    kind = reference_kind(a.reference, a.hints)
    same_kind = kind is not None and kind == reference_kind(b.reference, b.hints)
    return same_kind and a.reference != b.reference


def _duplicates(run: _Run, rows: list[Txn], legacy_pairs: Iterable[Pair]) -> None:
    """Design B1. References never make a match; two different ones rule a pair out."""
    debits = [t for t in rows if t.direction == "debit" and t.account_last4]
    autopay = [t for t in debits if t.channel == "e_mandate"]
    cards = [t for t in debits if t.channel in CARD_CHANNELS]
    d1: dict[Pair, tuple[str, str]] = {}
    for a, c in _close_pairs(
        autopay, cards, lambda t: (t.bank, t.account_last4, t.amount_paise), DUP_CANDIDATE_WINDOW
    ):
        brands = {run.merchants[a.id].brand_id, run.merchants[c.id].brand_id}
        if None in brands or len(brands) == 1:  # two different brands are two merchants
            near = abs(a.txn_time_utc - c.txn_time_utc) <= DUP_LINK_WINDOW
            d1[_pair(a, c)] = ("linked", "unique_10min") if near else ("candidate", "within_24h")
    _emit(run, "duplicate", "DUP_autopay_card", d1)

    d2: dict[Pair, tuple[str, str]] = {}
    for a, b in _close_pairs(
        rows,
        rows,
        lambda t: (t.bank, t.account_last4, t.direction, t.amount_paise),
        DUP_LINK_WINDOW,
    ):
        if _pair(a, b) not in d1 and not _two_payments(a, b):
            d2[_pair(a, b)] = ("candidate", "same_amount")
    _emit(run, "duplicate", "DUP_same_amount", d2)
    _owner_only(run, "duplicate")

    for a, b in {(min(p), max(p)) for p in legacy_pairs}:  # none may be lost (D-062)
        known = ("duplicate", a, b) in run.links or (a, b) in run.different["duplicate"]
        if a != b and a in run.by_id and b in run.by_id and not known:
            two = _two_payments(run.by_id[a], run.by_id[b])
            reason = "different_references" if two else "recorded_at_import"
            run.links["duplicate", a, b] = Link(
                "duplicate", a, b, "candidate", "DUP_legacy", reason, "engine"
            )

    # Groups. A rule links a pair only when neither side has another partner, so a group a
    # rule built has two members; a larger group is the owner's.
    group_of: dict[int, set[int]] = {}
    by_owner: set[int] = set()
    for link in run.linked("duplicate"):
        merged = group_of.get(link.txn_a, {link.txn_a}) | group_of.get(link.txn_b, {link.txn_b})
        group_of.update(dict.fromkeys(merged, merged))
        if link.decided_by == "owner":
            by_owner |= merged
    if any(b in group_of.get(a, ()) for a, b in run.different["duplicate"]):
        raise ValueError("owner link decisions contradict each other")
    for i, group in group_of.items():
        primary = min(group, key=lambda m: (run.by_id[m].txn_time_utc, m))
        if i != primary and i not in run.fixed:
            run.duplicate_of[i] = primary
            rule, basis = (
                ("OWNER_link", "owner") if i in by_owner else ("DUP_autopay_card", "engine")
            )
            run.put(i, ("duplicate", rule, basis))


def _transfers(
    run: _Run, rows: list[Txn], accounts: tuple[OwnAccount, ...], points_at: dict[int, int]
) -> None:
    """Design B2 S2: the second leg of a transfer between two own accounts."""
    account_of = _account_index(accounts)
    on: dict[int, int] = {}  # transaction -> the own account it is on
    for t in rows:
        position = account_of.get((t.bank, t.account_last4 or ""))
        open_role = run.unexplained(t.id) or run.matches[t.id][0][1] == "ST_own_text"
        if position is not None and open_role and t.id not in run.duplicate_of:
            on[t.id] = position
    legs = [t for t in rows if t.id in on]
    compatible: dict[Pair, tuple[str, str]] = {}
    for d, c in _close_pairs(
        [t for t in legs if t.direction == "debit"],
        [t for t in legs if t.direction == "credit"],
        lambda t: t.amount_paise,
        TRANSFER_WINDOW,
    ):
        if on[d.id] != on[c.id]:
            named = points_at.get(d.id) == on[c.id] or points_at.get(c.id) == on[d.id]
            compatible[_pair(d, c)] = (
                ("linked", "names_partner_account") if named else ("candidate", "no_own_text")
            )
    _emit(run, "self_transfer", "ST_pair", compatible)
    _owner_only(run, "self_transfer")
    for link in run.linked("self_transfer"):
        rule = "ST_pair" if link.decided_by == "engine" else "OWNER_link"
        for i in (link.txn_a, link.txn_b):
            if run.role(i) != "self_transfer":
                run.put(i, ("self_transfer", rule, "owner"))


def _fd_pairs(run: _Run, rows: list[Txn]) -> None:
    """Design B5: a second credit for an FD closure is only ever a candidate."""
    credits = [t for t in rows if t.direction == "credit" and t.id not in run.duplicate_of]
    compatible = {
        _pair(closure, other): ("candidate", "second_credit")
        for closure, other in _close_pairs(
            [t for t in credits if run.matches[t.id][0][1] == "FD_channel"],
            [t for t in credits if run.unexplained(t.id)],
            lambda t: (t.bank, t.amount_paise),
            FD_WINDOW,
        )
    }
    _emit(run, "fd", "FD_pair", compatible)
    _owner_only(run, "fd")
    for link in run.linked("fd"):
        for i in (link.txn_a, link.txn_b):
            if run.role(i) != "fd_move":
                run.put(i, ("fd_move", "OWNER_link", "owner"))


def _refunds(run: _Run, rows: list[Txn]) -> None:
    """Design B4. A link never changes a total: a refund is role refund, linked or not."""
    live = [t for t in rows if t.id not in run.duplicate_of and t.account_last4]
    refunds = [t for t in live if t.direction == "credit" and run.role(t.id) == "refund"]
    purchases = [t for t in live if t.direction == "debit" and run.role(t.id) in DEBIT_ONLY]
    full: dict[Pair, tuple[str, str]] = {}
    partial: dict[Pair, tuple[str, str]] = {}
    for r, p in _close_pairs(
        refunds, purchases, lambda t: (t.bank, t.account_last4), REFUND_WINDOW
    ):
        if p.txn_time_utc > r.txn_time_utc:
            continue
        key = run.merchants[r.id].merchant_key
        same_merchant = key is not None and key == run.merchants[p.id].merchant_key
        if p.amount_paise == r.amount_paise:
            full[_pair(r, p)] = (
                ("linked", "same_merchant")
                if same_merchant
                else ("candidate", "different_merchant")
            )
        elif p.amount_paise > r.amount_paise and same_merchant:
            partial[_pair(r, p)] = ("candidate", "partial")
    _emit(run, "refund", "RF_same_amount", full)
    # A partial match is proposed only for a refund with no full-amount pair and no owner link.
    placed = {i for kind, a, b in run.links if kind == "refund" for i in (a, b)}
    placed |= {i for pair in run.same["refund"] for i in pair}
    refund_ids = {t.id for t in refunds}
    _emit(
        run,
        "refund",
        "RF_partial",
        {p: v for p, v in partial.items() if not (set(p) & refund_ids & placed)},
    )
    _owner_only(run, "refund")

    # A unique full-amount link equals its purchase, so only owner links can add up to more.
    refunded: Counter[int] = Counter()
    for link in run.linked("refund"):
        a, b = run.by_id[link.txn_a], run.by_id[link.txn_b]
        purchase, refund = (a, b) if a.direction == "debit" else (b, a)
        refunded[purchase.id] += refund.amount_paise
        if refunded[purchase.id] > purchase.amount_paise:
            raise ValueError("owner link decisions: refunds add up to more than the purchase")
        if run.role(refund.id) != "refund":  # the owner linked a plain credit as a refund
            run.put(refund.id, ("refund", "OWNER_link", "owner"))
