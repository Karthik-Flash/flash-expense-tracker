"""Redact an SMS Backup & Restore XML export into a shareable JSON sample.

- Streams the XML, so 250 MB+ files are fine. <mms> elements are skipped.
- Keeps only allowlisted bank/card/UPI/wallet senders. The operator prefix
  (VM-, AD-, JD-, ...) and TRAI suffix (-S/-T/-P/-G) are ignored when matching.
  Promotional (-P) messages and OTP messages are dropped.
- Pseudonymises people's names in P2P UPI/IMPS/NEFT messages (PERSON_001, ...).
- Replaces UPI/IMPS/NEFT reference numbers with stable fakes of the same shape,
  so deduplication can still be tested on the sample.
- Masks account/card numbers (last 4 kept), UPI IDs, emails and phone numbers.

The name and reference maps live in data/private/ (gitignored, blocked for
agents) and are reused on every run: the same real value always gets the same
fake. If a merchant was mistaken for a person, open data/private/name_map.json,
set that entry's value to the name itself, and re-run.

Standard library only. Run it yourself; agents must never read data/raw/.

    python scripts/redact_sms.py --list-senders     # sender IDs + counts only
    python scripts/redact_sms.py --limit 50         # every data/raw/*.xml
    python scripts/redact_sms.py data/raw/x.xml --senders HDFCBK,MYBANK
"""

import argparse
import json
import os
import random
import re
import secrets
import string
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = ROOT / "data" / "raw"
DEFAULT_OUTPUT = ROOT / "data" / "sample" / "redacted_sample.json"
DEFAULT_PRIVATE_DIR = ROOT / "data" / "private"
PROGRESS_EVERY = 5_000

# DLT sender headers, without operator prefix or TRAI suffix.
# Grow this list with --list-senders.
DEFAULT_SENDERS = (
    "HDFCBK,ICICIT,ICICIB,SBIUPI,SBIINB,SBIPSG,CBSSBI,AXISBK,KOTAKB,"
    "PAYTMB,IPAYTM,PAYTM,YESBNK,INDUSB,IDFCFB,PNBSMS,BOBTXN,CANBNK,UNIONB,"
    "AMEXIN,SCBANK,CITIBK,PHONPE,GPAY,AMZPAY,MOBIKW,FREECH,ONECRD,SLICE"
)
TRAI_SUFFIXES = {"S", "T", "P", "G"}

# --- OTP ----------------------------------------------------------------------
# ponytail: keyword heuristic. "Never share your OTP" warnings inside real
# transaction alerts are stripped first so those alerts survive. Tune with data.
OTP_WARNING_RE = re.compile(
    r"(?:never|do\s*not|don'?t|not\s+to)\s+share\s+(?:your\s+|the\s+|this\s+)?"
    r"(?:otp|one[\s-]?time[\s-]?password|pin|cvv)",
    re.IGNORECASE,
)
OTP_RE = re.compile(r"\b(?:otp|one[\s-]?time[\s-]?password|verification\s+code)\b", re.IGNORECASE)

# --- Masking ------------------------------------------------------------------
UPI_ID_RE = re.compile(r"\b[\w.\-]+@([a-zA-Z][a-zA-Z0-9]+)\b")  # UPI IDs and emails
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?[6-9]\d{9}(?!\d)")
ACCOUNT_RE = re.compile(
    r"(?P<prefix>\b(?:a/c|ac|acct|account|card)\b\.?"
    r"(?:\s*(?:no|number|ending(?:\s+(?:with|in))?)\b\.?)?\s*[:\-]?\s*)"
    r"(?P<num>[Xx*\d]+(?:[ -][Xx*\d]{4})*)(?!\w)",
    re.IGNORECASE,
)
LONG_DIGITS_RE = re.compile(r"(?<!\d)\d{9,}(?!\d)")

# --- Reference numbers ----------------------------------------------------------
REF_RES = (
    # UPI/P2P/612345678901/NAME, IMPS/P2A/..., NEFT/SBIN326317123456/NAME
    re.compile(r"\b(?:UPI|IMPS|NEFT|RTGS)/(?:P2[PAM]/)?(?P<ref>[A-Z0-9]{6,22})(?=/)", re.I),
    # Ref 6123..., UPI Ref No. 6123..., Refno ..., RRN: ..., UTR No ..., Txn ID ...
    re.compile(
        r"\b(?:ref(?:erence)?|rrn|utr|txn|transaction)\.?(?:[ ]*(?:no|number|id))?\.?"
        r"[ ]*[:#-]?[ ]*(?P<ref>[A-Z0-9]{6,22})\b",
        re.I,
    ),
    # UPI:612345678901, IMPS 612345678901
    re.compile(r"\b(?:UPI|IMPS|NEFT|RTGS)[: -]+(?P<ref>\d{9,22})\b", re.I),
)
# Private-use characters never appear in SMS, so refs hide safely between them.
PH_OPEN, PH_CLOSE = "\ue000", "\ue001"
PLACEHOLDER_RE = re.compile(f"{PH_OPEN}(\\d+){PH_CLOSE}")

# --- People's names -----------------------------------------------------------
# ponytail: context heuristic, tuned to common Indian bank formats. It errs
# toward pseudonymising; a merchant hit by mistake is fixed in name_map.json.
NAME_WORD = r"[A-Za-z][A-Za-z.']*"
NAME = rf"{NAME_WORD}(?:[ ]+{NAME_WORD}){{0,3}}"
P2P_HINT_RE = re.compile(r"\b(?:upi|imps|neft|rtgs|vpa|p2p|p2a|trf|sent)\b|transfer", re.I)
ALWAYS_NAME_RES = (
    # UPI/P2P/<ref>/RAHUL KUMAR (P2M is a merchant payment, so it is skipped)
    re.compile(rf"\b(?:UPI|IMPS|NEFT|RTGS)/(?!P2M/)(?:P2[PA]/)?[^/\s]+/(?P<name>{NAME})", re.I),
    # ICICI style: "...; RAHUL KUMAR credited"
    re.compile(rf";[ ]*(?P<name>{NAME})[ ]+credited\b", re.I),
    # Greeting with the account holder's own name
    re.compile(rf"\bdear[ ]+(?P<name>{NAME})", re.I),
)
# "to/from/by NAME" only counts in messages that look like transfers.
# The name sits in a lookahead so "by IMPS from Mr. X" still finds "from Mr. X".
TRANSFER_NAME_RE = re.compile(
    rf"\b(?:to|from|by)[ ]+(?=(?:(?:mr|mrs|ms|dr)\.?[ ]+)?(?P<name>{NAME}))", re.I
)
STOP_WORDS = set(
    """
    A AC ACCT ACCOUNT AND AT ATM AVL BAL BALANCE BENEFICIARY BLOCK BY CALL CARDHOLDER
    CASH CHEQUE CLICK CREDIT CREDITED CUSTOMER DATE DATED DEAR DEBIT DEBITED DISPUTE
    FOR FRAUD FROM HAS ID IF IMPS IN INFO INR INTEREST IS KINDLY LINKED LOAN MADAM
    MEMBER MERCHANT MOBILE NEFT NO NOT OF ON OTP PAID PLEASE PLS RECEIVED REF REFNO
    REFERENCE REPORT RRN RS RTGS SAVINGS SELF SENT SIR SMS THANK THANKS THE TO TRANSFER
    TRANSFERRED TRF TXN TRANSACTION UPI UR USER USING UTR VALUED VIA VPA WALLET WAS
    WITH YOU YOUR
    """.split()
)
NOT_PERSON = set(
    """
    AGENCIES AGENCY BAKERY BANK CAFE CAPITAL CARD CENTER CENTRE CHEMIST CLINIC CLUB
    COLLEGE COMPANY CORP CORPORATION DIGITAL ELECTRONICS ENTERPRISE ENTERPRISES FASTAG
    FINANCE FITNESS FOOD FOODS GLOBAL GROUP GYM HOSPITAL HOTEL INDIA INDUSTRIES
    INSURANCE INTERNATIONAL KITCHEN LIMITED LLP LTD MART MEDICAL MEDICALS MOTORS ONLINE
    PAY PAYMENTS PETROL PETROLEUM PHARMA PHARMACY PRIVATE PVT RESTAURANT RETAIL SALON
    SCHOOL SECURITIES SERVICE SERVICES SHOP SOLUTIONS STATION STORE STORES SUPERMARKET
    SWEETS TECH TECHNOLOGIES TECHNOLOGY TELECOM TRADERS TRADING TRAVELS TRUST
    UNIVERSITY VENTURES
    AXIS BOB CANARA CITI FEDERAL HDFC HSBC ICICI IDFC INDUSIND KOTAK PNB RBL SBI YES
    AIRTEL AMAZON BIGBASKET BLINKIT BOOKMYSHOW DOMINOS DUNZO FLIPKART GOOGLE IRCTC JIO
    MAKEMYTRIP MCDONALDS MYNTRA NETFLIX NYKAA OLA PAYTM PHONEPE RAPIDO SPOTIFY
    STARBUCKS SWIGGY UBER ZEPTO ZOMATO
    """.split()
)
WORD_RE = re.compile(r"[A-Za-z]+")


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


def name_key(raw: str) -> str:
    """Leading words of raw up to the first stop word, e.g. 'Rahul Kumar on' -> 'RAHUL KUMAR'."""
    words = []
    for w in WORD_RE.findall(raw.upper()):
        if w in STOP_WORDS or set(w) == {"X"}:
            break
        words.append(w)
    return " ".join(words)


def is_otp(body: str) -> bool:
    return bool(OTP_RE.search(OTP_WARNING_RE.sub("", body)))


def parse_sender(address: str) -> tuple[str, str]:
    """'VM-HDFCBK-S' -> ('HDFCBK', 'S'); 'HDFCBK' -> ('HDFCBK', '')."""
    parts = [p for p in address.upper().replace(" ", "").split("-") if p]
    if len(parts) > 1 and len(parts[0]) == 2 and parts[0].isalpha():
        parts = parts[1:]  # operator/circle prefix
    if not parts:
        return "", ""
    suffix = parts[-1] if len(parts) > 1 and parts[-1] in TRAI_SUFFIXES else ""
    return parts[0], suffix


def is_phone_number(header: str) -> bool:
    """Personal numbers are hidden in --list-senders; short codes are shown."""
    return sum(c.isdigit() for c in header) >= 7 or not header


class Redactor:
    """Masks message bodies and keeps the stable name/reference pseudonym maps."""

    def __init__(self, private_dir: Path) -> None:
        self.names_path = private_dir / "name_map.json"
        self.refs_path = private_dir / "ref_map.json"
        self.names: dict[str, str] = _load_json(self.names_path)
        self.refs: dict[str, str] = _load_json(self.refs_path)
        self._fakes = set(self.refs.values())
        self._people: dict[str, str] = {}
        self._first_words: set[str] = set()
        self._next_person = 1
        for key, token in self.names.items():
            self._remember(key, token)

    def mask(self, body: str) -> str:
        """Fake refs; mask UPI IDs, phones, accounts; note names (replaced by pseudonymise)."""
        fakes: list[str] = []

        def stash(m: re.Match) -> str:
            ref = m.group("ref")
            if sum(c.isdigit() for c in ref) < 6:
                return m.group(0)
            fakes.append(self._fake_ref(ref))
            i = m.start("ref") - m.start()
            head, tail = m.group(0)[:i], m.group(0)[i + len(ref) :]
            return f"{head}{PH_OPEN}{len(fakes) - 1}{PH_CLOSE}{tail}"

        for rx in REF_RES:
            body = rx.sub(stash, body)
        body = UPI_ID_RE.sub(lambda m: f"xxxx@{m.group(1)}", body)
        body = PHONE_RE.sub(lambda m: re.sub(r"\d", "X", m.group()), body)
        self._note_names(body)
        body = ACCOUNT_RE.sub(lambda m: m.group("prefix") + keep_last4(m.group("num")), body)
        body = LONG_DIGITS_RE.sub(lambda m: keep_last4(m.group()), body)
        return PLACEHOLDER_RE.sub(lambda m: fakes[int(m.group(1))], body)

    def pseudonymise(self, body: str) -> str:
        """Replace every known person's name (any case, 1-N words) with their token."""
        words = list(WORD_RE.finditer(body))
        out, pos, i = [], 0, 0
        while i < len(words):
            if words[i].group().upper() in self._first_words:
                for n in range(min(len(words) - i, 8), 0, -1):
                    span = words[i : i + n]
                    if any(body[a.end() : b.start()].strip(" .'") for a, b in pairwise(span)):
                        continue
                    token = self._people.get(" ".join(w.group().upper() for w in span))
                    if token:
                        out += [body[pos : span[0].start()], token]
                        pos = span[-1].end()
                        i += n
                        break
                else:
                    i += 1
            else:
                i += 1
        return "".join(out) + body[pos:]

    def redact(self, body: str) -> str:
        return self.pseudonymise(self.mask(body))

    def save(self) -> None:
        _save_json(self.names_path, self.names)
        _save_json(self.refs_path, self.refs)

    def _note_names(self, body: str) -> None:
        regexes = ALWAYS_NAME_RES + ((TRANSFER_NAME_RE,) if P2P_HINT_RE.search(body) else ())
        for rx in regexes:
            for m in rx.finditer(body):
                key = name_key(m.group("name"))
                if len(key.replace(" ", "")) < 3 or key in self.names:
                    continue
                if set(key.split()) & NOT_PERSON or key.replace(" ", "") in NOT_PERSON:
                    continue
                self.names[key] = f"PERSON_{self._next_person:03d}"
                self._remember(key, self.names[key])

    def _remember(self, key: str, token: str) -> None:
        if not token.startswith("PERSON_") or not key.split():
            return  # manual override: value == name means "keep as is"
        self._people[key] = token
        self._first_words.add(key.split()[0])
        if token[7:].isdigit():
            self._next_person = max(self._next_person, int(token[7:]) + 1)

    def _fake_ref(self, ref: str) -> str:
        key = ref.upper()
        if key not in self.refs:
            while True:
                fake = "".join(secrets.choice(string.digits) if c.isdigit() else c for c in key)
                if fake != key and fake not in self._fakes:
                    break
            self.refs[key] = fake
            self._fakes.add(fake)
        return self.refs[key]


def _load_json(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save_json(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
    os.replace(tmp, path)


# --- Streaming XML ------------------------------------------------------------
CHARREF_RE = re.compile(rb"&#(?:x([0-9a-fA-F]{1,6})|(\d{1,7}));")


def _fix_charref(m: re.Match) -> bytes:
    cp = int(m[1], 16) if m[1] else int(m[2])
    valid = (
        cp in (0x9, 0xA, 0xD)
        or 0x20 <= cp <= 0xD7FF
        or 0xE000 <= cp <= 0xFFFD
        or 0x10000 <= cp <= 0x10FFFF
    )
    return m[0] if valid else b"&#65533;"


class CharRefCleaner:
    """File wrapper that rewrites XML-invalid character references while streaming.

    SMS Backup & Restore writes emoji as UTF-16 surrogate pairs (&#55357;&#56832;),
    which XML parsers reject. They become U+FFFD instead of crashing the run.
    """

    def __init__(self, f) -> None:
        self.f, self.tail = f, b""

    def read(self, n: int = 1 << 16) -> bytes:
        while True:
            chunk = self.f.read(n if n and n > 0 else 1 << 16)
            data = self.tail + chunk
            if not chunk:
                self.tail = b""
                return CHARREF_RE.sub(_fix_charref, data)
            # Hold back a reference that may be split across chunks (max 10 bytes).
            cut = data.find(b"&", max(0, len(data) - 10))
            cut = len(data) if cut == -1 else cut
            data, self.tail = data[:cut], data[cut:]
            if data:
                return CHARREF_RE.sub(_fix_charref, data)


def iter_messages(source) -> Iterator[tuple[str, dict[str, str] | None]]:
    """Yield ('sms', attrs) or ('mms', None) per message without building the tree."""
    context = ET.iterparse(source, events=("start", "end"))
    _, root = next(context)
    for event, elem in context:
        if event == "end" and elem.tag in ("sms", "mms"):
            yield elem.tag, (dict(elem.attrib) if elem.tag == "sms" else None)
            root.clear()  # drop finished messages so memory stays flat


def iter_files(paths: Iterable[Path]) -> Iterator[tuple[str, dict[str, str] | None]]:
    n = 0
    for path in paths:
        with path.open("rb") as f:
            for item in iter_messages(CharRefCleaner(f)):
                n += 1
                if n % PROGRESS_EVERY == 0:
                    print(f"  ... {n:,} messages read", file=sys.stderr)
                yield item


# --- Modes --------------------------------------------------------------------
def collect(
    paths: Iterable[Path], senders: set[str], redactor: Redactor
) -> tuple[dict[str, list[dict]], Counter]:
    kept: dict[str, list[dict]] = defaultdict(list)
    dropped: Counter = Counter()
    for _, sms in iter_files(paths):
        if sms is None:
            dropped["mms (skipped)"] += 1
            continue
        header, suffix = parse_sender(sms.get("address", ""))
        body = sms.get("body", "")
        if header not in senders:
            dropped["sender not allowlisted"] += 1
        elif suffix == "P":
            dropped["promotional (-P)"] += 1
        elif is_otp(body):
            dropped["otp"] += 1
        else:
            date_ms = int(sms.get("date") or 0)
            kept[header].append(
                {
                    "sender": header,
                    "date_utc": datetime.fromtimestamp(date_ms / 1000, UTC).isoformat(),
                    "body": redactor.mask(body),
                }
            )
    return kept, dropped


def list_senders(paths: Iterable[Path], senders: set[str]) -> None:
    totals: Counter = Counter()
    promo: Counter = Counter()
    phones: Counter = Counter()
    mms = 0
    for _, sms in iter_files(paths):
        if sms is None:
            mms += 1
            continue
        header, suffix = parse_sender(sms.get("address", ""))
        if is_phone_number(header):
            phones[header] += 1
            continue
        totals[header] += 1
        promo[header] += suffix == "P"
    print(f"{'SENDER':<12}{'MESSAGES':>10}{'PROMO':>8}  ALLOWLISTED")
    for header, n in totals.most_common():
        print(f"{header:<12}{n:>10,}{promo[header]:>8,}  {'yes' if header in senders else ''}")
    print(f"\nPhone numbers (hidden): {phones.total():,} messages from {len(phones):,} numbers")
    print(f"MMS (skipped): {mms:,}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("inputs", nargs="*", type=Path, help="XML files (default: data/raw/*.xml)")
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--private-dir", type=Path, default=DEFAULT_PRIVATE_DIR)
    ap.add_argument("--senders", default=DEFAULT_SENDERS, help="comma-separated sender IDs")
    ap.add_argument("--limit", type=int, help="random sample of N messages per sender")
    ap.add_argument("--seed", type=int, default=0, help="seed for --limit sampling")
    ap.add_argument("--list-senders", action="store_true", help="print sender IDs and counts only")
    args = ap.parse_args(argv)

    paths = args.inputs or sorted(DEFAULT_INPUT_DIR.glob("*.xml"))
    if not paths:
        print(f"No XML files given and none found in {DEFAULT_INPUT_DIR}", file=sys.stderr)
        return 1
    senders = {s.strip().upper() for s in args.senders.split(",") if s.strip()}

    try:
        if args.list_senders:
            list_senders(paths, senders)
            return 0
        redactor = Redactor(args.private_dir)
        kept, dropped = collect(paths, senders, redactor)
    except ET.ParseError as e:
        print(f"XML parse error: {e}", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    out: list[dict] = []
    for header in sorted(kept):
        msgs = kept[header]
        if args.limit is not None and len(msgs) > args.limit:
            msgs = rng.sample(msgs, args.limit)
        out.extend(sorted(msgs, key=lambda m: m["date_utc"]))
    for msg in out:  # after the full pass, so every name found anywhere is replaced
        msg["body"] = redactor.pseudonymise(msg["body"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    redactor.save()

    n_kept = sum(len(v) for v in kept.values())
    print(f"\nRead {n_kept + dropped.total():,} messages. Kept {n_kept:,}.")
    print("Dropped:")
    for reason, n in dropped.most_common():
        print(f"  {reason:<24}{n:>10,}")
    print("Kept per sender:")
    for header, msgs in sorted(kept.items(), key=lambda kv: -len(kv[1])):
        print(f"  {header:<24}{len(msgs):>10,}")
    people = sum(v.startswith("PERSON_") for v in redactor.names.values())
    print(f"Wrote {len(out):,} messages to {args.output}")
    print(f"Pseudonyms: {people:,} people, {len(redactor.refs):,} references in {args.private_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
