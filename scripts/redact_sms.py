r"""Redact an SMS Backup & Restore XML export into a shareable JSON sample.

Default-deny: every counterparty name and every UPI ID local part is replaced
unless it is on the keep-list (scripts/keep_names.txt plus an optional
keep_names.txt in --private-dir). It never guesses person vs merchant.

- Streams the XML (250 MB+ is fine) and skips <mms>.
- Keeps allowlisted bank and UPI senders only. Sender IDs are normalised to
  their core first (operator prefix and TRAI suffix stripped, with or without
  hyphens). Promotional (suffix P) and OTP messages are dropped.
- Names become PARTY_001, PARTY_002, ... via name_map.json in --private-dir.
- References, phone numbers and UPI local parts get fakes of the same shape,
  derived with HMAC-SHA256 and a random key (redaction.key in --private-dir,
  created on first run). The same input gives the same fake on every run.
- Account/card numbers keep the bank's mask style and only the last 4 digits.

Real data lives outside the repo. Run this yourself; agents never do.

  python scripts/redact_sms.py --input D:/FlashPrivate/raw --private-dir D:/FlashPrivate/private --list-senders
  python scripts/redact_sms.py --input D:/FlashPrivate/raw --private-dir D:/FlashPrivate/private --list-counterparties
  python scripts/redact_sms.py --input D:/FlashPrivate/raw --private-dir D:/FlashPrivate/private --output data/sample/redacted_sample.json --limit 50
"""  # noqa: E501

import argparse
import hashlib
import hmac
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

PROGRESS_EVERY = 5_000
KEEP_FILE = Path(__file__).with_name("keep_names.txt")
PRIVATE_KEEP_FILE = "keep_names.txt"
NAME_MAP_FILE = "name_map.json"
KEY_FILE = "redaction.key"

# Banks and UPI only. Investment, broker and exchange senders are deliberately
# excluded until Phase 6 (data minimisation). Values are normalised cores.
DEFAULT_SENDERS = (
    "HDFCBK,HDFCBN,SBIBNK,CBSSBI,SBIUPI,SBIINB,SBYONO,SBIPSG,"
    "ICICIT,AXISBK,KOTAKM,YESBNK,DOPBNK,PHONPE"
)
TRAI_SUFFIXES = {"S", "T", "P", "G"}  # service, transactional, promotional, government

# --- OTP ----------------------------------------------------------------------
# ponytail: keyword heuristic. "Never share your OTP" warnings inside real
# transaction alerts are stripped first so those alerts survive. Tune with data.
OTP_WARNING_RE = re.compile(
    r"(?:never|do\s*not|don'?t|not\s+to)\s+share\s+(?:your\s+|the\s+|this\s+)?"
    r"(?:otp|one[\s-]?time[\s-]?password|pin|cvv)",
    re.IGNORECASE,
)
OTP_RE = re.compile(r"\b(?:otp|one[\s-]?time[\s-]?password|verification\s+code)\b", re.IGNORECASE)

# --- Identifiers --------------------------------------------------------------
UPI_ID_RE = re.compile(r"\b(?P<local>[\w.\-]+)@(?P<handle>[a-zA-Z][a-zA-Z0-9]+)\b")  # + emails
PHONE_RE = re.compile(r"(?<!\d)(?P<prefix>(?:\+?91[\s-]?|0)?)(?P<num>[6-9]\d{9})(?!\d)")
ACCOUNT_RE = re.compile(
    r"(?P<prefix>\b(?:a/c|ac|acct|account|card)\b\.?"
    r"(?:\s*(?:no|number|ending(?:\s+(?:with|in))?)\b\.?)?\s*[:\-]?\s*)"
    r"(?P<num>[Xx*\d]+(?:[ -][Xx*\d]{4})*)(?!\w)",
    re.IGNORECASE,
)
LONG_DIGITS_RE = re.compile(r"(?<!\d)\d{9,}(?!\d)")  # unlabelled account numbers
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
# Private-use characters never appear in SMS; masked values hide between them
# so later patterns cannot touch them.
PH_OPEN, PH_CLOSE = chr(0xE000), chr(0xE001)
PLACEHOLDER_RE = re.compile(f"{PH_OPEN}(\\d+){PH_CLOSE}")

# --- Counterparty names -------------------------------------------------------
# Positions where a counterparty name appears. Whatever is found there is
# pseudonymised unless keep-listed. Names outside these positions are not
# detected, so review the output (and --list-counterparties) before sharing.
NAME_WORD = r"[A-Za-z][A-Za-z.']*"
NAME = rf"{NAME_WORD}(?:[ ]+{NAME_WORD}){{0,3}}"
COUNTERPARTY_RES = (
    re.compile(rf"\b(?:UPI|IMPS|NEFT|RTGS)/(?:P2[PAM]/)?[^/\s]+/(?P<name>{NAME})", re.I),
    re.compile(rf";[ ]*(?P<name>{NAME})[ ]+credited\b", re.I),  # ICICI: "; NAME credited"
    re.compile(rf"\bdear[ ]+(?P<name>{NAME})", re.I),
    # Lookahead keeps "by IMPS from Mr. X" from hiding "from Mr. X".
    re.compile(
        rf"\b(?:to|from|by|at|towards)[ ]+(?=(?:(?:mr|mrs|ms|dr)\.?[ ]+)?(?P<name>{NAME}))",
        re.I,
    ),
)
# Words that end a name. They describe message structure, not people/merchants.
STOP_WORDS = set(
    """
    A AC ACCT ACCOUNT AND AT ATM AVL BAL BALANCE BENEFICIARY BLOCK BY CALL CARDHOLDER
    CASH CHEQUE CLICK CREDIT CREDITED CUSTOMER DATE DATED DEAR DEBIT DEBITED DISPUTE
    EMI FOR FRAUD FROM HAS ID IF IMPS IN INFO INR INTEREST IS KINDLY LINKED LOAN MADAM
    MEMBER MOBILE NEFT NO NOT OF ON OTP PAID PLEASE PLS RECEIVED REF REFNO REFERENCE
    REPORT RRN RS RTGS SAVINGS SELF SENT SIR SMS THANK THANKS THE TO TOWARDS TRANSFER
    TRANSFERRED TRF TXN TRANSACTION UPI UR USER USING UTR VALUED VIA VPA WALLET WAS
    WITH YOU YOUR
    """.split()
)
WORD_RE = re.compile(r"[A-Za-z]+")


def norm(text: str) -> str:
    """'Amazon.Pay' -> 'AMAZON PAY'. Used for keep-list and name-map keys."""
    return " ".join(WORD_RE.findall(text.upper()))


def name_key(raw: str) -> str:
    """Leading words up to the first stop word: 'Rahul Kumar on' -> 'RAHUL KUMAR'."""
    words = []
    for w in WORD_RE.findall(raw.upper()):
        if w in STOP_WORDS:
            break
        words.append(w)
    return " ".join(words)


def find_names(body: str) -> list[str]:
    """Counterparty names in a body whose IDs/refs/phones are already placeholders."""
    names = []
    for rx in COUNTERPARTY_RES:
        for m in rx.finditer(body):
            key = name_key(m.group("name"))
            if len(key.replace(" ", "")) >= 2:
                names.append(key)
    return names


def keep_last4(s: str) -> str:
    """Mask every digit except the last four with 'X', keeping the bank's own style."""
    n_digits = sum(c.isdigit() for c in s)
    out, seen = [], 0
    for c in s:
        if c.isdigit():
            seen += 1
            out.append(c if seen > n_digits - 4 else "X")
        else:
            out.append(c)
    return "".join(out)


def is_otp(body: str) -> bool:
    return bool(OTP_RE.search(OTP_WARNING_RE.sub("", body)))


def parse_sender(address: str) -> tuple[str, str]:
    """Normalise a sender ID to (core, TRAI suffix).

    Hyphens are optional, so VM-HDFCBK-S, VMHDFCBKS, HDFCBK-S and VMHDFCBK all
    give core HDFCBK. Rules, after uppercasing and removing hyphens:
      9 chars ending S/T/P/G  -> drop 2-letter prefix and the suffix
      8 chars                 -> drop 2-letter prefix
      7 chars ending S/T/P/G  -> drop the suffix
      digits, maybe prefixed  -> drop a 2-letter prefix (CP388558 -> 388558)
      anything else           -> unchanged (e.g. ...@RBM.GOOG, +91 numbers)
    """
    sid = address.upper().replace("-", "").replace(" ", "")
    if sid[2:].isdigit() and (sid[:2].isalpha() or sid[:2].isdigit()):
        return (sid[2:] if sid[:2].isalpha() else sid), ""
    if not sid.isalnum():
        return sid, ""
    if len(sid) == 9 and sid[:2].isalpha() and sid[-1] in TRAI_SUFFIXES:
        return sid[2:-1], sid[-1]
    if len(sid) == 8 and sid[:2].isalpha():
        return sid[2:], ""
    if len(sid) == 7 and sid[-1] in TRAI_SUFFIXES:
        return sid[:-1], sid[-1]
    return sid, ""


def is_allowlisted(core: str, senders: set[str]) -> bool:
    """Only plain alphanumeric cores can match; RCS IDs and numbers never do."""
    return core.isalnum() and core in senders


def is_phone_number(header: str) -> bool:
    """Personal numbers are hidden in --list-senders; short codes are shown."""
    return sum(c.isdigit() for c in header) >= 7 or not header


def load_keep(private_dir: Path) -> set[str]:
    keep: set[str] = set()
    for path in (KEEP_FILE, private_dir / PRIVATE_KEEP_FILE):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                entry = norm(line.split("#", 1)[0])
                if entry:
                    keep.add(entry)
    return keep


def _hold(held: list[str], text: str) -> str:
    held.append(text)
    return f"{PH_OPEN}{len(held) - 1}{PH_CLOSE}"


def scan(body: str) -> tuple[list[str], list[str]]:
    """(names, UPI IDs) in a raw body, for --list-counterparties. Nothing is faked."""
    upi_ids = [m.group(0) for m in UPI_ID_RE.finditer(body)]
    for rx in (*REF_RES, UPI_ID_RE, PHONE_RE):
        body = rx.sub(PH_OPEN + PH_CLOSE, body)
    return find_names(body), upi_ids


class Redactor:
    """Masks bodies. Holds the name map, HMAC key and keep-list for one run."""

    def __init__(self, private_dir: Path) -> None:
        private_dir.mkdir(parents=True, exist_ok=True)
        self.keep = load_keep(private_dir)
        self.key = _load_or_create_key(private_dir / KEY_FILE)
        self.names_path = private_dir / NAME_MAP_FILE
        self.names: dict[str, str] = _load_json(self.names_path)
        self.seen: dict[str, set[str]] = {
            k: set() for k in ("names_kept", "names_pseudonymised", "upi_kept", "upi_pseudonymised")
        }
        self._people: dict[str, str] = {}
        self._first_words: set[str] = {k.split()[0] for k in self.keep}
        self._next = 1
        for key, token in self.names.items():
            self._remember(key, token)

    def mask(self, body: str) -> str:
        """Fake refs, UPI IDs and phones; mask accounts; record names for pseudonymise()."""
        held: list[str] = []

        def ref(m: re.Match) -> str:
            value = m.group("ref")
            if sum(c.isdigit() for c in value) < 6:
                return m.group(0)
            i = m.start("ref") - m.start()
            fake = _hold(held, self._fake("ref", value))
            return m.group(0)[:i] + fake + m.group(0)[i + len(value) :]

        for rx in REF_RES:
            body = rx.sub(ref, body)
        body = UPI_ID_RE.sub(lambda m: _hold(held, self._upi(m["local"], m["handle"])), body)
        body = PHONE_RE.sub(lambda m: m["prefix"] + _hold(held, self._phone(m["num"])), body)
        for key in find_names(body):
            self._note_name(key)
        body = ACCOUNT_RE.sub(lambda m: m["prefix"] + keep_last4(m["num"]), body)
        body = LONG_DIGITS_RE.sub(lambda m: keep_last4(m.group()), body)
        return PLACEHOLDER_RE.sub(lambda m: held[int(m.group(1))], body)

    def pseudonymise(self, body: str) -> str:
        """Replace every mapped name (any case, any position) with its token.

        Keep-listed phrases are matched first and skipped, so a brand such as
        "AMAZON PAY" survives even if "AMAZON" alone were mapped.
        """
        words = list(WORD_RE.finditer(body))
        out, pos, i = [], 0, 0
        while i < len(words):
            step = 1
            if words[i].group().upper() in self._first_words:
                for n in range(min(len(words) - i, 8), 0, -1):
                    span = words[i : i + n]
                    gaps = (body[a.end() : b.start()] for a, b in pairwise(span))
                    if any(gap.strip(" .'") for gap in gaps):
                        continue
                    key = " ".join(w.group().upper() for w in span)
                    if key in self.keep:
                        step = n
                        break
                    if key in self._people:
                        out += [body[pos : span[0].start()], self._people[key]]
                        pos, step = span[-1].end(), n
                        break
            i += step
        return "".join(out) + body[pos:]

    def redact(self, body: str) -> str:
        return self.pseudonymise(self.mask(body))

    def save(self) -> None:
        _save_text(self.names_path, json.dumps(self.names, indent=2, sort_keys=True))

    def _note_name(self, key: str) -> None:
        if key in self.keep:
            self.seen["names_kept"].add(key)
            return
        self.seen["names_pseudonymised"].add(key)
        if key not in self.names:
            self.names[key] = f"PARTY_{self._next:03d}"
            self._remember(key, self.names[key])

    def _remember(self, key: str, token: str) -> None:
        if key in self.keep or not key:
            return  # keep-listed since the map was written
        self._people[key] = token
        self._first_words.add(key.split()[0])
        digits = token.rpartition("_")[2]
        if digits.isdigit():
            self._next = max(self._next, int(digits) + 1)

    def _upi(self, local: str, handle: str) -> str:
        if norm(local) in self.keep:
            self.seen["upi_kept"].add(local.lower())
            return f"{local}@{handle}"
        self.seen["upi_pseudonymised"].add(local.lower())
        is_phone = re.fullmatch(r"[6-9]\d{9}", local)
        fake = self._phone(local) if is_phone else self._fake("upi", local)
        return f"{fake}@{handle}"

    def _phone(self, num: str) -> str:
        """10 digits in, 10 digits out, still starting with 6-9."""
        fake = self._fake("phone", num)
        return "6789"[int(fake[0]) % 4] + fake[1:]

    def _fake(self, kind: str, value: str) -> str:
        """Same length and character type per position: digit, A-Z, a-z; others kept."""
        stream = b""
        out = []
        for i, c in enumerate(value):
            while len(stream) <= i:
                msg = f"{kind}:{value.upper()}:{len(stream)}".encode()
                stream += hmac.new(self.key, msg, hashlib.sha256).digest()
            b = stream[i]
            if c in string.digits:
                out.append(string.digits[b % 10])
            elif c in string.ascii_uppercase:
                out.append(string.ascii_uppercase[b % 26])
            elif c in string.ascii_lowercase:
                out.append(string.ascii_lowercase[b % 26])
            else:
                out.append(c)
        return "".join(out)


def _load_or_create_key(path: Path) -> bytes:
    if not path.exists():
        _save_text(path, secrets.token_hex(32))
    return bytes.fromhex(path.read_text(encoding="utf-8").strip())


def _load_json(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text + "\n", encoding="utf-8", newline="\n")
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


def iter_relevant(
    paths: Iterable[Path], senders: set[str], dropped: Counter
) -> Iterator[tuple[str, dict[str, str]]]:
    """Allowlisted, non-promotional, non-OTP SMS. Counts every drop by reason."""
    for _, sms in iter_files(paths):
        if sms is None:
            dropped["mms (skipped)"] += 1
            continue
        header, suffix = parse_sender(sms.get("address", ""))
        if not is_allowlisted(header, senders):
            dropped["sender not allowlisted"] += 1
        elif suffix == "P":
            dropped["promotional (-P)"] += 1
        elif is_otp(sms.get("body", "")):
            dropped["otp"] += 1
        else:
            yield header, sms


# --- Modes --------------------------------------------------------------------
def list_senders(paths: list[Path], senders: set[str]) -> None:
    totals: Counter = Counter()
    promo: Counter = Counter()
    phones: Counter = Counter()
    variants: dict[str, set[str]] = defaultdict(set)
    mms = 0
    for _, sms in iter_files(paths):
        if sms is None:
            mms += 1
            continue
        raw = sms.get("address", "")
        header, suffix = parse_sender(raw)
        if is_phone_number(header):
            phones[header] += 1
            continue
        totals[header] += 1
        promo[header] += suffix == "P"
        variants[header].add(raw.upper().replace(" ", ""))
    print(f"{'SENDER':<20}{'MESSAGES':>10}{'PROMO':>8}{'VARIANTS':>10}  ALLOWLISTED")
    for header, n in totals.most_common():
        flag = "yes" if is_allowlisted(header, senders) else ""
        print(f"{header:<20}{n:>10,}{promo[header]:>8,}{len(variants[header]):>10,}  {flag}")
    print(f"\nPhone numbers (hidden): {phones.total():,} messages from {len(phones):,} numbers")
    print(f"MMS (skipped): {mms:,}")


def list_counterparties(paths: list[Path], senders: set[str], keep: set[str]) -> None:
    names: Counter = Counter()
    upi_ids: Counter = Counter()
    for _, sms in iter_relevant(paths, senders, Counter()):
        found_names, found_upi = scan(sms.get("body", ""))
        names.update(found_names)
        upi_ids.update(u.lower() for u in found_upi)
    for title, counts, to_key in (
        ("COUNTERPARTY NAME", names, lambda k: k),
        ("UPI ID", upi_ids, lambda k: norm(k.split("@")[0])),
    ):
        print(f"\n{'MESSAGES':>8}  KEPT  {title}")
        for value, n in counts.most_common():
            print(f"{n:>8,}  {'yes ' if to_key(value) in keep else '    '}  {value}")


def redact_to_file(args: argparse.Namespace, paths: list[Path], senders: set[str]) -> None:
    redactor = Redactor(args.private_dir)
    dropped: Counter = Counter()
    kept: dict[str, list[dict]] = defaultdict(list)
    for header, sms in iter_relevant(paths, senders, dropped):
        date_ms = int(sms.get("date") or 0)
        kept[header].append(
            {
                "sender": header,
                "date_utc": datetime.fromtimestamp(date_ms / 1000, UTC).isoformat(),
                "body": redactor.mask(sms.get("body", "")),
            }
        )

    rng = random.Random(args.seed)
    out: list[dict] = []
    for header in sorted(kept):
        msgs = kept[header]
        if args.limit is not None and len(msgs) > args.limit:
            msgs = rng.sample(msgs, args.limit)
        out.extend(sorted(msgs, key=lambda m: m["date_utc"]))
    for msg in out:  # after the full pass, so a name found anywhere is replaced everywhere
        msg["body"] = redactor.pseudonymise(msg["body"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    redactor.save()

    n_kept = sum(len(v) for v in kept.values())
    s = {k: len(v) for k, v in redactor.seen.items()}
    print(f"\nRead {n_kept + dropped.total():,} messages. Kept {n_kept:,}.")
    print("Dropped:")
    for reason, n in dropped.most_common():
        print(f"  {reason:<24}{n:>10,}")
    print("Kept per sender:")
    for header, msgs in sorted(kept.items(), key=lambda kv: -len(kv[1])):
        print(f"  {header:<24}{len(msgs):>10,}")
    print("Distinct values this run:")
    print(f"  {'names kept (keep-list)':<24}{s['names_kept']:>10,}")
    print(f"  {'names pseudonymised':<24}{s['names_pseudonymised']:>10,}")
    print(f"  {'UPI IDs kept':<24}{s['upi_kept']:>10,}")
    print(f"  {'UPI IDs pseudonymised':<24}{s['upi_pseudonymised']:>10,}")
    print(f"Wrote {len(out):,} messages to {args.output}")


def resolve_inputs(inputs: list[Path]) -> list[Path]:
    """Files as given; folders expand to their *.xml files."""
    paths: list[Path] = []
    for p in inputs:
        paths.extend(sorted(p.glob("*.xml")) if p.is_dir() else [p])
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--input", type=Path, nargs="+", required=True, help="XML files or folders")
    ap.add_argument("--private-dir", type=Path, required=True, help="name map, key, keep-list")
    ap.add_argument("--output", type=Path, help="JSON sample to write (required unless listing)")
    ap.add_argument("--senders", default=DEFAULT_SENDERS, help="comma-separated sender IDs")
    ap.add_argument("--limit", type=int, help="random sample of N messages per sender")
    ap.add_argument("--seed", type=int, default=0, help="seed for --limit sampling")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--list-senders", action="store_true", help="sender IDs and counts only")
    mode.add_argument(
        "--list-counterparties", action="store_true", help="names and UPI IDs with counts only"
    )
    args = ap.parse_args(argv)
    if not (args.list_senders or args.list_counterparties or args.output):
        ap.error("--output is required unless --list-senders or --list-counterparties is used")

    paths = resolve_inputs(args.input)
    if not paths:
        print("No XML files found in --input", file=sys.stderr)
        return 1
    senders = {parse_sender(s.strip())[0] for s in args.senders.split(",") if s.strip()}

    try:
        if args.list_senders:
            list_senders(paths, senders)
        elif args.list_counterparties:
            list_counterparties(paths, senders, load_keep(args.private_dir))
        else:
            redact_to_file(args, paths, senders)
    except ET.ParseError as e:
        print(f"XML parse error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
