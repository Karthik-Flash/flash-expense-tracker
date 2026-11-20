"""Synthetic SMS Backup & Restore files built from the fake parser fixtures."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import quoteattr

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "sms" / "hdfc.json").read_text(encoding="utf-8")
)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
WHEN = datetime(2026, 1, 20, 6, 30, tzinfo=UTC)

Row = tuple[str, str, datetime]


def hdfc_rows() -> list[Row]:
    return [(f["sender"], f["body"], datetime.fromisoformat(f["received_at"])) for f in FIXTURES]


# Messages that must never be stored, plus one known sender that no parser reads (an app;
# a bank with no dedicated parser has the generic one since 4F-A).
NEVER_STORED: list[Row] = [
    ("VM-HDFCBK-S", "123456 is your OTP for txn of Rs 33 at TEST STORE", WHEN),
    ("VM-HDFCBK-P", "Get 10% cashback on TEST OFFER. Apply now", WHEN),
    ("+919000000001", "Sent Rs 33 to you. Ref 000000000099", WHEN),
    ("AB-TESTCO-S", "Your TEST CO order is on the way", WHEN),
]
NO_PARSER_ROW: Row = ("VM-PHONPE-S", "Rs 33 debited from A/c XX0009 on 20-01-26", WHEN)


def epoch_ms(moment: datetime) -> int:
    return (moment - EPOCH) // timedelta(milliseconds=1)


def write_backup(path: Path, rows: list[Row], mms: int = 0) -> Path:
    with path.open("w", encoding="utf-8") as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<smses count="{len(rows)}">\n')
        for address, body, when in rows:
            f.write(
                f'<sms protocol="0" address={quoteattr(address)} date="{epoch_ms(when)}" '
                f'type="1" body={quoteattr(body)} read="1" />\n'
            )
        for _ in range(mms):
            f.write('<mms date="1762300000000"><parts><part data="QUFB" /></parts></mms>\n')
        f.write("</smses>\n")
    return path


def full_rows() -> list[Row]:
    return hdfc_rows() + NEVER_STORED + [NO_PARSER_ROW]
