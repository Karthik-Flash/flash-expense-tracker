"""HDFC Bank templates (senders HDFCBK, HDFCBN).

One template per shape in docs/templates/hdfc.md. H01-H15 were observed in
the redacted sample (shape id in the comment), H16-H21 only in the full-data
coverage run; N-templates are expected forms from the catalogue's "Not yet
seen" list, covered by fixtures only.

Bodies are whitespace-normalised before matching, so every pattern uses single
spaces where the SMS has spaces or line breaks.
"""

import re

from app.engine.parsers.base import AMOUNT, MASK, BankParser, Template

# Bump on every change that can alter the result for some message:
# MAJOR when result fields change meaning, MINOR when a template is added
# (more messages parse), PATCH when a template fix changes values.
PARSER_VERSION = "hdfc-1.1.1"

_PARTS = {
    "<AMT>": f"(?P<amount>{AMOUNT})",
    "<BAL>": f"(?P<bal>{AMOUNT})",
    "<L4>": MASK + r"(?P<last4>\d{4})",
    "<CARD>": MASK + r"(?P<card>\d{4})",
    "<DT>": r"(?P<dt>\d{4}-\d{2}-\d{2}:\d{2}:\d{2}:\d{2})",
    "<D_SLASH2>": r"(?P<date>\d{2}/\d{2}/\d{2})",
    "<D_SLASH4>": r"(?P<date>\d{2}/\d{2}/\d{4})",
    "<D_DASH2>": r"(?P<date>\d{2}-\d{2}-\d{2})",
    "<D_MON>": r"(?P<date>\d{2}-[A-Za-z]{3}-(?:\d{4}|\d{2}))",
    # Any catalogued date form, for shapes first seen in full data only.
    "<DATE>": (
        r"(?P<date>\d{4}-\d{2}-\d{2}|\d{2}[-/]\d{2}[-/](?:\d{4}|\d{2})"
        r"|\d{2}-[A-Za-z]{3}-(?:\d{4}|\d{2}))"
    ),
    "<NUM4>": MASK + r"\d*(?P<last4>\d{4})",  # plain account number: keep the last 4
}


def _p(pattern: str) -> re.Pattern[str]:
    for key, value in _PARTS.items():
        pattern = pattern.replace(key, value)
    return re.compile(pattern)


TEMPLATES = (
    # H01 sh_4d09f351: UPI payment sent
    Template(
        "H01",
        _p(
            r"Sent <AMT> From HDFC Bank A/C <L4> To (?P<party>.+?) On <D_SLASH2> "
            r"Ref (?P<ref>\d+) Not You\? Call \S+ BLOCK UPI to \S+"
        ),
        "debit",
        "upi",
    ),
    # H02 sh_6159ada2: UPI credit
    Template(
        "H02",
        _p(
            r"Credit Alert! <AMT> credited to HDFC Bank A/c <L4> on <D_DASH2> "
            r"from VPA (?P<vpa>\S+) \(UPI (?P<ref>\d+)\)"
        ),
        "credit",
        "upi",
    ),
    # H03 sh_5c7a7a9b: debit card spend
    Template(
        "H03",
        _p(
            r"Spent <AMT> From HDFC Bank Card <CARD> At (?P<party>.+?) On <DT> Bal <BAL> "
            r"Not You\? Call \S+ BLOCK DC (?P<card2>\d{4}) to \S+"
        ),
        "debit",
        "debit_card",
    ),
    # H04 sh_1aaf7a69: forex notice -> FOREIGN_CURRENCY below, not a template
    # H05 sh_bbcdf74e: NetBanking payment
    Template(
        "H05",
        _p(
            r"Payment Successful! <AMT> from A/c <L4> to (?P<party>.+?) "
            r"via HDFC Bank NetBanking\. Not you\?Call \S+"
        ),
        "debit",
        "netbanking",
    ),
    # H06 sh_2c4c888b: online banking money transfer
    Template(
        "H06",
        _p(
            r"Amt Deducted! <AMT> from your HDFC Bank A/c <L4> for Money Transfer "
            r"via HDFC Bank Online Banking\. Not you\?Call \S+ BLOCK OB to \S+"
        ),
        "debit",
        "netbanking",
    ),
    # H07 sh_844eba4b: UPI PIN set
    Template(
        "H07",
        _p(
            r"HDFC Bank: You have successfully set the UPI Pin for your HDFC Bank A/c No\. "
            r"<L4>\. Not You\? Call \S+ or SMS BLOCK UPI to \S+"
        ),
        "other_info",
    ),
    # H08 sh_d43a0170: card e-mandate (AutoPay) executed, SI Hub variant
    Template(
        "H08",
        _p(
            r"AutoPay \(E-mandate\) Success! For (?P<party>.+?) Txn Amt:<AMT> Dt:<D_SLASH4> "
            r"Via:HDFC Bank DC (?P<card>\d{4}) SI Hub ID: (?P<ref>\S+) TnC"
        ),
        "debit",
        "e_mandate",
        hints=("mandate_reference",),  # the ref is the mandate's, same every month
    ),
    # H09 sh_5791118d: biometric login enabled (the word slot varies)
    Template(
        "H09",
        _p(
            r"Biometric [^\s!]+! You have enabled your biometric \S+ for HDFC Bank App\. "
            r"Not you\? Call \S+"
        ),
        "other_info",
    ),
    # H10 sh_25c299ba: debit card transaction reversed ("MERCHANT* REF")
    Template(
        "H10",
        _p(
            r"Transaction Reversed!On HDFC Bank DEBIT/ATM Card <CARD> Amt: <AMT> "
            r"By (?P<party>.+?)(?:\* (?P<ref>\S+))? On <DT>"
        ),
        "refund",
        "debit_card",
    ),
    # H11 sh_edf2c444: ATM cash withdrawal
    Template(
        "H11",
        _p(
            r"Withdrawn <AMT> From HDFC Bank Card <CARD> At (?P<party>.+?) On <DT> Bal <BAL> "
            r"Not You\? Call \S+ BLOCK DC (?P<card2>\d{4}) to \S+"
        ),
        "debit",
        "atm",
    ),
    # H12 sh_9ca903ac: pre-debit notice for a card mandate
    Template(
        "H12",
        _p(
            r"Alert: <AMT> will be debited on <D_SLASH4> from HDFC Bank Card <CARD> "
            r"for (?P<party>.+?) ID:(?P<ref>\S+) Act:\S+"
        ),
        "upcoming_debit",
        "e_mandate",
    ),
    # H13 sh_6a2cfbb1: card e-mandate (AutoPay) executed, Mandate ID variant
    Template(
        "H13",
        _p(
            r"AutoPay \(E-mandate\) Success! For (?P<party>.+?) Txn Amt:<AMT> Dt:<D_SLASH4> "
            r"Via:HDFC Bank DC (?P<card>\d{4}) Mandate ID: (?P<ref>\S+) "
            r"Not You\? To Block\+Reissue Call \S+ BLOCK DC (?P<card2>\d{4}) to \S+"
        ),
        "debit",
        "e_mandate",
        hints=("mandate_reference",),
    ),
    # H14 sh_5208991c: fixed deposit closed early (own money in; Reconcile)
    Template(
        "H14",
        _p(
            r"HDFCBANK UPDATE: Your FD No <L4> has been pre maturely liquidated "
            r"for <AMT> on <D_MON>"
        ),
        "credit",
        "fd",
    ),
    # H15 sh_b34b84f1: UPI AutoPay mandate set up
    Template(
        "H15",
        _p(
            r"Mandate Set <AMT> For (?P<party>.+?) From HDFC Bank A/c <L4> "
            r"UMN: (?P<ref>\S+) Not you\? Call \S+"
        ),
        "mandate",
        "upi",
    ),
    # H16 (full data): NEFT sent via online banking
    Template(
        "H16",
        _p(
            r"Amt Deducted! <AMT> from your HDFC Bank A/c <L4> for NEFT transaction "
            r"via HDFC Bank Online Banking\.? Not you\?Call \S+ BLOCK OB to \S+"
        ),
        "debit",
        "neft",
    ),
    # H17 (full data): UPI AutoPay mandate executed
    Template(
        "H17",
        _p(
            r"UPI Mandate: Sent <AMT> from HDFC Bank A/c <NUM4> To (?P<party>.+?) <DATE> "
            r"Ref (?P<ref>\S+) Not You\? Call \S+ BLOCK UPI to \S+"
        ),
        "debit",
        "upi",
        hints=("autopay",),
    ),
    # H18 (full data): card AutoPay mandate set up
    Template(
        "H18",
        _p(
            r"AutoPay Active! For (?P<party>.+?) Starting:<DATE> Mandate ID:(?P<ref>\S+) "
            r"On HDFC Bank Card <CARD> Manage: \S+ TnC"
        ),
        "mandate",
        "e_mandate",
    ),
    # H19 (full data): UPI mandate cancelled
    Template(
        "H19",
        _p(
            r"Update: <AMT> UPI mandate to (?P<party>.+?) has been cancelled "
            r"from HDFC Bank A/c <L4>\. UMN: (?P<ref>\S+)"
        ),
        "mandate",
        "upi",
        hints=("mandate_cancelled",),
    ),
    # H20 (full data): FD closed early, funds moved (no amount; H14 has it)
    Template(
        "H20",
        _p(
            r"Alert! Your FD No\.<L4> is prematurely liquidated and funds are transferred "
            r"to your HDFC Bank A/c " + MASK + r"\d{4}\. Not you\?Call \S+"
        ),
        "other_info",
        "fd",
        hints=("fd_closure",),
    ),
    # H21 (full data): mutual fund order placed (investments are Phase 6)
    Template(
        "H21",
        _p(
            r"HDFC Bank MF a/c - <L4>\. You have placed a SUBSCRIPTION order "
            r"in (?P<party>.+?) for <AMT> on <DATE>\."
        ),
        "other_info",
        hints=("mf_order",),
    ),
    # N01 not yet seen: credit card spend
    Template(
        "N01",
        _p(
            r"Spent <AMT> On HDFC Bank Card <CARD> At (?P<party>.+?) On <DT> "
            r"Not You\? To Block\+Reissue Call \S+ BLOCK CC (?P<card2>\d{4}) to \S+"
        ),
        "debit",
        "credit_card",
    ),
    # N02 not yet seen: credit card bill payment received
    Template(
        "N02",
        _p(
            r"DEAR CARDMEMBER, PAYMENT OF <AMT> RECEIVED TOWARDS YOUR CREDIT CARD ENDING "
            r"<CARD> ON <D_MON>\. YOUR AVAILABLE LIMIT IS " + AMOUNT
        ),
        "credit",
        "credit_card",
        hints=("card_bill_payment",),
    ),
    # N03 not yet seen: NEFT credit
    Template(
        "N03",
        _p(
            r"Update! <AMT> deposited in HDFC Bank A/c <L4> on <D_MON> for NEFT "
            r"Cr-[A-Z0-9]+-(?P<party>.+?)-[*Xx\d]+-(?P<ref>[A-Z0-9]+)\. ?Avl bal <BAL>\. "
            r"Cheque deposits in A/C are subject to clearing"
        ),
        "credit",
        "neft",
    ),
    # N04 not yet seen: IMPS credit
    Template(
        "N04",
        _p(
            r"<AMT> credited to a/c <L4> on <D_DASH2> by a/c linked to mobile \S+ "
            r"\(IMPS Ref No\. (?P<ref>\d+)\)"
        ),
        "credit",
        "imps",
    ),
    # N05 not yet seen: IMPS debit
    Template(
        "N05",
        _p(
            r"IMPS of <AMT> sent from A/c <L4> to (?P<party>.+?) A/c [*Xx\d]+ on <D_DASH2>\. "
            r"Ref (?P<ref>\d+)"
        ),
        "debit",
        "imps",
    ),
    # N06 not yet seen: loan EMI debit
    Template(
        "N06",
        _p(
            r"EMI of <AMT> for Loan A/c [*Xx\d]+ has been debited from your HDFC Bank A/c <L4> "
            r"on <D_DASH2>"
        ),
        "debit",
        "emi",
    ),
    # N07 not yet seen: NACH debit
    Template(
        "N07",
        _p(
            r"<AMT> debited from A/c <L4> on <D_DASH2> towards ACH D- (?P<party>.+?)-"
            r"(?P<ref>\d+)\. Avl bal <BAL>"
        ),
        "debit",
        "nach",
    ),
    # N08 not yet seen: UPI refund
    Template(
        "N08",
        _p(
            r"<AMT> refund credited to HDFC Bank A/c <L4> from (?P<party>.+?) on <D_DASH2> "
            r"\(UPI Ref (?P<ref>\d+)\)"
        ),
        "refund",
        "upi",
    ),
    # N09 not yet seen: cash deposit
    Template(
        "N09",
        _p(r"Cash deposit of <AMT> in A/c <L4> on <D_DASH2> at (?P<party>.+?)\. Avl bal <BAL>"),
        "credit",
        "cash",
    ),
    # N10 not yet seen: UPI collect request
    Template(
        "N10",
        _p(
            r"(?P<party>.+?) has requested money from you on HDFC Bank MobileBanking\. "
            r"On approving, <AMT> will be debited from your A/c - HDFC Bank\. "
            r"Collect ID: (?P<ref>\d+)"
        ),
        "collect_request",
        "upi",
    ),
    # N11 not yet seen: balance enquiry
    Template(
        "N11",
        _p(
            r"Available Bal in HDFC Bank A/c <L4> as on <D_MON> is <BAL>\. "
            r"Cheques are subject to clearing"
        ),
        "balance_info",
    ),
    # N12 not yet seen: declined card transaction
    Template(
        "N12",
        _p(r"Transaction of <AMT> on HDFC Bank Card <CARD> at (?P<party>.+?) declined due to .+\."),
        "card_alert",
        "debit_card",
    ),
    # N13 not yet seen: fraud advisory
    Template(
        "N13",
        _p(
            r"HDFC Bank never asks for OTP, PIN or card details over a call\. "
            r"Do not share them with anyone\. Beware of fraud\."
        ),
        "fraud_warning",
    ),
)

FOREIGN_CURRENCY = (
    re.compile(r"^Notice! 1\. Forex Markup fee applies"),  # H04 sh_1aaf7a69
    re.compile(r"^Spent (?!INR\b)[A-Z]{3} ?\d"),  # N14 not yet seen: foreign card spend
)

# Amount-free HDFC notices with no template (UPI activated, card limits, KYC,
# login alerts, ...) become other_info "H_INFO". With an amount: no_template.
PARSER = BankParser("HDFC", PARSER_VERSION, TEMPLATES, FOREIGN_CURRENCY, info_fallback="H_INFO")
