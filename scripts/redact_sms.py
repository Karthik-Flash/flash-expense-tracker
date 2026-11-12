"""Redact an SMS Backup & Restore XML export into a small, shareable JSON sample.

Keeps only messages from bank / card / UPI / wallet sender IDs, drops OTPs, and
masks account/card numbers, UPI IDs and phone numbers. Amounts, dates and
merchant text are kept so parsers can be developed against realistic shapes.

Standard library only. Run it yourself; tools/agents must never read data/raw/.

    python scripts/redact_sms.py                         # all data/raw/*.xml
    python scripts/redact_sms.py data/raw/sms-2026.xml --limit 50
    python scripts/redact_sms.py --senders HDFCBK,ICICIT,MYBANK

Note: P2P payee names (e.g. "UPI/P2P/.../RAHUL K") are NOT masked. Review the
output before sharing it.
"""

import argparse
import json
import random
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = ROOT / "data" / "raw"
DEFAULT_OUTPUT = ROOT / "data" / "sample" / "redacted_sample.json"

# 6-char DLT headers. Matched against each dash-separated part of the address,
# so "VM-HDFCBK", "AD-HDFCBK-S" and "HDFCBK" all match HDFCBK.
DEFAULT_SENDERS = (
    "HDFCBK,ICICIT,ICICIB,SBIUPI,SBIINB,SBIPSG,CBSSBI,AXISBK,KOTAKB,"
    "PAYTMB,IPAYTM,PAYTM,YESBNK,INDUSB,IDFCFB,PNBSMS,BOBTXN,CANBNK,UNIONB,"
    "AMEXIN,SCBANK,CITIBK,PHONPE,GPAY,AMZPAY,MOBIKW,FREECH,ONECRD,SLICE"
)

# ponytail: keyword heuristic. "Never share your OTP" warnings inside real
# transaction alerts are stripped first so those alerts survive. Tune with data.
OTP_WARNING_RE = re.compile(
    r"(?:never|do\s*not|don'?t|not\s+to)\s+share\s+(?:your\s+|the\s+|this\s+)?"
    r"(?:otp|one[\s-]?time[\s-]?password|pin|cvv)",
    re.IGNORECASE,
)
OTP_RE = re.compile(r"\b(?:otp|one[\s-]?time[\s-]?password|verification\s+code)\b", re.IGNORECASE)

UPI_ID_RE = re.compile(r"\b[\w.\-]+@([a-zA-Z][a-zA-Z0-9]+)\b")
# Indian mobile numbers, optionally prefixed with +91 / 91 / 0.
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?[6-9]\d{9}(?!\d)")
# Number right after an account/card keyword: "A/c XX1234", "Card no. 4111 1111 1111 1234".
ACCOUNT_RE = re.compile(
    r"(?P<prefix>\b(?:a/c|ac|acct|account|card)\b\.?"
    r"(?:\s*(?:no|number|ending(?:\s+(?:with|in))?)\b\.?)?\s*[:\-]?\s*)"
    r"(?P<num>[Xx*\d]+(?:[ -][Xx*\d]{4})*)(?!\w)",
    re.IGNORECASE,
)
# Any other long digit run: account numbers, card numbers, UPI/IMPS refs.
LONG_DIGITS_RE = re.compile(r"(?<!\d)\d{9,}(?!\d)")


def keep_last4(s: str) -> str:
    """Replace every digit except the last four with 'X', keeping separators."""
    n_digits = sum(c.isdigit() for c in s)
    out, seen = [], 0
    for c in s:
        if c.isdigit():
            seen += 1
            out.append(c if seen > n_digits - 4 else "X")
        else:
            out.append(c)
    return "".join(out)


def redact(body: str) -> str:
    body = UPI_ID_RE.sub(lambda m: f"xxxx@{m.group(1)}", body)
    body = PHONE_RE.sub(lambda m: re.sub(r"\d", "X", m.group()), body)
    body = ACCOUNT_RE.sub(lambda m: m.group("prefix") + keep_last4(m.group("num")), body)
    return LONG_DIGITS_RE.sub(lambda m: keep_last4(m.group()), body)


def is_otp(body: str) -> bool:
    return bool(OTP_RE.search(OTP_WARNING_RE.sub("", body)))


def match_sender(address: str, senders: set[str]) -> str | None:
    for part in address.upper().replace(" ", "").split("-"):
        if part in senders:
            return part
    return None


def iter_sms(path: Path):
    """Stream <sms> elements so large backups don't load fully into memory."""
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag == "sms":
            yield dict(elem.attrib)
        elem.clear()


def collect(paths: list[Path], senders: set[str]) -> tuple[dict[str, list[dict]], dict]:
    by_sender: dict[str, list[dict]] = defaultdict(list)
    stats = {"total": 0, "kept": 0, "otp_dropped": 0, "other_sender": 0}
    for path in paths:
        for sms in iter_sms(path):
            stats["total"] += 1
            sender = match_sender(sms.get("address", ""), senders)
            if sender is None:
                stats["other_sender"] += 1
                continue
            body = sms.get("body", "")
            if is_otp(body):
                stats["otp_dropped"] += 1
                continue
            date_ms = int(sms.get("date") or 0)
            by_sender[sender].append(
                {
                    "sender": sender,
                    "date_utc": datetime.fromtimestamp(date_ms / 1000, UTC).isoformat(),
                    "body": redact(body),
                }
            )
            stats["kept"] += 1
    return by_sender, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("inputs", nargs="*", type=Path, help="XML files (default: data/raw/*.xml)")
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--senders", default=DEFAULT_SENDERS, help="comma-separated sender IDs")
    ap.add_argument("--limit", type=int, help="random sample of N messages per sender")
    ap.add_argument("--seed", type=int, default=0, help="seed for --limit sampling")
    args = ap.parse_args(argv)

    paths = args.inputs or sorted(DEFAULT_INPUT_DIR.glob("*.xml"))
    if not paths:
        print(f"No XML files given and none found in {DEFAULT_INPUT_DIR}", file=sys.stderr)
        return 1

    senders = {s.strip().upper() for s in args.senders.split(",") if s.strip()}
    by_sender, stats = collect(paths, senders)

    rng = random.Random(args.seed)
    out: list[dict] = []
    for sender in sorted(by_sender):
        msgs = by_sender[sender]
        if args.limit is not None and len(msgs) > args.limit:
            msgs = rng.sample(msgs, args.limit)
        out.extend(sorted(msgs, key=lambda m: m["date_utc"]))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    per_sender = ", ".join(f"{s}={len(v)}" for s, v in sorted(by_sender.items()))
    print(f"{stats} written={len(out)} -> {args.output}", file=sys.stderr)
    print(f"per sender (before --limit): {per_sender or 'none'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
