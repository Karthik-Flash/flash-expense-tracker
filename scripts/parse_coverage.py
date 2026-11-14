"""Run the parsing engine over a redacted sample and print counts only.

Never prints a message body. Unknown messages are shown by SHAPE (fixed
wording plus placeholders, see shape_survey.py).

  python scripts/parse_coverage.py --input data/sample/redacted_sample.json
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from shape_survey import shape_id, shape_of  # noqa: E402

from app.engine import ParsedMessage, parse_message  # noqa: E402


def coverage(messages: list[dict]) -> dict[str, Counter]:
    c = {k: Counter() for k in ("sender", "type", "template", "unknown", "unknown_shape")}
    c["total"] = Counter()
    for m in messages:
        result = parse_message(m["sender"], m["body"], datetime.fromisoformat(m["date_utc"]))
        c["total"]["messages"] += 1
        c["sender"][m["sender"]] += 1
        if isinstance(result, ParsedMessage):
            c["total"]["parsed"] += 1
            c["total"]["is_money"] += result.is_money
            c["type"][result.type] += 1
            c["template"][f"{result.bank} {result.template_id}"] += 1
        else:
            c["unknown"][result.reason] += 1
            if result.reason != "no_parser_for_bank":  # those are expected, not a gap
                shape = shape_of(m["body"])
                c["unknown_shape"][(result.reason, shape_id(shape), shape)] += 1
    return c


def report(c: dict[str, Counter]) -> None:
    t = c["total"]
    print(f"Messages: {t['messages']:,}  parsed: {t['parsed']:,}  is_money: {t['is_money']:,}")
    for title, key in (
        ("Per sender", "sender"),
        ("Per type", "type"),
        ("Per template", "template"),
    ):
        print(f"\n{title}:")
        for name, n in sorted(c[key].items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {name:<28}{n:>8,}")
    print("\nUnknown by reason:")
    for name, n in c["unknown"].most_common():
        print(f"  {name:<28}{n:>8,}")
    if c["unknown_shape"]:
        print("\nUnknown shapes (excluding banks without a parser):")
        for (reason, sid, shape), n in c["unknown_shape"].most_common():
            print(f"  {n:>5}  {reason}  {sid}")
            for line in shape.split("\n"):
                print(f"         {line}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--input", type=Path, required=True, help="redacted sample JSON")
    args = ap.parse_args(argv)
    report(coverage(json.loads(args.input.read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
