"""Parser interface: a bank parser is a list of literal templates.

A template is a regex over the whitespace-normalised body plus fixed facts
(type, channel, hints). Named groups carry the values:

  amount, bal   money text, converted with money.to_paise
  last4, card   account or card last 4 (card2, if present, must equal card)
  party, vpa    counterparty text
  ref           reference
  dt            IST date-time (yyyy-mm-dd:HH:MM:SS)
  date          date only; validated, the time comes from received_at
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.engine.models import MONEY_TYPES, ParsedMessage, Unknown
from app.engine.money import AmountError, to_paise
from app.engine.timeparse import as_utc, parse_date, txn_time

DIRECTION = {"debit": "debit", "credit": "credit", "refund": "credit"}

# Building blocks shared by bank templates (single spaces: bodies are normalised).
AMOUNT = r"(?:(?:Rs|INR)\.?|" + chr(0x20B9) + r") ?[\d,]+(?:\.\d+)?"
MASK = r"[*Xx]*"  # bank masking before the last 4 digits


def normalise(body: str) -> str:
    """Collapse every run of whitespace (including newlines) to one space."""
    return " ".join(body.split())


@dataclass(frozen=True)
class Template:
    id: str  # e.g. "H01"; matches the shape catalogue in docs/templates/<bank>.md
    pattern: re.Pattern[str]
    type: str
    channel: str | None = None
    hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class BankParser:
    bank: str
    version: str
    templates: tuple[Template, ...]
    # Messages we recognise but deliberately do not parse yet (foreign currency).
    foreign_currency: tuple[re.Pattern[str], ...] = field(default=())

    def matching(self, body: str) -> list[tuple[Template, re.Match[str]]]:
        text = normalise(body)
        return [(t, m) for t in self.templates if (m := t.pattern.fullmatch(text))]

    def parse(self, body: str, received_at: datetime) -> ParsedMessage | Unknown:
        as_utc(received_at)  # a naive datetime is a caller bug: raise, never "ambiguous"
        text = normalise(body)
        if any(p.search(text) for p in self.foreign_currency):
            return Unknown("foreign_currency_deferred", self.bank)
        matches = self.matching(body)
        if not matches:
            return Unknown("no_template", self.bank)
        if len(matches) > 1:
            ids = ",".join(t.id for t, _ in matches)
            return Unknown("ambiguous", self.bank, f"templates {ids} all match")
        template, m = matches[0]
        try:
            return self._build(template, m, received_at)
        except (AmountError, ValueError) as e:
            return Unknown("ambiguous", self.bank, f"{template.id}: {e}")

    def _build(self, t: Template, m: re.Match[str], received_at: datetime) -> ParsedMessage:
        g = {k: v for k, v in m.groupdict().items() if v is not None}
        if "card2" in g and g["card2"] != g.get("card"):
            raise ValueError("card number differs within the message")
        if "date" in g:
            parse_date(g["date"])  # validate even when the time is inferred

        money = t.type in MONEY_TYPES
        time_utc, inferred = txn_time(g.get("dt"), received_at) if money else (None, None)
        amount = to_paise(g["amount"]) if "amount" in g else None
        party = g.get("party") or g.get("vpa")
        return ParsedMessage(
            bank=self.bank,
            template_id=t.id,
            parser_version=self.version,
            type=t.type,
            direction=DIRECTION.get(t.type),
            amount_paise=amount,
            currency="INR" if amount is not None else None,
            account_last4=g.get("last4") or g.get("card"),
            channel=t.channel,
            counterparty_raw=party.strip() if party else None,
            reference=g.get("ref"),
            balance_paise=to_paise(g["bal"]) if "bal" in g else None,
            txn_time_utc=time_utc,
            time_inferred=inferred,
            hints=t.hints,
        )
