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
- Optional always_redact.txt in --private-dir (own/family names, own phone):
  every whole-word occurrence is replaced in a final pass, whatever its position.
- --verify scans the written sample for always-redact entries, mapped names
  and real UPI IDs/references, printing tokens and positions only.

Real data lives outside the repo. Run this yourself; agents never do.
Standard sample command (Windows paths, from the repo root):

  python scripts/redact_sms.py --input D:/FlashPrivate/raw --private-dir D:/FlashPrivate/private --output data/sample/redacted_sample.json --limit 100 --seed 42 --verify

Also: --list-senders / --list-counterparties (with --input and --private-dir),
and --verify alone on an existing --output.
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
ALWAYS_FILE = "always_redact.txt"  # optional: own/family names, own phone number
SEEN_IDS_FILE = "seen_ids.json"  # keyed digests of real UPI IDs/refs, for --verify

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
# Links: scheme and host are kept; the path/query (can be a personal tracking
# link) gets a same-length fake.
URL_RE = re.compile(r"\b(?P<head>(?:https?://|www\.)[^/\s?#]+)(?P<rest>[/?#]\S*)?", re.I)
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

# Fixed bank template wording (see docs/templates/hdfc.md). Never a
# counterparty: skipped at the start of a name, ends a name, and never
# replaced. Separate from keep_names.txt, which lists brands that ARE
# counterparties. Punctuation counts as a space ("E-mandate" = "E MANDATE").
BANK_VOCABULARY = (
    "HDFC Bank",
    "HDFCBANK",
    "HDFC Bank Card",
    "HDFC Bank Debit Card",
    "HDFC Bank DEBIT/ATM Card",
    "HDFC Bank App",
    "HDFC Bank NetBanking",
    "HDFC Bank Online Banking",
    "HDFC Bank MobileBanking",
    "Debit Card",
    "International payment",
    "Biometric authentication",
    "authentication",
    "AutoPay",
    "E-mandate",
    "SI Hub",
    "Mandate Set",
    "Money Transfer",
    "Credit Alert",
    "Amt Deducted",
    "Payment Successful",
    "Transaction Reversed",
    "Forex Markup",
    "UPI Pin",
    "Block+Reissue",
    "TnC",
    "https",
    "http",
    "www",
)


def norm(text: str) -> str:
    """'Amazon.Pay' -> 'AMAZON PAY'. Used for keep-list, vocabulary and map keys."""
    return " ".join(WORD_RE.findall(text.upper()))


VOCAB = {norm(p) for p in BANK_VOCABULARY}
VOCAB_MAX_WORDS = max(len(v.split()) for v in VOCAB)


def _vocab_len(words: list[str], i: int) -> int:
    """Length in words of the longest bank-vocabulary phrase starting at words[i]."""
    for n in range(min(VOCAB_MAX_WORDS, len(words) - i), 0, -1):
        if " ".join(words[i : i + n]) in VOCAB:
            return n
    return 0


def name_key(raw: str) -> str:
    """Name words up to the first stop word or bank wording; leading bank wording dropped.

    'Rahul Kumar on' -> 'RAHUL KUMAR'; 'HDFC Bank Card x' -> 'X' (too short, ignored).
    """
    words = WORD_RE.findall(raw.upper())
    out: list[str] = []
    i = 0
    while i < len(words) and words[i] not in STOP_WORDS:
        n = _vocab_len(words, i)
        if n and out:
            break
        if n:
            i += n
            continue
        out.append(words[i])
        i += 1
    return " ".join(out)


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

    With hyphens, the parts are: optional 2-letter prefix, core, optional
    1-letter suffix (S/T/P/G): AB-ABCDE-P -> ABCDE, P; AB-123456 -> 123456.
    Without hyphens, length rules apply:
      9 chars ending S/T/P/G  -> drop 2-letter prefix and the suffix
      8 chars                 -> drop 2-letter prefix
      7 chars ending S/T/P/G  -> drop the suffix
      digits, maybe prefixed  -> drop a 2-letter prefix (CP388558 -> 388558)
    Anything else (e.g. ...@RBM.GOOG, +91 numbers) stays unchanged.
    """
    sid = address.upper().replace(" ", "")
    if "-" in sid and sid.replace("-", "").isalnum():
        parts = [p for p in sid.split("-") if p]
        suffix = parts.pop() if len(parts) > 1 and parts[-1] in TRAI_SUFFIXES else ""
        if len(parts) > 1 and len(parts[0]) == 2 and parts[0].isalpha():
            parts = parts[1:]
        return "".join(parts), suffix
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


def load_always_redact(private_dir: Path) -> list[str]:
    """Entries of <private-dir>/always_redact.txt; '#' starts a comment. Never printed."""
    path = private_dir / ALWAYS_FILE
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [e for line in lines if (e := line.split("#", 1)[0].strip())]


def phone_entry(entry: str) -> str | None:
    """The 10-digit mobile number in an always-redact entry, or None for a name."""
    digits = re.sub(r"\D", "", entry)
    tail = digits[-10:]
    if 10 <= len(digits) <= 12 and re.fullmatch(r"[6-9]\d{9}", tail):
        return tail
    return None


def name_pattern(key: str) -> re.Pattern[str]:
    """Whole-word, case-insensitive match of a normalised name ('RAHUL KUMAR')."""
    words = r"[\s.']+".join(map(re.escape, key.split()))
    return re.compile(rf"\b{words}\b", re.I)


def id_digest(key: bytes, kind: str, value: str) -> str:
    """Keyed digest, so --verify can spot a real ID without it being stored."""
    return hmac.new(key, f"seen:{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:32]


def _hold(held: list[str], text: str) -> str:
    held.append(text)
    return f"{PH_OPEN}{len(held) - 1}{PH_CLOSE}"


def scan(body: str) -> tuple[list[str], list[str]]:
    """(names, UPI IDs) in a raw body, for --list-counterparties. Nothing is faked."""
    upi_ids = [m.group(0) for m in UPI_ID_RE.finditer(body)]
    for rx in (URL_RE, *REF_RES, UPI_ID_RE, PHONE_RE):
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
        self._first_words: set[str] = {k.split()[0] for k in self.keep | VOCAB}
        self._next = 1
        for key, token in self.names.items():
            self._remember(key, token)
        self.seen_ids_path = private_dir / SEEN_IDS_FILE
        stored = _load_json(self.seen_ids_path)
        self.seen_ids = {k: set(stored.get(k, [])) for k in ("upi", "ref")}
        self._always = self._compile_always(load_always_redact(private_dir))

    def _compile_always(self, entries: list[str]) -> list[tuple[re.Pattern[str], str]]:
        """(pattern, replacement) per always-redact entry, longest names first."""
        rules = []
        for entry in entries:
            phone = phone_entry(entry)
            if phone:
                digits = r"[\s-]?".join(phone)
                rules.append((re.compile(rf"(?<!\d){digits}(?!\d)"), self._phone(phone)))
            elif key := norm(entry):
                if key not in self.names:
                    self.names[key] = f"PARTY_{self._next:03d}"
                self._remember(key, self.names[key])
                rules.append((name_pattern(key), self.names[key]))
        return sorted(rules, key=lambda r: -len(r[0].pattern))

    def always_redact(self, body: str) -> tuple[str, int]:
        """Final pass: replace every always-redact entry anywhere. Returns (body, count)."""
        total = 0
        for rx, replacement in self._always:
            body, n = rx.subn(replacement, body)
            total += n
        return body, total

    def mask(self, body: str) -> str:
        """Fake refs, UPI IDs and phones; mask accounts; record names for pseudonymise()."""
        held: list[str] = []

        def ref(m: re.Match) -> str:
            value = m.group("ref")
            if sum(c.isdigit() for c in value) < 6:
                return m.group(0)
            i = m.start("ref") - m.start()
            self.seen_ids["ref"].add(id_digest(self.key, "ref", value.upper()))
            fake = _hold(held, self._fake("ref", value))
            return m.group(0)[:i] + fake + m.group(0)[i + len(value) :]

        def url(m: re.Match) -> str:
            rest = m["rest"] or ""
            return _hold(held, m["head"] + (self._fake("url", rest) if rest else ""))

        body = URL_RE.sub(url, body)
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

        Keep-listed phrases and bank wording are matched first and skipped, so
        "AMAZON PAY" or "HDFC Bank Card" survive even if a shorter name is mapped.
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
                    if key in self.keep or key in VOCAB:
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
        ids = {k: sorted(v) for k, v in self.seen_ids.items()}
        _save_text(self.seen_ids_path, json.dumps(ids))

    def _note_name(self, key: str) -> None:
        if key in self.keep:
            self.seen["names_kept"].add(key)
            return
        self.seen["names_pseudonymised"].add(key)
        if key not in self.names:
            self.names[key] = f"PARTY_{self._next:03d}"
            self._remember(key, self.names[key])

    def _remember(self, key: str, token: str) -> None:
        digits = token.rpartition("_")[2]
        if digits.isdigit():  # always, so a skipped entry's number is never reused
            self._next = max(self._next, int(digits) + 1)
        if not key or key in self.keep or name_key(key) != key:
            return  # keep-listed or bank wording since the map was written
        self._people[key] = token
        self._first_words.add(key.split()[0])

    def _upi(self, local: str, handle: str) -> str:
        if norm(local) in self.keep:
            self.seen["upi_kept"].add(local.lower())
            return f"{local}@{handle}"
        self.seen["upi_pseudonymised"].add(local.lower())
        self.seen_ids["upi"].add(id_digest(self.key, "upi", f"{local}@{handle}".lower()))
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
    always_hits = 0
    for msg in out:  # after the full pass, so a name found anywhere is replaced everywhere
        msg["body"], hits = redactor.always_redact(redactor.pseudonymise(msg["body"]))
        always_hits += hits

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
    # Entries share the name map, so the name sweep often replaces them first.
    print(f"Always-redact final-pass replacements: {always_hits:,}")
    print(f"Wrote {len(out):,} messages to {args.output}")


def verify(output: Path, private_dir: Path) -> int:
    """Scan a written sample for leaks. Prints tokens and positions only."""
    bodies = [m.get("body", "") for m in json.loads(output.read_text(encoding="utf-8"))]
    names = _load_json(private_dir / NAME_MAP_FILE)
    keep = load_keep(private_dir)
    leaks: set[tuple[int, str]] = set()  # (1-based message number, label)

    # a) always-redact entries, as substrings so joined words are caught too
    for n, entry in enumerate(load_always_redact(private_dir), 1):
        phone = phone_entry(entry)
        label = (None if phone else names.get(norm(entry))) or f"ALWAYS_REDACT_{n}"
        needle = phone or entry.lower()
        for i, body in enumerate(bodies, 1):
            hay = re.sub(r"[\s-]", "", body) if phone else body.lower()
            if needle in hay:
                leaks.add((i, label))

    # b) mapped names: 2+ words are leaks, single words only "possible"
    possible = 0
    for key, token in names.items():
        if not key or key in keep or name_key(key) != key:
            continue  # keep-listed or bank wording since the map was written
        rx = name_pattern(key)
        hits = [i for i, body in enumerate(bodies, 1) if rx.search(body)]
        if len(key.split()) >= 2:
            leaks.update((i, token) for i in hits)
        else:
            possible += len(hits)

    # c) real UPI IDs and references, compared by keyed digest
    key_path, seen = private_dir / KEY_FILE, _load_json(private_dir / SEEN_IDS_FILE)
    if key_path.exists() and seen:
        key = bytes.fromhex(key_path.read_text(encoding="utf-8").strip())
        upi, refs = set(seen.get("upi", [])), set(seen.get("ref", []))
        for i, body in enumerate(bodies, 1):
            for m in UPI_ID_RE.finditer(body):
                if id_digest(key, "upi", m.group(0).lower()) in upi:
                    leaks.add((i, "UPI_ID"))
            for cand in re.findall(r"\b[A-Za-z0-9]{6,22}\b", body):
                if sum(c.isdigit() for c in cand) < 6:
                    continue
                if id_digest(key, "ref", cand.upper()) in refs:
                    leaks.add((i, "REFERENCE"))

    for i, label in sorted(leaks):
        print(f"LEAK {label} in message {i}")
    print(f"possible (single word): {possible}")
    print(f"Leaks: {len(leaks)}")
    return 1 if leaks else 0


def resolve_inputs(inputs: list[Path]) -> list[Path]:
    """Files as given; folders expand to their *.xml files."""
    paths: list[Path] = []
    for p in inputs:
        paths.extend(sorted(p.glob("*.xml")) if p.is_dir() else [p])
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument(
        "--input", type=Path, nargs="+", help="XML files or folders (not with --verify alone)"
    )
    ap.add_argument("--private-dir", type=Path, required=True, help="name map, key, keep-lists")
    ap.add_argument("--output", type=Path, help="JSON sample to write (required unless listing)")
    ap.add_argument(
        "--verify", action="store_true", help="check --output for leaks; exit 1 if any are found"
    )
    ap.add_argument("--senders", default=DEFAULT_SENDERS, help="comma-separated sender IDs")
    ap.add_argument("--limit", type=int, help="random sample of N messages per sender")
    ap.add_argument("--seed", type=int, default=0, help="seed for --limit sampling")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--list-senders", action="store_true", help="sender IDs and counts only")
    mode.add_argument(
        "--list-counterparties", action="store_true", help="names and UPI IDs with counts only"
    )
    args = ap.parse_args(argv)
    listing = args.list_senders or args.list_counterparties
    if not (listing or args.output):
        ap.error("--output is required unless --list-senders or --list-counterparties is used")
    if listing and args.verify:
        ap.error("--verify checks a written --output; it cannot be combined with listing")
    if not args.input:
        if not args.verify:
            ap.error("--input is required unless --verify is used alone")
        if not args.output.exists():
            ap.error(f"--output {args.output} does not exist")
        return verify(args.output, args.private_dir)

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
    return verify(args.output, args.private_dir) if args.verify else 0


if __name__ == "__main__":
    sys.exit(main())
