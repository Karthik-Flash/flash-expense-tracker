"""Group redacted SMS into template SHAPES for parser design.

Each body becomes a shape by replacing variable parts with placeholders:
{URL} {REF} {VPA} {DATE} {TIME} {BAL} {CURRENCY} {AMOUNT} {PHONE} {ACCT}
{PARTY} {NUM}. Messages with the same shape are grouped and counted.

Reads only the redacted sample. Standard library only; works for any bank.

  python scripts/shape_survey.py --input data/sample/redacted_sample.json \
      --senders HDFCBK,HDFCBN --output data/sample/hdfc_shapes.json
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

RUPEE = chr(0x20B9)
CUR = rf"(?:Rs\.?|INR\.?|{RUPEE})"
MONEY = r"\d[\d,]*(?:\.\d+)?"
MONTHS = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"

# Applied in order; each rule sees the output of the previous ones. When a
# pattern has a group named "v", only that group is replaced (keyword kept).
RULES: list[tuple[str, re.Pattern[str]]] = [
    ("{URL}", re.compile(r"\b[\w.+-]+://\S+|\bwww\.\S+", re.I)),
    # Reference-like value after a keyword; it must contain a digit.
    (
        "{REF}",
        re.compile(
            r"\b(?:Ref|RRN|UTR|UPI|IMPS|NEFT|UMN|ID)(?:\s*No\.?)?\s*[:.]?\s*"
            r"(?P<v>(?=[\w@.-]*\d)[\w@.-]*[\w@-])",  # never ends on "."
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
    # Counterparty text after a capitalised keyword, up to the next field.
    # Not after "? " ("Not You? To Block+Reissue ..." is fixed bank wording).
    (
        "{PARTY}",
        re.compile(
            r"(?<!\? )\b(?:To|At|For|By) (?P<v>[^\n]+?)"
            r"(?=\s*(?:\n|$| On | on | via | Via | Bal | Not ))"
        ),
    ),
    ("{NUM}", re.compile(r"\d+(?:\.\d+)?")),
]


def _apply(placeholder: str, rx: re.Pattern[str], text: str) -> str:
    """Replace the whole match, or only group "v" when the pattern has one."""
    if "v" not in rx.groupindex:
        return rx.sub(placeholder, text)

    def repl(m: re.Match[str]) -> str:
        a, b = m.start("v") - m.start(), m.end("v") - m.start()
        return m.group(0)[:a] + placeholder + m.group(0)[b:]

    return rx.sub(repl, text)


def shape_of(body: str) -> str:
    for placeholder, rx in RULES:
        body = _apply(placeholder, rx, body)
    lines = (" ".join(line.split()) for line in body.strip().split("\n"))
    return "\n".join(lines)


def shape_id(shape: str) -> str:
    return "sh_" + hashlib.sha1(shape.encode("utf-8")).hexdigest()[:8]


def survey(messages: list[dict], senders: set[str]) -> list[dict]:
    counts: Counter = Counter()
    seen_senders: dict[str, set[str]] = defaultdict(set)
    for m in messages:
        if m.get("sender") in senders:
            s = shape_of(m.get("body", ""))
            counts[s] += 1
            seen_senders[s].add(m["sender"])
    return [
        {"id": shape_id(s), "count": n, "senders": sorted(seen_senders[s]), "shape": s}
        for s, n in counts.most_common()
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--input", type=Path, required=True, help="redacted sample JSON")
    ap.add_argument("--senders", required=True, help="comma-separated sender cores")
    ap.add_argument("--output", type=Path, required=True, help="report JSON to write")
    args = ap.parse_args(argv)

    messages = json.loads(args.input.read_text(encoding="utf-8"))
    senders = {s.strip().upper() for s in args.senders.split(",") if s.strip()}
    report = survey(messages, senders)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    total = sum(r["count"] for r in report)
    print(f"{total:,} messages, {len(report)} shapes -> {args.output}")
    for r in report:
        print(f"{r['id']}  {r['count']:>5}  {','.join(r['senders'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
