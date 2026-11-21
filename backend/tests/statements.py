"""FAKE HDFC NetBanking "Delimited" statements, in the bank's shape (D-114).

A preamble, the padded header, rows padded like the bank pads them, and a footer. Every
value is made up.
"""

from decimal import Decimal

HEADER = (
    "  Date     ,Narration                                                                     "
    ",Value Dat,Debit Amount       ,Credit Amount      ,Chq/Ref Number   ,Closing Balance"
)
PREAMBLE = [
    "                                                             TEST BANK LTD (FAKE)",
    "Account Branch : TEST BRANCH                    Account No :XXXXXXXX0001",
    "Statement From : 01/01/26 To : 31/01/26",
    "",
]
FOOTER = ["", "  **Continue**", "STATEMENT SUMMARY :-", "Generated On: 01/02/26 (FAKE)."]

# (date dd/mm/yy, narration, debit, credit, ref): debit and credit as "123.45" or ""
Line = tuple[str, str, str, str, str]


def statement_text(rows: list[Line], opening: str = "50000.00") -> str:
    balance = Decimal(opening)
    out = [*PREAMBLE, HEADER]
    for day, narration, debit, credit, ref in rows:
        balance += Decimal(credit or "0") - Decimal(debit or "0")
        out.append(
            f"  {day}  ,{narration:<78},{day} ,{debit or '0.00':>18} ,{credit or '0.00':>18} "
            f",{ref:<16} ,{balance:>16.2f}"
        )
    return "\r\n".join([*out, *FOOTER]) + "\r\n"


def upi(name: str, vpa: str, ref12: str, note: str = "UPI") -> str:
    return f"UPI-{name}-{vpa}-TEST0000001-{ref12}-{note}"
