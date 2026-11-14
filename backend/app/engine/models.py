"""Engine result types. Frozen: a parse result never changes after creation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MONEY_TYPES = frozenset({"debit", "credit", "refund"})
MESSAGE_TYPES = MONEY_TYPES | {
    "collect_request",
    "mandate",
    "upcoming_debit",
    "card_alert",
    "balance_info",
    "fraud_warning",
    "other_info",
}
UnknownReason = Literal[
    "unknown_sender",
    "no_parser_for_bank",
    "no_template",
    "foreign_currency_deferred",
    "ambiguous",
]


@dataclass(frozen=True)
class ParsedMessage:
    """What one SMS says, literally. Nothing inferred from other messages."""

    bank: str
    template_id: str
    parser_version: str
    type: str
    direction: Literal["debit", "credit"] | None
    amount_paise: int | None
    currency: str | None
    account_last4: str | None
    channel: str | None
    counterparty_raw: str | None
    reference: str | None
    balance_paise: int | None
    txn_time_utc: datetime | None
    time_inferred: bool | None
    hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.type not in MESSAGE_TYPES:
            raise ValueError(f"unknown message type: {self.type}")
        if self.is_money and None in (self.amount_paise, self.direction, self.txn_time_utc):
            raise ValueError("money messages need amount, direction and time")

    @property
    def is_money(self) -> bool:
        return self.type in MONEY_TYPES


@dataclass(frozen=True)
class Unknown:
    """The engine could not (or deliberately did not) parse the message."""

    reason: UnknownReason
    bank: str | None = None
    detail: str | None = None
