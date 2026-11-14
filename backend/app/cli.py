"""Command line: python -m app.cli <command>, run from backend/.

  import-sms --input <file|folder> [--dry-run]
  reparse [--dry-run]
  stats

Uses DATABASE_URL (backend/.env or the environment). Prints counts, ids,
versions and timings only: never bodies, names, amounts, references or
account digits.
"""

import argparse
import sys
import time
from collections.abc import Callable
from datetime import timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.importers.sms_backup import import_sms
from app.models import (
    DuplicateCandidate,
    ImportBatch,
    ParseResult,
    RawMessage,
    Transaction,
    TransactionSource,
)
from app.pipeline.reparse import reparse
from app.pipeline.store import Counts, parser_versions

IST = timezone(timedelta(hours=5, minutes=30))
TABLES = (ImportBatch, RawMessage, ParseResult, Transaction, TransactionSource, DuplicateCandidate)


def line(label: str, value: object, indent: int = 0) -> None:
    print(f"{' ' * indent}{label:<{32 - indent}}{value:>10}")


def print_counts(counts: Counts) -> None:
    c = counts.as_dict()
    for key, value in c.items():
        if isinstance(value, dict):
            print(key)
            for sub, n in value.items():
                line(sub, n, 2)
        else:
            line(key, value)


def progress(started: float) -> Callable[[int], None]:
    def report(n: int) -> None:
        print(f"  ... {n:,} messages, {time.monotonic() - started:.1f}s", file=sys.stderr)

    return report


def cmd_import(session: Session, args: argparse.Namespace) -> None:
    started = time.monotonic()
    batch_id, counts = import_sms(
        session, args.input, settings.owner_id, dry_run=args.dry_run, progress=progress(started)
    )
    title = (
        "import-sms (dry run: nothing saved)" if args.dry_run else f"import-sms batch {batch_id}"
    )
    print(title)
    print("parser versions: " + ", ".join(f"{b} {v}" for b, v in parser_versions().items()))
    print_counts(counts)
    print(f"time: {time.monotonic() - started:.1f}s")


def cmd_reparse(session: Session, args: argparse.Namespace) -> None:
    started = time.monotonic()
    counts = reparse(session, settings.owner_id, dry_run=args.dry_run, progress=progress(started))
    print("reparse (dry run: nothing saved)" if args.dry_run else "reparse")
    print("parser versions: " + ", ".join(f"{b} {v}" for b, v in parser_versions().items()))
    c = counts.as_dict()
    for key in ("reparsed", "parsed", "unknown", "is_money", "transactions", "candidates"):
        value = c[key]
        if isinstance(value, dict):
            print(key)
            for sub, n in value.items():
                line(sub, n, 2)
        else:
            line(key, value)
    print(f"time: {time.monotonic() - started:.1f}s")


def grouped(session: Session, *columns, where=()) -> list[tuple]:
    query = select(*columns, func.count()).where(*where).group_by(*columns).order_by(*columns)
    return list(session.execute(query))


def cmd_stats(session: Session, args: argparse.Namespace) -> None:
    print("tables")
    for model in TABLES:
        line(model.__tablename__, session.scalar(select(func.count()).select_from(model)), 2)

    print("transactions by type and direction (active)")
    active = (Transaction.status == "active",)
    for kind, direction, n in grouped(
        session, Transaction.type, Transaction.direction, where=active
    ):
        line(f"{kind} {direction}", n, 2)

    current = (ParseResult.is_current,)
    print("parse results by type (current)")
    for kind, n in grouped(
        session, ParseResult.type, where=(*current, ParseResult.type.is_not(None))
    ):
        line(kind, n, 2)
    print("unknown queue by reason (current)")
    unknown = (*current, ParseResult.status == "unknown")
    for reason, n in grouped(session, ParseResult.unknown_reason, where=unknown):
        line(reason, n, 2)

    open_pairs = select(func.count()).where(DuplicateCandidate.status == "open")
    line("open duplicate candidates", session.scalar(open_pairs))

    first, last = session.execute(
        select(func.min(Transaction.txn_time_utc), func.max(Transaction.txn_time_utc))
    ).one()
    span = f"{first.astimezone(IST):%Y-%m} .. {last.astimezone(IST):%Y-%m}" if first else "-"
    line("months (IST)", span)

    print("last import batches")
    batches = session.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(3))
    for b in batches:
        raw = (b.counts or {}).get("raw", {})
        print(
            f"  #{b.id} {b.status:<8} {b.started_at:%Y-%m-%d %H:%M} UTC  "
            f"read {(b.counts or {}).get('read', 0)}  raw new {raw.get('new', 0)}  "
            f"duplicate {raw.get('duplicate', 0)}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-sms", help="import an SMS Backup & Restore file or folder")
    imp.add_argument("--input", type=Path, required=True)
    imp.add_argument("--dry-run", action="store_true", help="run everything, save nothing")
    rep = sub.add_parser("reparse", help="re-parse messages behind their parser version")
    rep.add_argument("--dry-run", action="store_true")
    sub.add_parser("stats", help="counts per table, type, reason and batch")
    return parser


COMMANDS = {"import-sms": cmd_import, "reparse": cmd_reparse, "stats": cmd_stats}


def main(argv: list[str] | None = None, session_factory=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "import-sms" and not args.input.exists():
        print("input not found", file=sys.stderr)
        return 2
    if session_factory is None:
        from app.db import SessionLocal as session_factory
    with session_factory() as session:
        COMMANDS[args.command](session, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
