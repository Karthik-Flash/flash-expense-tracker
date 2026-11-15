"""Command line: python -m app.cli <command>, run from backend/.

  import-sms --input <file|folder> [--dry-run]
  reparse [--dry-run]
  stats
  merchant-stats
  merchant-review [--kind] [--confidence] [--reason] [--direction] [--sample N]
  reconcile-stats

Uses DATABASE_URL (backend/.env or the environment). Prints counts, ids,
versions and timings only: never bodies, names, amounts, references or
account digits. One exception: merchant-review shows counterparty text for the
owner's own screen; it refuses to run unless stdout is a terminal.
"""

import argparse
import random
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.engine.merchant import MERCHANT_VERSION, channel_for, normalise_merchant, parts
from app.engine.reconcile import RECONCILE_VERSION, OwnerData, Txn, derive
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


def print_counter(title: str, counter: Counter) -> None:
    print(title)
    for key, n in sorted(counter.items()):
        line(key, n, 2)


def merchant_rows(session: Session):
    """(raw counterparty, merchant channel, debit|credit|refund, Merchant) per active txn."""
    rows = session.execute(
        select(
            Transaction.channel,
            Transaction.hints,
            Transaction.counterparty_raw,
            Transaction.direction,
            Transaction.type,
        ).where(Transaction.status == "active")
    )
    for channel, hints, raw, direction, txn_type in rows:
        merchant_channel = channel_for(channel, hints or ())
        flow = "refund" if txn_type == "refund" else direction
        yield raw, merchant_channel, flow, normalise_merchant(raw, merchant_channel)


def keys_covering(key_counts: Counter, share: float) -> int:
    """Fewest merchant keys that together hold `share` of the keyed transactions."""
    total, running = sum(key_counts.values()), 0
    for n_keys, (_, n) in enumerate(key_counts.most_common(), 1):
        running += n
        if running >= share * total:
            return n_keys
    return 0


def cmd_merchant_stats(session: Session, args: argparse.Namespace) -> None:
    """Run the merchant engine in memory over active transactions. Read-only, counts only."""
    examined = with_text = brand_hits = 0
    channel_kind, kind_conf, kind_flow, reasons, unsure, handles = (Counter() for _ in range(6))
    brands, key_counts, key_dirs, key_groups = set(), Counter(), defaultdict(set), set()
    for raw, channel, flow, m in merchant_rows(session):
        examined += 1
        with_text += bool(raw and raw.strip())
        channel_kind[f"{channel} {m.kind}"] += 1
        kind_conf[f"{m.kind} {m.confidence}"] += 1
        kind_flow[f"{flow} {m.kind}"] += 1
        reasons.update(m.reasons)
        if m.brand_id:
            brand_hits += 1
            brands.add(m.brand_id)
        if m.merchant_key:
            key_counts[m.merchant_key] += 1
            key_dirs[m.merchant_key].add("debit" if flow == "debit" else "credit")
            key_groups.add((f"{m.kind} {m.confidence}", m.merchant_key))
        p = parts(raw)
        if p and p.vpa:
            handles[p.vpa.partition("@")[2]] += 1
        if m.kind == "unsure" and p:
            unsure["vpa" if p.vpa else "name only"] += 1
            unsure["gateway prefix"] += p.gateway
            if not p.vpa:  # name shape; a UPI ID has no name tokens to count
                n = len(p.tokens)
                unsure[f"name tokens {n if n < 4 else '4+'}"] += 1
                unsure["name has digits"] += any(ch.isdigit() for w in p.tokens for ch in w)

    print(f"merchant-stats ({MERCHANT_VERSION}, read-only)")
    line("transactions examined", examined)
    line("with counterparty text", with_text, 2)
    line("without counterparty text", examined - with_text, 2)
    print_counter("channel by kind", channel_kind)
    print_counter("kind by confidence", kind_conf)
    print_counter("kind by direction", kind_flow)
    print_counter("reason codes", reasons)
    line("dictionary hits", brand_hits)
    line("distinct brands hit", len(brands))
    line("distinct merchant keys", len(key_counts))
    line("seen once", sum(n == 1 for n in key_counts.values()), 2)
    line("seen more than once", sum(n > 1 for n in key_counts.values()), 2)
    print_counter("distinct merchant keys by kind", Counter(g for g, _ in key_groups))
    print("keys covering the keyed transactions")
    for share in (0.5, 0.8, 0.95):
        line(f"{share:.0%}", keys_covering(key_counts, share), 2)
    line("keys with debit and credit", sum(len(d) == 2 for d in key_dirs.values()))
    print_counter("unsure", unsure)
    common = Counter({h: n for h, n in handles.items() if n >= 5})
    common["other"] = sum(n for n in handles.values() if n < 5)
    print_counter("UPI handles (5 or more; rest as other)", common)


PRIVATE = "PRIVATE: do not paste this into any chat or file."


def is_terminal() -> bool:
    return sys.stdout.isatty()


def cmd_merchant_review(session: Session, args: argparse.Namespace) -> int:
    """Owner only: one line per merchant key, with real counterparty text. Read-only."""
    if not is_terminal():
        print(
            "merchant-review shows real names and prints only to a terminal: "
            "run it in a console window, without a pipe or redirect.",
            file=sys.stderr,
        )
        return 2
    groups: dict[str, list] = {}
    for raw, _channel, flow, m in merchant_rows(session):
        if m.merchant_key is None or (args.direction and flow != args.direction):
            continue
        if (args.kind and m.kind != args.kind) or (
            args.confidence and m.confidence != args.confidence
        ):
            continue
        if args.reason and args.reason not in m.reasons:
            continue
        groups.setdefault(m.merchant_key, [raw, m, 0])[2] += 1
    keys = sorted(groups, key=lambda k: (-groups[k][2], k))
    if args.sample is not None:
        keys = sorted(random.Random(args.seed).sample(keys, min(args.sample, len(keys))))
    print(PRIVATE)
    for key in keys:
        raw, m, n = groups[key]
        print(
            f"{raw!r} | {m.display_name} | {key} | {m.kind} {m.confidence} | "
            f"{','.join(m.reasons)} | {n}"
        )
    print(f"{len(keys)} keys")
    print(PRIVATE)
    return 0


def reconcile_txns(session: Session) -> list[Txn]:
    """Active transactions as Reconcile input."""
    t = Transaction
    rows = session.execute(
        select(
            t.id,
            t.bank,
            t.type,
            t.direction,
            t.amount_paise,
            t.account_last4,
            t.channel,
            t.counterparty_raw,
            t.txn_time_utc,
            t.hints,
        ).where(t.status == "active")
    )
    return [Txn(*row[:9], tuple(row[9] or ())) for row in rows]


NO_INCOME_PARTY = (
    "warning: owner data lists no income party; "
    "pocket money or a salary from a person counts as a payback"
)


def cmd_reconcile_stats(session: Session, args: argparse.Namespace) -> None:
    """Run Reconcile in memory over active transactions. Read-only, counts only."""
    txns = reconcile_txns(session)
    owner = OwnerData()  # owner tables arrive in step 3C-4; until then every basis is engine
    derived = derive(txns, owner)
    by_direction, by_rule, paybacks = Counter(), Counter(), Counter(engine=0, owner=0)
    for t in txns:
        d = derived[t.id]
        by_direction[f"{t.direction} {d.role}"] += 1
        by_rule[d.rule] += 1
        if d.role == "payback":
            paybacks[d.basis] += 1
    unknown = dict(
        grouped(
            session,
            ParseResult.unknown_reason,
            where=(ParseResult.is_current, ParseResult.status == "unknown"),
        )
    )

    print(f"reconcile-stats ({RECONCILE_VERSION}, {MERCHANT_VERSION}, read-only)")
    line("transactions (active)", len(txns))
    print_counter("role by direction", by_direction)
    print_counter("role by rule", by_rule)
    line("matched by two or more rules", sum(len(d.reasons) > 1 for d in derived.values()))
    print_counter("paybacks by basis", paybacks)
    line("uncertain credits", sum(d.role == "uncertain" for d in derived.values()))
    print("not counted yet")
    line("foreign currency", unknown.get("foreign_currency_deferred", 0), 2)
    line("no parser", unknown.get("no_parser_for_bank", 0), 2)
    print("owner data")
    line("accounts", len(owner.accounts), 2)
    line("parties", len(owner.parties), 2)
    line("income sources", sum(p.income for p in owner.parties), 2)
    line("role decisions", len(owner.roles), 2)
    if not any(p.income for p in owner.parties):
        print(NO_INCOME_PARTY)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-sms", help="import an SMS Backup & Restore file or folder")
    imp.add_argument("--input", type=Path, required=True)
    imp.add_argument("--dry-run", action="store_true", help="run everything, save nothing")
    rep = sub.add_parser("reparse", help="re-parse messages behind their parser version")
    rep.add_argument("--dry-run", action="store_true")
    sub.add_parser("stats", help="counts per table, type, reason and batch")
    sub.add_parser("merchant-stats", help="merchant engine counts over transactions (read-only)")
    rev = sub.add_parser("merchant-review", help="owner only: merchants with real names")
    rev.add_argument("--kind", choices=("business", "person", "unsure"))
    rev.add_argument("--confidence", choices=("high", "low"))
    rev.add_argument("--reason", help="only results with this reason code")
    rev.add_argument("--direction", choices=("debit", "credit", "refund"))
    rev.add_argument("--sample", type=int, metavar="N", help="random N merchant keys")
    rev.add_argument("--seed", type=int, default=0, help="seed for --sample")
    sub.add_parser("reconcile-stats", help="role counts over transactions (read-only)")
    return parser


COMMANDS = {
    "import-sms": cmd_import,
    "reparse": cmd_reparse,
    "stats": cmd_stats,
    "merchant-stats": cmd_merchant_stats,
    "merchant-review": cmd_merchant_review,
    "reconcile-stats": cmd_reconcile_stats,
}


def main(argv: list[str] | None = None, session_factory=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "import-sms" and not args.input.exists():
        print("input not found", file=sys.stderr)
        return 2
    if session_factory is None:
        from app.db import SessionLocal as session_factory
    with session_factory() as session:
        return COMMANDS[args.command](session, args) or 0


if __name__ == "__main__":
    sys.exit(main())
