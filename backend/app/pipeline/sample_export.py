"""A redacted sample of one bank's messages, for writing its parser (D-100).

Same idea as the Phase 1 sample (scripts/redact_sms.py, scripts/shape_survey.py): values
become shape tokens and redaction is default-deny.
  1. The shape rules of scripts/shape_survey.py (a test keeps them equal) turn URLs,
     references, UPI IDs, dates, times, balances, amounts, phone numbers, account and card
     digits, counterparty slots and every other number into {URL} {REF} {VPA} {DATE} {TIME}
     {BAL} {AMOUNT} {PHONE} {ACCT} {PARTY} {NUM}.
  2. Every word left that is not in the bank-wording vocabulary below becomes {WORD}: a
     name in an unknown place is never kept.
  3. A leak scan reads every line again and refuses the whole file when a line still has a
     run of 4 or more digits, an @ handle, or a capitalised word outside the vocabulary.
Equal shapes are written once, with their count, kind and parse status; never a message
time, never an original value. The file goes to the owner's private folder (never into the
repository). Only `--approve` copies it into the repo's local, git-ignored data/sample/.
"""

import re
import shutil
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.engine.parsers import generic
from app.pipeline.survey import _rows, family_of, status_of

REPO = Path(__file__).resolve().parents[3]
SAMPLE_DIR = REPO / "data" / "sample"  # git-ignored: data/ is never committed
RUPEE = chr(0x20B9)
CUR = rf"(?:Rs\.?|INR\.?|{RUPEE})"
MONEY = r"\d[\d,]*(?:\.\d+)?"
MONTHS = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
# The rules of scripts/shape_survey.py, in the same order (tests/test_survey.py checks it).
RULES: list[tuple[str, re.Pattern[str]]] = [
    ("{URL}", re.compile(r"\b[\w.+-]+://\S+|\bwww\.\S+", re.I)),
    (
        "{REF}",
        re.compile(
            r"\b(?:Ref|RRN|UTR|UPI|IMPS|NEFT|UMN|ID)(?:\s*No\.?)?\s*[:.]?\s*"
            r"(?P<v>(?=[\w@.-]*\d)[\w@.-]*[\w@-])",
            re.I,
        ),
    ),
    ("{VPA}", re.compile(r"\*?[\w.\-]+@[a-zA-Z][a-zA-Z0-9]+")),
    ("{DATE}", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    ("{DATE}", re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b")),
    ("{DATE}", re.compile(rf"\b\d{{1,2}}[- ]?(?:{MONTHS})[A-Z]*[- ,]?\d{{2,4}}\b", re.I)),
    ("{TIME}", re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")),
    ("{BAL}", re.compile(rf"\b(?:Avl )?Bal(?:ance)?:?\s*(?P<v>{CUR}\s?{MONEY})", re.I)),
    ("{CURRENCY} {AMOUNT}", re.compile(rf"\b(?:USD|EUR|GBP|AED|SGD|AUD|CAD|JPY|CHF)\s?{MONEY}")),
    ("{AMOUNT}", re.compile(rf"{CUR}\s?{MONEY}", re.I)),
    ("{PHONE}", re.compile(r"\bCall\s+(?P<v>X+\d{4})")),
    ("{PHONE}", re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")),
    ("{ACCT}", re.compile(r"(?<![\w*])[Xx*]+\d{3,4}\b")),
    ("{ACCT}", re.compile(r"\b(?:DC|Card)\s+(?P<v>\d{4})\b")),
    ("{PARTY}", re.compile(r"\b(?:PARTY|PERSON)_\w*")),
    (
        "{PARTY}",
        re.compile(
            r"(?<!\? )\b(?:To|At|For|By) (?P<v>[^\n]+?)"
            r"(?=\s*(?:\n|$| On | on | via | Via | Bal | Not ))"
        ),
    ),
    ("{NUM}", re.compile(r"\d+(?:\.\d+)?")),
]

# Bank-alert wording kept as it is (any case). Anything else is {WORD}. Words only: names
# of people never belong here; public bank names and fixed wording do.
VOCABULARY = frozenset(
    """
    a ac acct account accounts active added address advice after against alert alerts all
    allowed amount amt an and any app apply approved are as at atm auto autopay available
    avl axis bal balance bank banking be been beneficiary bill biller blocked block bob
    by c call can canara cancelled card cards cash cashback charge charges cheque clear
    cleared click code collect completed contact cr credit credited cust customer cvv date
    dated day days dear debit debited deducted deposit deposited details device did dispute
    do does done dr due e ecs emi enquiry end ending enter expire expires expiry failed fd
    federal for fraud from fund funds gateway get has have help helpline hdfc icici id
    idfc if immediately imps in inb indusind info initiated instant insufficient interest
    into is it its kotak kyc limit link linked lmt loan login made mandate merchant message
    mins minimum mobile money month monthly neft net netbanking new no not now of on
    online or otp our own paid pay payee payment payments pending per pin please pls pnb
    pos pre pvt quote rbl received recharge ref refno refund registered reject rejected
    reply report request requested reversed rrn rs rtgs sb sbi scheduled secure sent
    service share sms spent standing statement status successful successfully thank
    thanks the this through thru time to total towards transaction transactions transfer
    transferred trf txn u union unsuccessful upi ur use used user using utr valid value
    via vpa wallet was we will with withdrawal withdrawn yes yono you your
    jan feb mar apr may jun jul aug sep oct nov dec
    """.split()
)
WORD = re.compile(r"[A-Za-z][A-Za-z']*")
TOKEN = re.compile(r"\{[A-Z]+\}")
HEADER = re.compile(  # the only "#" lines the tool writes
    r"# [A-Z0-9_]+ sample(?:, unread messages only)?: \d+ messages, \d+ shapes\. "
    r"Values are shape tokens; words outside "
    r"the bank vocabulary are \{WORD\}\."
    r"|## \d+ \| \d+ messages? \| kind [a-z_]+ \| (?:dedicated|generic|not parsed)"
)
DIGITS = re.compile(r"\d{4,}")
HANDLE = re.compile(r"@\w")
LEAK_REASONS = ("4+ digits", "@ handle", "capitalised word")


def shape_of(body: str) -> str:
    for placeholder, rx in RULES:
        if "v" not in rx.groupindex:
            body = rx.sub(placeholder, body)
            continue

        def repl(m: re.Match[str], placeholder: str = placeholder) -> str:
            a, b = m.start("v") - m.start(), m.end("v") - m.start()
            return m.group(0)[:a] + placeholder + m.group(0)[b:]

        body = rx.sub(repl, body)
    return "\n".join(" ".join(line.split()) for line in body.strip().split("\n"))


def redact(body: str, kept: Counter) -> tuple[str, int]:
    """(shape with every non-vocabulary word as {WORD}, how many words were replaced).
    Words inside the shape tokens are left alone; `kept` counts the vocabulary words."""
    replaced = 0

    def word(m: re.Match[str]) -> str:
        nonlocal replaced
        if (w := m.group(0)).lower() in VOCABULARY:
            kept[w.lower()] += 1
            return w
        replaced += 1
        return "{WORD}"

    shape = shape_of(body)
    parts, tokens = TOKEN.split(shape), TOKEN.findall(shape)
    text = "".join(WORD.sub(word, p) + t for p, t in zip(parts, [*tokens, ""], strict=True))
    return text, replaced


def leak_scan(text: str) -> tuple[Counter, list[str]]:
    """Counts per reason, and the offending lines (PRIVATE: shown on screen only)."""
    reasons: Counter = Counter()
    lines = []
    for line in text.split("\n"):
        if line.startswith("#"):
            if not HEADER.fullmatch(line):
                reasons["capitalised word"] += 1  # a header the tool did not write
                lines.append(line)
            continue
        bare = TOKEN.sub(" ", line)
        found = [
            reason
            for reason, hit in (
                ("4+ digits", DIGITS.search(bare)),
                ("@ handle", HANDLE.search(bare)),
                (
                    "capitalised word",
                    any(w[0].isupper() and w.lower() not in VOCABULARY for w in WORD.findall(bare)),
                ),
            )  # fmt: skip
            if hit
        ]
        reasons.update(found)
        if found:
            lines.append(line)
    return reasons, lines


@dataclass
class Export:
    family: str
    messages: int = 0
    shapes: list[tuple[str, int, str, str]] = field(default_factory=list)  # shape, n, kind, st
    kept: Counter = field(default_factory=Counter)
    replaced: int = 0
    unparsed: bool = False  # only the messages no parser read (4Z)

    @property
    def name(self) -> str:
        """The file name's family: "hdfc", or "hdfc-unparsed"."""
        return f"{self.family.lower()}-unparsed" if self.unparsed else self.family.lower()

    def text(self) -> str:
        which = " sample, unread messages only" if self.unparsed else " sample"
        head = (
            f"# {self.family}{which}: {self.messages} messages, {len(self.shapes)} shapes. "
            "Values are shape tokens; words outside the bank vocabulary are {WORD}."
        )
        blocks = [head]
        for n, (shape, count, kind, status) in enumerate(self.shapes, 1):
            noun = "message" if count == 1 else "messages"
            blocks.append(f"## {n} | {count} {noun} | kind {kind} | {status}\n{shape}")
        return "\n\n".join(blocks) + "\n"

    def vocabulary(self) -> str:
        rows = [f"{word} {n}" for word, n in sorted(self.kept.items(), key=lambda x: (-x[1], x[0]))]
        return "\n".join([
            f"# {self.family}: template words kept (word, count). Check that none is a name.",
            *rows,
            f"# words replaced by {{WORD}}: {self.replaced}",
        ]) + "\n"  # fmt: skip


UNPARSED = "-UNPARSED"


def build(session: Session, owner_id: uuid.UUID, family: str, unparsed: bool = False) -> Export:
    """`unparsed` (4Z): only the messages no parser read, as family "<BANK>-UNPARSED", so a
    missing template can be added from an approved sample (never guessed without one)."""
    family = family.upper().removesuffix(UNPARSED)
    export = Export(family, unparsed=unparsed)
    counts: Counter = Counter()
    for core, body, _, status, version in _rows(session, owner_id):
        if family_of(core) != family or (unparsed and status == "parsed"):
            continue
        export.messages += 1
        shape, replaced = redact(body, export.kept)
        export.replaced += replaced
        counts[(shape, generic.kind_of(body), status_of(status, version))] += 1
    export.shapes = [
        (shape, n, kind, status)
        for (shape, kind, status), n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    ]
    return export


def inside_repo(path: Path) -> bool:
    return path.resolve().is_relative_to(REPO)


def sample_name(family: str) -> str:
    return f"{family.lower()}-sample.txt"


def write(export: Export, review_dir: Path) -> tuple[Counter, list[str], Path | None]:
    """Scan, then write the sample and its vocabulary report, or refuse and write nothing."""
    text = export.text()
    reasons, lines = leak_scan(text)
    if reasons or inside_repo(review_dir):
        return reasons, lines, None
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / sample_name(export.name)
    path.write_text(text, encoding="utf-8")
    (review_dir / f"{export.name}-vocabulary.txt").write_text(export.vocabulary(), encoding="utf-8")
    return reasons, lines, path


def approve(family: str, review_dir: Path, sample_dir: Path | None = None):
    """Scan the reviewed file again; when clean, copy it to the repo's data/sample/."""
    sample_dir = sample_dir or SAMPLE_DIR
    source = review_dir / sample_name(family)
    if not source.exists():
        return None, [], None
    reasons, lines = leak_scan(source.read_text(encoding="utf-8"))
    if reasons:
        return reasons, lines, None
    sample_dir.mkdir(parents=True, exist_ok=True)
    target = sample_dir / sample_name(family)
    shutil.copyfile(source, target)
    return reasons, lines, target
