"""SBI parser (D-108): one template per money shape in docs/templates/sbi.md.

Shapes from the redacted sample (sender cores SBIUPI, CBSSBI, SBIBNK, SBIINB, SBIPSG,
SBYONO). SBI writes some amounts with no currency mark ("debited by 500.0"); inside a
template that is safe, the wording fixes what the number is. A message that matches no
template is never guessed at: a known notice is not_a_transaction with its reason (holds,
deposits, mandates, promotions and alerts, the same reasons as the generic parser), and
anything else with an amount stays "not counted yet" (generic_unsure, no_template).

There are no SBI card templates yet (no card message in the sample): an SBI debit or credit
card message is not counted, never read as the other card. Results carry no "generic" hint,
so the app does not ask the owner to check them.
"""

import re
from datetime import datetime

from app.engine.models import ParsedMessage, Unknown
from app.engine.money import AmountError, to_paise
from app.engine.parsers import generic
from app.engine.parsers.base import BankParser, Template, normalise
from app.engine.timeparse import as_utc

VERSION = "sbi-1.0.0"
BANK = "SBI"

AMT = r"(?:(?:Rs|INR)\.? ?|" + chr(0x20B9) + r" ?)?(?P<amount>\d[\d,]*(?:\.\d{1,2})?)"
BAL = r"(?:(?:Rs|INR)\.? ?|" + chr(0x20B9) + r" ?)?(?P<bal>\d[\d,]*(?:\.\d{1,2})?)"
MASK = r"[Xx*]*(?P<last4>\d{4})"
OTHER_ACCT = r"[Xx*]*\d{3,}"
DATE = r"\d{1,2}[-/ ]?(?:[A-Za-z]{3}|\d{1,2})[-/ ]?\d{2,4}"
REF = r"(?P<ref>[A-Za-z0-9]{6,})"
PARTY = r"(?P<party>.+?)"


def _t(id: str, pattern: str, type: str, channel: str | None) -> Template:
    return Template(id, re.compile(pattern, re.I), type, channel)


TEMPLATES = (
    _t("S01", rf"Dear UPI user A/C {MASK} debited by {AMT} on date {DATE} trf to {PARTY} "
       rf"Refno {REF}\.? If not u\? call.*", "debit", "upi"),
    _t("S02", rf"Dear SBI User, your A/c {MASK}-credited by {AMT} on {DATE} transfer from "
       rf"{PARTY} Ref No {REF} -SBI", "credit", "upi"),
    _t("S03", rf"Dear Customer, Your A/C {MASK} has a debit by transfer of {AMT} on {DATE}\. "
       rf"Avl Bal {BAL}\.?-SBI", "debit", None),
    _t("S04", rf"Dear Customer, ?Your A/C {MASK} has a credit by Transfer of {AMT} on {DATE} "
       rf"by {PARTY}\. Avl Bal {BAL}\.?(?: Download YONO)? ?-SBI", "credit", None),
    _t("S05", rf"Dear Customer, ?Your A/C {MASK} has a credit by (?!Transfer of ){PARTY} of "
       rf"{AMT} on {DATE}\. Avl Bal {BAL}\.?(?: Download YONO)? ?-SBI", "credit", None),
    _t("S06", rf"Your A/C {MASK} has credit for (?P<ref>UPI/\S+?) of {AMT} on {DATE}\. "
       rf"Avl Bal {BAL}\.?-SBI", "credit", "upi"),
    _t("S07", rf"Dear Customer, Your NEFT of {AMT} with UTR {REF} DTD {DATE} credited to "
       rf"Beneficiary AC NO\. ?{OTHER_ACCT} at .+? on {DATE} at \d{{1,2}}:\d{{2}}(?::\d{{2}})? "
       r"?(?:AM|PM)?\.?-SBI", "debit", "neft"),
    _t("S08", rf"Your A/C {MASK} Credited {AMT} on {DATE} -Deposit by transfer from {PARTY}\. "
       rf"Avl Bal {BAL}-SBI", "credit", None),
    _t("S09", rf"Your A/?C {MASK} Debited {AMT} on {DATE} -{PARTY}\.? Avl Bal {BAL}\.?-SBI",
       "debit", None),
    _t("S10", rf"Dear Customer, Your a/c no\. {MASK} is credited by {AMT} on {DATE} by a/c "
       rf"linked to mobile \S+?-{PARTY} \(IMPS Ref no {REF}\)\.? ?If not done by you, call "
       r".*-SBI", "credit", "imps"),
    _t("S11", rf"Dear Customer, {AMT} credited to your A/c No {MASK} on {DATE} through NEFT "
       rf"with UTR {REF} by {PARTY}, INFO: .*-SBI", "credit", "neft"),
    _t("S12", rf"Dear Customer, Your a/c no\. {MASK} is debited for {AMT} on {DATE} and a/c "
       rf"{OTHER_ACCT} credited \(IMPS Ref no {REF}\)\.? ?-SBI", "debit", "imps"),
    _t("S13", rf"Dear Customer, Thx for INB txn of {AMT} frm A/c {MASK} ref# {REF} on {DATE}\. "
       r"If not done, .*", "debit", "netbanking"),
    _t("S14", rf"Dear Customer, SBCollect Txn {REF} dtd \S+ {AMT} for {PARTY} is successful\.? "
       r"?-SBI", "debit", "netbanking"),
)  # fmt: skip

# Notices SBI sends that are not payments, before the generic parser's reasons.
HOLD = re.compile(r"\bhold for\b", re.I)
DEPOSIT = re.compile(r"\b(?:TDR|STDR)\b.*\bcreated\b", re.I)
CARD = re.compile(r"\b(?:debit|credit) card\b", re.I)


class SbiParser(BankParser):
    """Templates first; never a guess after them."""

    def parse(self, body: str, received_at: datetime) -> ParsedMessage | Unknown:
        as_utc(received_at)
        text = normalise(body)
        if generic.FOREIGN.search(text):
            return Unknown("foreign_currency_deferred", BANK)
        matches = self.matching(body)
        if len(matches) > 1:
            return Unknown("ambiguous", BANK, "templates " + ",".join(t.id for t, _ in matches))
        if matches:
            template, m = matches[0]
            try:
                return self._read(template, m, text, received_at)
            except (AmountError, ValueError) as e:
                return Unknown("ambiguous", BANK, f"{template.id}: {e}")
        return self._refuse(generic._clean(body))  # "never share your OTP" is no OTP

    def _read(self, t: Template, m: re.Match[str], text: str, received_at: datetime):
        g = {k: v for k, v in m.groupdict().items() if v is not None}
        when, inferred = generic._event_time(text, received_at)
        party = g.get("party", "").strip(" .,-")
        return ParsedMessage(
            bank=BANK,
            template_id=t.id,
            parser_version=self.version,
            type=t.type,
            direction=t.type,
            amount_paise=to_paise(g["amount"]),
            currency="INR",
            account_last4=g.get("last4"),
            channel=t.channel,
            counterparty_raw=party or None,
            reference=g.get("ref"),
            balance_paise=to_paise(g["bal"]) if "bal" in g else None,
            txn_time_utc=when,
            time_inferred=inferred,
        )

    def _refuse(self, text: str) -> Unknown:
        if HOLD.search(text):
            return Unknown("not_a_transaction", BANK, "hold")
        if DEPOSIT.search(text):
            return Unknown("not_a_transaction", BANK, "deposit_notice")
        if reason := generic._negative(text):
            return Unknown("not_a_transaction", BANK, reason)
        if CARD.search(text) and generic._amounts(text):
            return Unknown("generic_unsure", BANK, "card_no_template")
        if generic._amounts(text) or generic.VERBS.search(text):
            return Unknown("generic_unsure", BANK, "no_template")
        reason = "balance_only" if generic.BALANCE_WORD.search(text) else "other"
        return Unknown("not_a_transaction", BANK, reason)


PARSER = SbiParser(bank=BANK, version=VERSION, templates=TEMPLATES)
