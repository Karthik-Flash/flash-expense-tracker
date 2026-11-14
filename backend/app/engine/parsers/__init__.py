"""Bank code -> parser. Adding a bank: one new module plus one line here."""

from app.engine.parsers.base import BankParser
from app.engine.parsers.hdfc import PARSER as HDFC

PARSERS: dict[str, BankParser] = {p.bank: p for p in (HDFC,)}
