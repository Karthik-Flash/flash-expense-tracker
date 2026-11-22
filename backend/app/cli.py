"""Command line: python -m app.cli <command>, run from backend/.

  import-sms --input <file|folder> [--dry-run]
  reparse [--dry-run]
  stats
  merchant-stats
  merchant-review [--kind] [--confidence] [--reason] [--direction] [--sample N]
  reconcile-stats
  owner-load <file> [--dry-run]
  recompute [--dry-run] [--accept-key-changes]
  reconcile-review [--list]
  owner-export <file>
  totals --month YYYY-MM
  category-stats
  category-review [--uncategorised] [--list]
  credit-review [--list]
  payback-audit [--fix [--apply] | --restore [--apply]]
  bank-survey
  generic-preview
  redact-sample --family <bank> [--unparsed] [--review-dir DIR]
  redact-sample --approve <bank> [--review-dir DIR]
  statement-check --file <path> [--file <path> ...] [--details]
  statement-names --file <path> [--file <path> ...] [--show | --apply]
  statement-import --file <path> [--file <path> ...] [--apply]
  sender-survey --contains <text> [--input <file|folder>]
  auth-cleanup
  category-diff --out <file.csv>     (5B-1: outside the repository; the CSV is PRIVATE)
  payback-review --out <file.csv>

Every command works on one owner's data: --owner <owner_id> (before the command), else the
admin in app_users (5C, D-130), else OWNER_ID.

Uses DATABASE_URL (backend/.env or the environment). Prints counts, ids,
versions and timings only: never bodies, names, amounts, references or
account digits. One exception: merchant-review shows counterparty text for the
owner's own screen; it refuses to run unless stdout is a terminal, and so do
reconcile-review and totals. owner-load
reads the owner's private file and reports problems by field path, never by value.
import-sms, reparse and owner-load end with a recompute of the derived tables.
"""

import argparse
import csv
import json
import random
import sys
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import supabase_admin
from app.config import settings
from app.engine import statement_check, statement_hdfc
from app.engine.categorise import CATEGORIES, CATEGORISE_VERSION, SPENDING_ROLES, UNCATEGORISED
from app.engine.merchant import MERCHANT_VERSION, channel_for, normalise_merchant, parts
from app.engine.money import format_inr
from app.engine.reconcile import (
    COUNTED,
    DUP_LINK_WINDOW,
    LINK_KINDS,
    RECONCILE_VERSION,
    ROLES,
    Result,
    Txn,
    inferred_accounts,
    ist_month,
)
from app.engine.senders import SENDER_BANKS
from app.importers.sms_backup import import_sms, input_files
from app.models import (
    AppUser,
    AuthDeletion,
    DeriveRun,
    DuplicateCandidate,
    ImportBatch,
    Label,
    OwnAccount,
    OwnerCategory,
    OwnerLinkDecision,
    OwnerRole,
    OwnIdentifier,
    ParseResult,
    Party,
    PartyText,
    RawMessage,
    Transaction,
    TransactionSource,
    TxnDerived,
    TxnLabel,
    TxnLink,
)
from app.pipeline import account, payback_audit, review, sample_export, statement, survey
from app.pipeline.owner_actions import ActionError, answer_sender, senders
from app.pipeline.owner_load import (
    OwnerFileError,
    export_owner,
    parse_owner_file,
    restore,
    sync,
)
from app.pipeline.recompute import (
    VERSIONS,
    OwnerDataError,
    Plan,
    active_txns,
    load_owner,
    plan,
    recompute,
    run_counts,
    stale_reason,
)
from app.pipeline.reparse import reparse
from app.pipeline.store import Counts, parser_versions

IST = timezone(timedelta(hours=5, minutes=30))
TABLES = (
    ImportBatch,
    RawMessage,
    ParseResult,
    Transaction,
    TransactionSource,
    DuplicateCandidate,
    OwnAccount,
    OwnIdentifier,
    Party,
    PartyText,
    OwnerLinkDecision,
    OwnerRole,
    OwnerCategory,
    Label,
    TxnLabel,
    DeriveRun,
    TxnDerived,
    TxnLink,
)


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


def cmd_import(session: Session, args: argparse.Namespace) -> int:
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
    return 0 if args.dry_run else run_recompute(session, "import")


def cmd_reparse(session: Session, args: argparse.Namespace) -> int:
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
    return 0 if args.dry_run else run_recompute(session, "reparse")


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
# Role rules that come from a link or an owner decision, not from one message.
LINK_OR_OWNER_RULES = frozenset(
    {"OWNER_role", "OWNER_link", "DUP_autopay_card", "ST_reference", "ST_pair"}
)


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


def autopay_card_counts(txns: list[Txn], result: Result) -> tuple[Counter, Counter]:
    """AutoPay + card spend pairs (linked or candidate): by time gap, and merchant facts."""
    by_id = {t.id: t for t in txns}
    gaps = Counter({"up to 10 min": 0, "10-60 min": 0, "1-24 h": 0})
    facts = Counter(
        dict.fromkeys(
            (
                "same merchant key",
                "brand on both",
                "brand on autopay only",
                "brand on card only",
                "brand on neither",
                "earlier message is autopay",
                "earlier message is card",
            ),
            0,
        )
    )
    for link in result.links:
        if link.rule != "DUP_autopay_card":
            continue
        a, b = by_id[link.txn_a], by_id[link.txn_b]
        autopay, card = (a, b) if a.channel == "e_mandate" else (b, a)
        gap = abs(a.txn_time_utc - b.txn_time_utc)
        hour = timedelta(hours=1)
        gaps[
            "up to 10 min" if gap <= DUP_LINK_WINDOW else "10-60 min" if gap <= hour else "1-24 h"
        ] += 1
        ma, mc = (
            normalise_merchant(t.counterparty_raw, channel_for(t.channel, t.hints))
            for t in (autopay, card)
        )
        facts["same merchant key"] += ma.merchant_key == mc.merchant_key
        brand = {
            (True, True): "both",
            (True, False): "autopay only",
            (False, True): "card only",
            (False, False): "neither",
        }[bool(ma.brand_id), bool(mc.brand_id)]
        facts[f"brand on {brand}"] += 1
        first = min(autopay, card, key=lambda t: (t.txn_time_utc, t.id))
        facts["earlier message is autopay" if first is autopay else "earlier message is card"] += 1
    return gaps, facts


def legacy_counts(legacy: set[tuple[int, int]], txns: list[Txn], owner, result: Result):
    """What became of each pair recorded in duplicate_candidates. "lost" must be 0."""
    active = {t.id for t in txns}
    links = {(x.txn_a, x.txn_b): x.status for x in result.links if x.kind == "duplicate"}
    counts = dict.fromkeys(
        ("linked", "still candidate", "decided different", "not active", "lost"), 0
    )
    for pair in legacy:
        if not set(pair) <= active:
            counts["not active"] += 1
        elif owner.links.get(("duplicate", *pair)) == "different":
            counts["decided different"] += 1
        elif pair in links:
            counts["linked" if links[pair] == "linked" else "still candidate"] += 1
        else:
            counts["lost"] += 1
    return counts


NO_INCOME_PARTY = (
    "warning: owner data lists no income party; "
    "credits from people stay To confirm until you answer them (credit-review)"
)


def run_recompute(
    session: Session, trigger: str, *, dry_run: bool = False, accept: bool = False
) -> int:
    """Recompute the derived tables and print counts only. A failure writes nothing derived."""
    try:
        outcome = recompute(
            session, settings.owner_id, trigger, dry_run=dry_run, accept_key_changes=accept
        )
    except Exception as exc:
        # Only the engine's own message is shown; any other could hold values from the data.
        reason = str(exc) if isinstance(exc, OwnerDataError) else type(exc).__name__
        print(f"recompute failed: {reason}. No derived data was written.", file=sys.stderr)
        if trigger != "manual":
            print(
                f"The {trigger} step itself is saved. Fix the cause, then run: "
                "python -m app.cli recompute",
                file=sys.stderr,
            )
        return 1
    p = outcome.plan
    print(
        {
            "done": f"recompute run #{outcome.run_id} ({trigger})",
            "unchanged": "recompute: nothing to change, nothing written",
            "dry_run": "recompute (dry run: nothing saved)",
            "stopped": "recompute stopped: nothing written",
        }[outcome.status]
    )
    print("versions: " + ", ".join(VERSIONS.values()))
    line("transactions (active)", len(p.txns))
    counts = run_counts(p)
    for table in ("txn_derived", "txn_links"):
        print(table)
        for what, n in counts[table].items():
            line(what, n, 2)
    print_counter("roles", Counter(counts["roles"]))
    print_counter("links", Counter(counts["links"]))
    if not any(party.income for party in p.owner.parties):
        print(NO_INCOME_PARTY)
    print(f"time: {outcome.seconds:.1f}s")
    if outcome.status == "stopped":
        print(
            f"The merchant engine changed ({(p.last_versions or {}).get('merchant')} -> "
            f"{MERCHANT_VERSION}) and {p.lost_matches} transaction(s) would lose or change "
            "their owner match. Check the owner file, then run: "
            "python -m app.cli recompute --accept-key-changes",
            file=sys.stderr,
        )
        return 3
    return 0


def cmd_recompute(session: Session, args: argparse.Namespace) -> int:
    return run_recompute(session, "manual", dry_run=args.dry_run, accept=args.accept_key_changes)


def stored_run_lines(p: Plan) -> None:
    """The last recompute and how far the stored rows are from a fresh derive."""
    print("stored run")
    line("last run", f"#{p.last_run_id}" if p.last_run_id else "none", 2)
    for name in VERSIONS:
        line(f"{name} version", (p.last_versions or {}).get(name, "-"), 2)
    line("stored rows that differ", p.changes, 2)


def cmd_reconcile_stats(session: Session, args: argparse.Namespace) -> int:
    """Run Reconcile in memory over active transactions. Read-only, counts only."""
    try:
        p = plan(session, settings.owner_id)
    except OwnerDataError as exc:
        print(f"reconcile-stats failed: {exc}", file=sys.stderr)
        return 1
    txns, owner, legacy, result = p.txns, p.owner, p.legacy, p.result
    derived = result.roles
    by_direction, by_rule = Counter({"debit duplicate": 0}), Counter()
    paybacks = Counter(engine=0, owner=0)
    by_status = Counter(
        dict.fromkeys((f"{k} {s}" for k in LINK_KINDS for s in ("linked", "candidate")), 0)
    )
    by_status.update(f"{x.kind} {x.status}" for x in result.links)
    by_reason = Counter(f"{x.kind} {x.reason}" for x in result.links if x.status == "candidate")
    gaps, facts = autopay_card_counts(txns, result)
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
    several = [d for d in derived.values() if len(d.reasons) > 1]
    over = sum(d.rule in LINK_OR_OWNER_RULES for d in several)
    line("matched by two or more rules", len(several))
    line("one-message rules agree", len(several) - over, 2)
    line("a link or decision overrides", over, 2)
    print_counter("paybacks by basis", paybacks)
    line("uncertain credits", sum(d.role == "uncertain" for d in derived.values()))
    print_counter("links by kind and status", by_status)
    print_counter("candidates by kind and reason", by_reason)
    print("autopay and card pairs by time gap")
    for label, n in gaps.items():
        line(label, n, 2)
    print("autopay and card pairs, merchant")
    for label, n in facts.items():
        line(label, n, 2)
    print("existing candidates")
    line("recorded", len(legacy), 2)
    for label, n in legacy_counts(legacy, txns, owner, result).items():
        line(label, n, 2)
    print("not counted yet")
    line("foreign currency", unknown.get("foreign_currency_deferred", 0), 2)
    line("no parser", unknown.get("no_parser_for_bank", 0), 2)
    print("owner data")
    line("accounts", len(owner.accounts), 2)
    line("parties", len(owner.parties), 2)
    line("income sources", sum(party.income for party in owner.parties), 2)
    line("role decisions", len(owner.roles), 2)
    line("link decisions", len(owner.links), 2)
    line("inferred own accounts", len(inferred_accounts(txns)))
    print("self-transfers by basis")
    for basis in ("engine", "owner"):
        n = sum(d.role == "self_transfer" and d.basis == basis for d in derived.values())
        line(basis, n, 2)
    stored_run_lines(p)
    if not any(party.income for party in owner.parties):
        print(NO_INCOME_PARTY)
    return 0


def cmd_owner_load(session: Session, args: argparse.Namespace) -> int:
    """Load the owner's private file into the owner tables. Counts and field paths only."""
    try:
        owner_file = parse_owner_file(args.input.read_text(encoding="utf-8-sig"))
        if owner_file.export:
            restored = restore(session, settings.owner_id, owner_file)
        else:
            counts = sync(session, settings.owner_id, owner_file)
    except (OwnerFileError, UnicodeDecodeError) as exc:
        session.rollback()
        errors = exc.errors if isinstance(exc, OwnerFileError) else ["file: is not UTF-8 text"]
        for error in errors:
            print(error, file=sys.stderr)
        print(f"owner-load: {len(errors)} problem(s); nothing loaded", file=sys.stderr)
        return 2
    if owner_file.export:
        print(
            "owner-load: export restored (dry run: nothing saved)"
            if args.dry_run
            else "owner-load: export restored"
        )
        for name in EXPORT_COUNTS:
            line(name.replace("_", " "), restored[name])
        if args.dry_run:
            session.rollback()
            return 0
        session.commit()
        return run_recompute(session, "owner")
    seen = {
        normalise_merchant(t.counterparty_raw, channel_for(t.channel, t.hints)).merchant_key
        for t in active_txns(session, settings.owner_id)
    }
    unmatched = sorted(path for key, path in owner_file.text_paths.items() if key not in seen)

    print("owner-load (dry run: nothing saved)" if args.dry_run else "owner-load")
    for name, counter in counts.items():
        print(name)
        for what in ("added", "updated", "removed", "unchanged"):
            if what != "updated" or name in ("accounts", "parties"):
                line(what, counter[what], 2)
    line("income sources", sum(bool(v["income_label"]) for _, v, _ in owner_file.parties))
    line("texts matching no transaction", len(unmatched))
    for path in unmatched:
        print(f"  {path}")
    if args.dry_run:
        session.rollback()
        return 0
    session.commit()
    return run_recompute(session, "owner")


EXPORT_COUNTS = (
    "accounts",
    "identifiers",
    "parties",
    "texts",
    "role_decisions",
    "link_decisions",
    "category_decisions",
    "labels",
    "labelled_transactions",
    "mapped to another id",
)
REPO = Path(__file__).resolve().parents[2]


def cmd_owner_export(session: Session, args: argparse.Namespace) -> int:
    """Every owner table to one private JSON file, decisions with dedupe keys. Counts only."""
    target = args.output.resolve()
    if target.is_relative_to(REPO):
        print("owner-export: the file must be outside the repository", file=sys.stderr)
        return 2
    try:
        document, counts = export_owner(session, settings.owner_id)
    except OwnerFileError as exc:
        print(f"owner-export: {exc.errors[0]}", file=sys.stderr)
        return 2
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("owner-export")
    for name in EXPORT_COUNTS[:-1]:
        line(name.replace("_", " "), counts[name])
    return 0


def can_ask() -> bool:
    return sys.stdin.isatty()


def ask(prompt: str) -> str:
    return input(prompt)


def refuse_without_terminal(command: str) -> int | None:
    if is_terminal():
        return None
    print(
        f"{command} shows real names and amounts and prints only to a terminal: "
        "run it in a console window, without a pipe or redirect.",
        file=sys.stderr,
    )
    return 2


def txn_line(t: Txn) -> str:
    when = t.txn_time_utc.astimezone(IST).strftime("%Y-%m-%d %H:%M")
    return (
        f"  #{t.id:<6} {when} IST  {t.direction:<6} {format_inr(t.amount_paise):>16}  "
        f"{t.channel or '-':<11} {t.counterparty_raw or '-'}"
    )


# Review items: (title, transaction ids, answers -> what each answer saves)
PAIR_ANSWERS = {"same": "same", "different": "different", "skip": None}
CREDIT_ANSWERS = {"payback": "payback", "income": "income", "ignored": "ignored", "leave": None}
NO_PAYEE_ANSWERS = {"self_transfer": "self_transfer", "ignored": "ignored", "leave": None}


def review_items(p: Plan) -> list[tuple[str, tuple[int, ...], dict, str | None]]:
    """Open candidates, uncertain credits, transfers with no payee. (title, ids, answers, kind)."""
    items = [
        (f"{x.kind} candidate: {x.rule}, {x.reason}", (x.txn_a, x.txn_b), PAIR_ANSWERS, x.kind)
        for x in p.result.links
        if x.status == "candidate"
    ]
    for i, d in p.result.roles.items():
        if d.role == "uncertain":
            items.append((f"uncertain credit: {d.rule}", (i,), CREDIT_ANSWERS, None))
    for i, d in p.result.roles.items():
        if d.rule == "DB_no_counterparty":
            items.append((f"debit with no payee: {d.rule}", (i,), NO_PAYEE_ANSWERS, None))
    return items


def cmd_reconcile_review(session: Session, args: argparse.Namespace) -> int:
    """Owner only: decide candidates and roles on screen. Saves owner decisions, then recomputes."""
    if (refused := refuse_without_terminal("reconcile-review")) is not None:
        return refused
    if not args.list and not can_ask():
        print("reconcile-review asks questions: run it in a console window.", file=sys.stderr)
        return 2
    try:
        p = plan(session, settings.owner_id)
    except OwnerDataError as exc:
        print(f"reconcile-review failed: {exc}", file=sys.stderr)
        return 1
    by_id = {t.id: t for t in p.txns}
    items = review_items(p)
    links, roles = [], []
    print(PRIVATE)
    for n, (title, ids, answers, kind) in enumerate(items, 1):
        print(f"[{n}/{len(items)}] {title}")
        for i in ids:
            print(txn_line(by_id[i]))
        if args.list:
            continue
        choices = list(answers)
        prompt = f"{', '.join(choices[:-1])} or {choices[-1]} (quit to stop)? "
        while (answer := _answer(prompt)) not in (*answers, "quit"):
            print(f"  answer one of: {', '.join(choices)}, quit")
        if answer == "quit":
            break
        if answers[answer] and kind:
            links.append((kind, *ids, answers[answer]))
        elif answers[answer]:
            roles.append((ids[0], answers[answer]))
    print(
        f"{len(items)} item(s)"
        if args.list
        else f"answered: {len(links)} pair(s), {len(roles)} role(s)"
    )
    code = 0
    if links or roles:
        code = _save_review(session, links, roles)
    print(PRIVATE)
    return code


def _answer(prompt: str, keep_case: bool = False) -> str:
    try:
        answer = ask(prompt).strip()
        return (answer if keep_case else answer.casefold()) or "skip_or_leave"
    except EOFError:
        return "quit"


def _save_review(session: Session, links: list[tuple], roles: list[tuple]) -> int:
    """Owner decisions from the review (source "terminal"), checked, then one recompute."""
    now, owner = datetime.now(UTC), settings.owner_id
    for kind, a, b, verdict in links:
        row = session.scalar(
            select(OwnerLinkDecision).where(
                OwnerLinkDecision.owner_id == owner,
                OwnerLinkDecision.kind == kind,
                OwnerLinkDecision.txn_a == a,
                OwnerLinkDecision.txn_b == b,
            )
        )
        if row is None:
            row = OwnerLinkDecision(owner_id=owner, kind=kind, txn_a=a, txn_b=b)
            session.add(row)
        row.verdict, row.decided_at, row.source = verdict, now, "terminal"
    for txn, role in roles:
        row = session.get(OwnerRole, txn) or OwnerRole(transaction_id=txn, owner_id=owner)
        row.role, row.decided_at, row.source = role, now, "terminal"
        session.add(row)
    session.flush()
    try:
        plan(session, owner)  # decisions that contradict each other are refused here
    except OwnerDataError as exc:
        session.rollback()
        print(f"not saved: {exc}. Run the review again.", file=sys.stderr)
        return 1
    session.commit()
    print(f"saved: {len(links)} link decision(s), {len(roles)} role decision(s)")
    return run_recompute(session, "owner")


def cmd_totals(session: Session, args: argparse.Namespace) -> int:
    """Owner only: Spent, Paid back, Net and Income of one IST month, from stored roles."""
    try:
        start, end = ist_month(args.month)
    except ValueError as exc:
        print(f"totals: {exc}", file=sys.stderr)
        return 2
    if (refused := refuse_without_terminal("totals")) is not None:
        return refused
    try:
        p = plan(session, settings.owner_id)
    except OwnerDataError as exc:
        print(f"totals failed: {exc}", file=sys.stderr)
        return 1
    if reason := stale_reason(p):
        print(
            f"totals: stored results are stale ({reason}). Run: python -m app.cli recompute",
            file=sys.stderr,
        )
        return 1
    rows = session.execute(
        select(
            TxnDerived.role, TxnDerived.role_basis, Transaction.amount_paise, TxnDerived.category
        )
        .join(Transaction, Transaction.id == TxnDerived.transaction_id)
        .where(
            TxnDerived.owner_id == settings.owner_id,
            Transaction.txn_time_utc >= start,
            Transaction.txn_time_utc < end,
        )
    )
    sums, roles, by_category = Counter(), Counter(), Counter()
    for role, basis, amount, category in rows:
        if role in SPENDING_ROLES:
            by_category[category] += COUNTED[role][1] * amount
        roles[role] += 1
        if role in COUNTED:
            total, sign = COUNTED[role]
            sums[total] += sign * amount
        if role == "payback" and basis != "owner":  # D-076: shown, never subtracted
            sums["paid_back"] -= amount
            sums["to_confirm"] += amount
    print(PRIVATE)
    print(
        f"totals {args.month} (IST), stored run #{p.last_run_id} ({', '.join(VERSIONS.values())})"
    )
    for label, value, indent in (
        ("Spent", sums["spent"], 0),
        ("Paid back", sums["paid_back"], 0),
        ("To confirm", sums["to_confirm"], 0),
        ("Net", sums["spent"] - sums["paid_back"], 0),
        ("Income", sums["income"], 0),
    ):
        print(f"{' ' * indent}{label:<{24 - indent}}{format_inr(value):>20}")
    print("Spent by category")
    for slug, name in CATEGORIES.items():
        if by_category[slug]:
            print(f"  {name:<22}{format_inr(by_category[slug]):>20}")
    print(f"  {'adds up to':<22}{format_inr(sum(by_category.values())):>20}")
    print("transactions by role")
    for role in ROLES:
        line(role, roles[role], 2)
    line("transactions", sum(roles.values()))
    print(PRIVATE)
    return 0


def percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "-"


def cmd_category_stats(session: Session, args: argparse.Namespace) -> int:
    """Categories over active transactions, in memory. Read-only, counts and percentages only."""
    try:
        p = plan(session, settings.owner_id)
    except OwnerDataError as exc:
        print(f"category-stats failed: {exc}", file=sys.stderr)
        return 1
    spend = Counter(dict.fromkeys(CATEGORIES, 0))
    rules, basis, merchants = Counter(), Counter(engine=0, owner=0), Counter()
    not_spending = gross = gross_open = no_text = 0
    for t in p.txns:
        role, c = p.result.roles[t.id].role, p.categories[t.id]
        rules[c.rule] += 1
        if role not in SPENDING_ROLES:
            not_spending += 1
            continue
        spend[c.category] += 1
        basis[c.basis] += 1
        if t.direction == "debit":
            gross += t.amount_paise
        if c.category == UNCATEGORISED:
            gross_open += t.amount_paise if t.direction == "debit" else 0
            key = p.result.merchants[t.id].merchant_key
            if key:
                merchants[key] += 1
            else:
                no_text += 1
    counted = sum(spend.values())
    print(f"category-stats ({CATEGORISE_VERSION}, read-only)")
    line("transactions (active)", len(p.txns))
    line("not spending", not_spending, 2)
    line("spend transactions", counted, 2)
    print("spend transactions by category")
    for slug in CATEGORIES:
        line(slug, spend[slug], 2)
    print_counter("by rule (all transactions)", rules)
    print_counter("spend transactions by basis", basis)
    print("uncategorised")
    line("share of spend transactions", percent(spend[UNCATEGORISED], counted), 2)
    line("share of spend amount", percent(gross_open, gross), 2)
    line("merchants", len(merchants), 2)
    line("without merchant text", no_text, 2)
    for share in (0.5, 0.8, 0.95):
        line(f"merchants covering {share:.0%}", keys_covering(merchants, share), 2)
    stored_run_lines(p)
    return 0


def merchant_groups(p: Plan) -> list[dict]:
    """Merchants of spend debits, most transactions first, with their usual category."""
    groups: dict[str, dict] = {}
    for t in sorted(p.txns, key=lambda t: t.id):
        d, m = p.result.roles[t.id], p.result.merchants[t.id]
        if (
            d.role not in ("spend", "card_bill_counted")
            or not m.merchant_key
            or d.own_account is not None
        ):
            continue
        party = None if d.party is None else p.owner.parties[d.party]
        g = groups.setdefault(
            m.merchant_key,
            {
                "key": m.merchant_key,
                "name": m.display_name,
                "text": t.counterparty_raw,
                "kinds": set(),
                "party": d.party,
                "n": 0,
                "categories": Counter(),
            },
        )
        g["n"] += 1
        g["kinds"].add(m.kind)
        c = p.categories[t.id]
        g["categories"][c.category, c.basis, c.rule] += 1
        g["has_default"] = bool(party and party.category)
    for g in groups.values():
        g["category"], g["basis"], g["rule"] = g["categories"].most_common(1)[0][0]
    return sorted(groups.values(), key=lambda g: (-g["n"], g["key"]))


def cmd_category_review(session: Session, args: argparse.Namespace) -> int:
    """Owner only: pick a category for a merchant. Saved on a party, then one recompute."""
    if (refused := refuse_without_terminal("category-review")) is not None:
        return refused
    if not args.list and not can_ask():
        print("category-review asks questions: run it in a console window.", file=sys.stderr)
        return 2
    try:
        p = plan(session, settings.owner_id)
    except OwnerDataError as exc:
        print(f"category-review failed: {exc}", file=sys.stderr)
        return 1
    groups = merchant_groups(p)
    if args.uncategorised:
        groups = [g for g in groups if g["category"] == UNCATEGORISED]
    slugs = list(CATEGORIES)
    print(PRIVATE)
    if not args.list:
        for n, slug in enumerate(slugs, 1):
            print(f"  {n:>2} {slug:<16} {CATEGORIES[slug]}")
    answers = []
    for n, g in enumerate(groups, 1):
        current = f"{CATEGORIES[g['category']]} ({g['basis']}, {g['rule']})"
        print(f"[{n}/{len(groups)}] {g['n']:>4} txns  {g['name']}  ->  {current}")
        if args.list:
            continue
        choice = None
        while choice is None:
            answer = _answer("category number or slug (enter to skip, none to clear, quit)? ")
            if answer in ("quit", "skip_or_leave", "none") or answer in CATEGORIES:
                choice = answer
            elif answer.isdigit() and 1 <= int(answer) <= len(slugs):
                choice = slugs[int(answer) - 1]
            else:
                print("  answer a number from the list, a slug, none, or quit")
        if choice == "quit":
            break
        if choice != "skip_or_leave":
            answers.append((g, None if choice == "none" else choice))
    print(f"{len(groups)} merchant(s)" if args.list else f"answered: {len(answers)} merchant(s)")
    code = _save_categories(session, answers) if answers else 0
    print(PRIVATE)
    return code


def _save_categories(session: Session, answers: list[tuple[dict, str | None]]) -> int:
    """A default category per merchant: on its party, or on a new party (source terminal)."""
    owner = settings.owner_id
    _, _, parties = load_owner(session, owner)
    labels = {label.casefold() for label in session.scalars(select(Party.label))}
    for g, slug in answers:
        if g["party"] is not None:
            parties[g["party"]].category = slug
        elif slug:
            label, n = g["name"][:70], 1
            while label.casefold() in labels:
                n += 1
                label = f"{g['name'][:70]} ({n})"
            labels.add(label.casefold())
            kind = "person" if g["kinds"] == {"person"} else "business"  # mixed: a shop
            party = Party(owner_id=owner, label=label, kind=kind, category=slug, source="terminal")
            session.add(party)
            session.flush()
            session.add(
                PartyText(
                    owner_id=owner, party_id=party.id, text=g["text"][:200], source="terminal"
                )
            )
    session.flush()
    try:
        plan(session, owner)
    except OwnerDataError as exc:
        session.rollback()
        print(f"not saved: {exc}. Run the review again.", file=sys.stderr)
        return 1
    session.commit()
    print(f"saved: {len(answers)} merchant categor(ies)")
    return run_recompute(session, "owner")


def cmd_credit_review(session: Session, args: argparse.Namespace) -> int:
    """Owner only: confirm who sent credits. friend, income <label> or ignore; one recompute."""
    if (refused := refuse_without_terminal("credit-review")) is not None:
        return refused
    if not args.list and not can_ask():
        print("credit-review asks questions: run it in a console window.", file=sys.stderr)
        return 2
    open_senders = [s for s in senders(session, settings.owner_id) if s.status == "to_confirm"]
    print(PRIVATE)
    answers = []
    for n, s in enumerate(open_senders, 1):
        last = s.last_time_utc.astimezone(IST).strftime("%Y-%m-%d")
        print(
            f"[{n}/{len(open_senders)}] {s.count:>4} credits  {format_inr(s.total_paise):>16}  "
            f"last {last}  {s.role} ({s.basis})  {s.display_name or '-'}"
        )
        if args.list:
            continue
        while True:
            answer = _answer("friend, income <label>, ignore, or enter to skip (quit)? ", True)
            word, _, label = answer.partition(" ")
            word = word.casefold()
            answer = word if word in ("quit", "friend", "ignore") else answer
            if answer in ("quit", "skip_or_leave", "friend", "ignore") or (
                word == "income" and label
            ):
                break
            print("  answer friend, income <label>, ignore, or quit")
        if answer == "quit":
            break
        if answer != "skip_or_leave":
            answers.append((s.id, word, label.strip() or None))
    print(
        f"{len(open_senders)} sender(s) to confirm"
        if args.list
        else f"answered: {len(answers)} sender(s)"
    )
    code = 0
    if answers:
        try:
            for sender, word, label in answers:
                answer_sender(session, settings.owner_id, sender, word, label, "terminal")
            plan(session, settings.owner_id)
        except (ActionError, OwnerDataError) as exc:
            session.rollback()
            print(f"not saved: {exc}. Run the review again.", file=sys.stderr)
            code = 1
        else:
            session.commit()
            print(f"saved: {len(answers)} answer(s)")
            code = run_recompute(session, "owner")
    print(PRIVATE)
    return code


def cmd_payback_audit(session: Session, args: argparse.Namespace) -> int:
    """D-099. Counts and IST month keys only; --fix is a dry run, --fix --apply changes."""
    if args.fix and args.restore:
        print("use --fix or --restore, not both", file=sys.stderr)
        return 2
    if args.apply and not (args.fix or args.restore):
        print("--apply needs --fix or --restore (run it first: it is a dry run)", file=sys.stderr)
        return 2
    if args.restore:
        return payback_restore(session, args.apply)
    found = payback_audit.audit(session, settings.owner_id)
    print("payback-audit (counts only)")
    print(payback_audit.RULE)
    line("silent person parties", len(found.parties))
    line("credits in Paid back", found.credits)
    line("months affected", len(found.months))
    if found.months:
        print("  " + ", ".join(found.months))
    if not args.fix:
        print("Next: --fix shows what would change (a dry run).")
        return 0
    n = len(found.parties)
    party = "party" if n == 1 else "parties"
    if not args.apply:
        print(
            f"dry run: would change {n} {party} to kind unsure (texts, names and categories "
            f"kept); {found.credits} credit(s) would move from Paid back to To confirm. "
            "Nothing saved. To change them: --fix --apply"
        )
        return 0
    changed = payback_audit.fix(session, settings.owner_id)
    print(f"changed {changed} {'party' if changed == 1 else 'parties'} to kind unsure")
    return run_recompute(session, "owner")


def payback_restore(session: Session, apply: bool) -> int:
    """D-111. Undo an earlier --fix --apply where a Friend answer is on record. Counts only."""
    parties = payback_audit.restorable(session, settings.owner_id)
    credits = payback_audit.credits_of(session, settings.owner_id, [p.id for p in parties])
    print("payback-audit --restore (counts only)")
    print("restore: kind person again for a party the fix changed that has a Friend answer")
    line("parties to restore", len(parties))
    line("their credits", credits)
    if not apply:
        print("dry run: nothing saved. To restore them: --restore --apply")
        return 0
    restored = payback_audit.restore(session, settings.owner_id)
    print(f"restored {restored} {'party' if restored == 1 else 'parties'} to kind person")
    return run_recompute(session, "owner")


def _statements(paths: list[Path]) -> tuple[list, int, int] | None:
    """Rows of every file (oldest first), lines skipped and balance breaks; None on an error."""
    rows, skipped, breaks = [], 0, 0
    for path in paths:
        try:
            read = statement_hdfc.read(path.read_text(encoding="utf-8-sig", errors="replace"))
        except OSError as exc:
            print(f"cannot read a --file ({type(exc).__name__})", file=sys.stderr)
            return None
        except statement_hdfc.StatementError as exc:
            print(f"not read: {exc}", file=sys.stderr)
            return None
        rows += read.rows
        skipped += read.skipped
        breaks += statement_hdfc.check_balances(read.rows)
    rows.sort(key=lambda r: r.date)  # stable: file order inside a day
    return rows, skipped, breaks


def _rs(paise: int) -> str:
    return format_inr(paise)


def cmd_statement_check(session: Session, args: argparse.Namespace) -> int:
    """D-114. The statement against the app's HDFC rows. Counts and aggregate rupees (SAFE);
    --details lists the unmatched rows (PRIVATE, terminal only)."""
    if args.details and (refused := refuse_without_terminal("statement-check --details")):
        return refused
    read = _statements(args.file)
    if read is None:
        return 2
    rows, skipped, breaks = read
    if not rows:
        print("statement-check: no rows found", file=sys.stderr)
        return 1
    try:
        p = plan(session, settings.owner_id)
    except OwnerDataError as exc:
        print(f"statement-check failed: {exc}", file=sys.stderr)
        return 1
    if reason := stale_reason(p):
        print(f"statement-check: stored results are stale ({reason}). Run: python -m app.cli "
              "recompute", file=sys.stderr)  # fmt: skip
        return 1
    app = statement.app_rows(session, settings.owner_id, rows[0].date, rows[-1].date)
    ctx = statement.context(session, settings.owner_id, rows[0].date, rows[-1].date)
    months = statement_check.check(rows, app, ctx)
    print("statement-check (counts and rupee sums only; SAFE TO PASTE)")
    print(f"reader {statement_hdfc.STATEMENT_VERSION}: files {len(args.file)}, rows {len(rows)}, "
          f"lines skipped {skipped}, balance breaks {breaks}")  # fmt: skip
    if breaks:
        print("  a balance break means a row was read wrongly: the figures below may be off")
    for key, m in months.items():
        print(f"month {key}")
        print(
            f"  statement debits  {m.stmt_debits.count:>5} {_rs(m.stmt_debits.paise):>18}   "
            f"credits {m.stmt_credits.count:>5} {_rs(m.stmt_credits.paise):>18}"
        )
        print(
            f"  app HDFC debits   {m.app_debits.count:>5} {_rs(m.app_debits.paise):>18}   "
            f"credits {m.app_credits.count:>5} {_rs(m.app_credits.paise):>18}"
        )
        print(
            f"  matched {sum(m.matched.values())} (by reference {m.matched['reference']}, "
            f"by amount and day {m.matched['amount_day']})"
        )
        print(f"  statement only    {m.stmt_only.count:>5} {_rs(m.stmt_only.paise):>18}")
        print(f"  app only          {m.app_only.count:>5} {_rs(m.app_only.paise):>18}")
        print(f"  amount mismatches {m.mismatches.count:>5} {_rs(m.mismatches.paise):>18}")
        print("  unmatched by likely cause")
        for cause in statement_check.CAUSES:
            side = m.causes[cause]
            print(f"    {cause:<22}{side.count:>5} {_rs(side.paise):>18}")
        t = statement.month_totals(session, settings.owner_id, key)
        adjusted = t.spent_paise + m.stmt_only_debits.paise
        print(
            f"  app:   Spent {_rs(t.spent_paise)}, Paid back {_rs(t.paid_back_paise)}, "
            f"Net {_rs(t.net_paise)}"
        )
        print(
            f"  with statement-only debits as spend: Spent {_rs(adjusted)}, "
            f"Net {_rs(adjusted - t.paid_back_paise)} (difference {_rs(m.stmt_only_debits.paise)})"
        )
    if args.details:
        print(PRIVATE)
        for key, m in months.items():
            for side, cause, item in m.unmatched:
                if side == "statement":
                    print(
                        f"{key} statement {item.date} {item.direction:<6} "
                        f"{_rs(item.amount_paise):>16} {cause:<22} {item.narration[:60]}"
                    )
                else:
                    print(
                        f"{key} app       {item.day} {item.direction:<6} "
                        f"{_rs(item.amount_paise):>16} {cause:<22} transaction {item.id}"
                    )
        print(PRIVATE)
    return 0


def cmd_statement_import(session: Session, args: argparse.Namespace) -> int:
    """D-120. The statement-only rows as transactions. Dry run: counts by month and cause
    (SAFE). --apply writes them (after the planner's OK) and recomputes."""
    read = _statements(args.file)
    if read is None:
        return 2
    rows, _skipped, breaks = read
    if not rows:
        print("statement-import: no rows found", file=sys.stderr)
        return 1
    if breaks:
        print(f"refused: {breaks} balance break(s): fix the reading first", file=sys.stderr)
        return 1
    found = statement.plan_import(session, settings.owner_id, rows)
    print("statement-import (counts only; SAFE TO PASTE)")
    print(f"reader {statement_hdfc.STATEMENT_VERSION}: rows {len(rows)}, balance breaks 0")
    for (month, cause), n in sorted(found.by_cause.items()):
        print(f"  {month} {cause:<24}{n:>5}")
    line("rows to import", len(found.rows))
    for cause, n in sorted(found.skipped.items()):
        line(f"not imported: {cause}", n)
    if not args.apply:
        print("dry run: nothing saved. To import them: --apply (after the planner's OK)")
        return 0
    counts = statement.apply_import(session, settings.owner_id, found)
    line("imported", counts.raw_new)
    line("already imported", counts.raw_duplicate)
    line("merged into an existing transaction", counts.transactions["merged"])
    return run_recompute(session, "import")


def cmd_statement_names(session: Session, args: argparse.Namespace) -> int:
    """D-116. Payer names for nameless UPI credits, by the 12-digit reference. Counts (SAFE);
    --show lists the pairs (PRIVATE, terminal only); --apply writes them as owner data."""
    if args.show and args.apply:
        print("use --show or --apply, not both", file=sys.stderr)
        return 2
    if args.show and (refused := refuse_without_terminal("statement-names --show")):
        return refused
    read = _statements(args.file)
    if read is None:
        return 2
    rows, _skipped, breaks = read
    found = statement.plan_names(session, settings.owner_id, rows)
    print("statement-names (counts only; SAFE TO PASTE)")
    line("statement rows", len(rows))
    line("balance breaks", breaks)
    line("nameless UPI credits matched", found.credits)
    line("of those with a usable name", found.named)
    line("already named: left alone", found.already_named)
    line("two names for one party: left", found.conflicts)
    line("parties to name", len(found.proposals))
    line("names two parties would share", found.shared_names)
    if found.shared_names:
        print("  never joined automatically: use Same as… on the phone if they are one person")
    if args.show:
        print(PRIVATE)
        for raw, name in found.pairs:
            print(f"  {raw[:40]:<40} -> {name}")
        print(PRIVATE)
        return 0
    if not args.apply:
        print("dry run: nothing saved. To name them: --apply (after the planner's OK)")
        return 0
    changed = statement.apply_names(session, settings.owner_id, found)
    print(f"named {changed} {'party' if changed == 1 else 'parties'} (source statement)")
    return run_recompute(session, "owner")


def cmd_bank_survey(session: Session, args: argparse.Namespace) -> int:
    """D-100. Counts only, by sender family (not private), kind and parse status."""
    found = survey.bank_survey(session, settings.owner_id)
    print("bank-survey (counts only): family / kind / dedicated, generic, not parsed")
    for family in sorted(found["table"], key=lambda f: (f == survey.OTHER, f)):
        kinds = found["table"][family]
        total = sum(sum(c.values()) for c in kinds.values())
        print(f"{family}  ({total} messages, {found['foreign'][family]} foreign currency)")
        for kind in sorted(kinds):
            c = kinds[kind]
            print(f"  {kind:<10}" + "".join(f"{c[s]:>12}" for s in survey.STATUSES))
    return 0


def cmd_sender_survey(session: Session, args: argparse.Namespace) -> int:
    """5C. Sender codes holding a text, stored and skipped as unregistered: counts only."""
    paths = input_files(args.input) if args.input else []
    found = survey.sender_survey(session, settings.owner_id, args.contains, paths)
    registered = set(SENDER_BANKS)
    print(f"sender-survey (counts only): sender codes containing {args.contains.upper()}")
    if not args.input:
        print("  (stored messages only: --input <backup> adds the ones import-sms skips)")
    print(f"  {'code':<20}{'registered':>11}{'stored':>8}{'skipped':>9}"
          f"{'debit':>7}{'credit':>8}{'other':>7}")  # fmt: skip
    for code in sorted(found, key=lambda c: (c == survey.NOT_A_CODE, c)):
        c = found[code]
        reg = "-" if code == survey.NOT_A_CODE else "yes" if code in registered else "NO"
        print(f"  {code:<20}{reg:>11}{c['stored']:>8}{c['skipped']:>9}"
              f"{c['debit']:>7}{c['credit']:>8}{c['other']:>7}")  # fmt: skip
    if not found:
        print("  none")
    return 0


def cmd_auth_cleanup(session: Session, args: argparse.Namespace) -> int:
    """5C (D-131). Retry deleting the logins of deleted accounts. Counts and error types."""
    pending = list(session.scalars(select(AuthDeletion.auth_uid).order_by(AuthDeletion.auth_uid)))
    done, errors = 0, Counter()
    for uid in pending:
        if account.finish_auth(session, uid, supabase_admin.delete_user):
            done += 1
        else:
            errors[session.get(AuthDeletion, uid).last_error or "?"] += 1
    left = len(pending) - done
    print(f"auth-cleanup: pending {len(pending)}, deleted {done}, still pending {left}")
    for code, n in sorted(errors.items()):
        print(f"  {code}: {n}")
    return 0 if done == len(pending) else 1


def admin_owner(session: Session) -> uuid.UUID | None:
    """The admin's owner_id (D-129), the default for owner commands; None before 0015."""
    try:
        return session.scalar(
            select(AppUser.owner_id)
            .where(AppUser.role == "admin")
            .order_by(AppUser.created_at, AppUser.auth_uid)
            .limit(1)
        )
    except SQLAlchemyError:
        session.rollback()
        return None


def cmd_generic_preview(session: Session, args: argparse.Namespace) -> int:
    """D-101. What the generic parser would accept and refuse. Counts only, writes nothing."""
    found = survey.generic_preview(session, settings.owner_id)
    print("generic-preview (counts only, nothing written)")
    if not found:
        print("no stored message from a bank without a dedicated parser")
    for family in sorted(found):
        print(family)
        for group in ("accepted", "refused", "unsure", "foreign currency"):
            for what, n in sorted(found[family][group].items()):
                line(f"{group}: {what}", n, 2)
    return 0


PRIVATE_ROOT = Path("D:/FlashPrivate")  # the owner's private folder (CLAUDE.md)


def _leaks(reasons: Counter, lines: list[str]) -> None:
    print("refused: the leak scan found lines that may hold private data", file=sys.stderr)
    for reason in sample_export.LEAK_REASONS:
        line(reason, reasons[reason], 2)
    if lines and is_terminal():
        print("PRIVATE (your screen only, never paste):", file=sys.stderr)
        for text in lines[:20]:
            print("  " + text.replace("\n", " "), file=sys.stderr)


def cmd_redact_sample(session: Session, args: argparse.Namespace) -> int:
    """D-100. A redacted sample of one bank, written to the owner's review folder."""
    review = args.review_dir or PRIVATE_ROOT / "review"
    if args.unparsed and not args.family:
        print("--unparsed goes with --family", file=sys.stderr)
        return 2
    if sample_export.inside_repo(review):
        print("refused: the review folder must be outside the repository", file=sys.stderr)
        return 2
    if args.approve:
        reasons, lines, target = sample_export.approve(args.approve, review)
        if reasons is None:
            print(f"no file {sample_export.sample_name(args.approve)} in the review folder")
            return 2
        if target is None:
            _leaks(reasons, lines)
            return 1
        print(f"approved: leak scan clean; copied to data/sample/{target.name} (git-ignored)")
        return 0
    export = sample_export.build(session, settings.owner_id, args.family, args.unparsed)
    print(f"redact-sample {export.name.upper()} (counts only)")
    line("messages", export.messages)
    line("shapes", len(export.shapes))
    line("template words kept", sum(export.kept.values()))
    line("words replaced by {WORD}", export.replaced)
    if not export.messages:
        print("nothing to write: no stored message of this family")
        return 2
    reasons, lines, path = sample_export.write(export, review)
    if path is None:
        _leaks(reasons, lines)
        return 1
    print(f"written to the review folder: {path.name} and {export.name}-vocabulary.txt")
    print(f"PRIVATE: read both files, then run: redact-sample --approve {export.name.upper()}")
    return 0


def _out_refused(target: Path, name: str) -> bool:
    """A PRIVATE CSV goes outside the repository, into a folder that exists (D-137)."""
    target = target.resolve()
    if target.is_relative_to(REPO):
        print(f"{name}: refused: --out must be outside the repository", file=sys.stderr)
        return True
    if not target.parent.is_dir():
        print(f"{name}: refused: the folder of --out does not exist", file=sys.stderr)
        return True
    return False


def _write_csv(target: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    with target.resolve().open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def cmd_category_diff(session: Session, args: argparse.Namespace) -> int:
    """D-137. categorise-1.2.0 against 1.3.0 on the owner's data, in memory: counts by
    category before and after, the number changed; the changed rows to a PRIVATE CSV."""
    if _out_refused(args.out, "category-diff"):
        return 2
    try:
        diff = review.category_diff(session, settings.owner_id)
    except OwnerDataError as exc:
        print(f"category-diff: owner data: {exc}", file=sys.stderr)
        return 1
    finally:
        session.rollback()  # read only: nothing to keep
    print("category-diff (categorise-1.2.0 -> 1.3.0, read-only, counts only)")
    line("transactions (active)", sum(diff.before.values()))
    line("category changed", len(diff.rows))
    print("by category (1.2.0 -> 1.3.0)")
    for slug in CATEGORIES:
        if diff.before[slug] or diff.after[slug]:
            print(f"  {slug:<26}{diff.before[slug]:>6} -> {diff.after[slug]:<6}")
    moves = Counter((r["category_1_2_0"], r["category_1_3_0"]) for r in diff.rows)
    if moves:
        print("moves")
        for (a, b), n in sorted(moves.items(), key=lambda m: (-m[1], m[0])):
            line(f"{a} -> {b}", n, 2)
    _write_csv(args.out, review.DIFF_COLUMNS, diff.rows)
    print(f"PRIVATE: the {len(diff.rows)} changed rows are in the --out file; never paste it")
    return 0


def cmd_payback_review(session: Session, args: argparse.Namespace) -> int:
    """D-137. Paybacks: engine-suggested, owner-confirmed and unanswered credits, by IST
    month, and how many paybacks are linked to a payment. Counts here; rows to a PRIVATE CSV."""
    if _out_refused(args.out, "payback-review"):
        return 2
    try:
        found = review.payback_review(session, settings.owner_id)
    except OwnerDataError as exc:
        print(f"payback-review: owner data: {exc}", file=sys.stderr)
        return 1
    finally:
        session.rollback()
    names = ("owner_confirmed", "engine_suggested", "unanswered")
    print(f"payback-review ({RECONCILE_VERSION}, read-only, counts only)")
    for name in names:
        line(name.replace("_", " "), found.counts[name])
    print("paybacks linked to a payment")
    for status in ("linked", "candidate", "none"):
        line(status, found.links[status], 2)
    print("by IST month (confirmed / suggested / unanswered)")
    for month, c in found.by_month.items():
        print(f"  {month:<26}{' / '.join(str(c[n]) for n in names)}")
    _write_csv(args.out, review.PAYBACK_COLUMNS, found.rows)
    print(f"PRIVATE: the {len(found.rows)} rows are in the --out file; never paste it")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    parser.add_argument(
        "--owner", type=uuid.UUID, metavar="OWNER_ID",
        help="whose data (before the command); default: the admin, else OWNER_ID",
    )  # fmt: skip
    sub = parser.add_subparsers(dest="command", required=True)
    ss = sub.add_parser("sender-survey", help="sender codes holding a text (counts only)")
    ss.add_argument("--contains", required=True, help="text in the sender code, e.g. HDFC")
    ss.add_argument("--input", type=Path, help="the SMS backup: adds the skipped messages")
    sub.add_parser("auth-cleanup", help="retry deleting the logins of deleted accounts")
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
    load = sub.add_parser("owner-load", help="load the owner's private file")
    load.add_argument("input", type=Path, help="the owner JSON file")
    load.add_argument("--dry-run", action="store_true", help="check and count, save nothing")
    rec = sub.add_parser("recompute", help="bring the derived tables up to date")
    rec.add_argument("--dry-run", action="store_true", help="count the changes, save nothing")
    rec.add_argument(
        "--accept-key-changes",
        action="store_true",
        help="go on although transactions lose their owner match after a merchant engine change",
    )
    rv = sub.add_parser("reconcile-review", help="owner only: decide candidates and roles")
    rv.add_argument("--list", action="store_true", help="show the items, ask nothing")
    ex = sub.add_parser("owner-export", help="owner tables to one private JSON file")
    ex.add_argument("output", type=Path, help="where to write it, outside the repository")
    tot = sub.add_parser("totals", help="owner only: Spent, Paid back, Net, Income of a month")
    tot.add_argument("--month", required=True, help="YYYY-MM, an IST calendar month")
    sub.add_parser("category-stats", help="category counts over transactions (read-only)")
    cat = sub.add_parser("category-review", help="owner only: a category per merchant")
    cat.add_argument("--uncategorised", action="store_true", help="only uncategorised merchants")
    cat.add_argument("--list", action="store_true", help="show the merchants, ask nothing")
    cr = sub.add_parser("credit-review", help="owner only: confirm who sent credits")
    cr.add_argument("--list", action="store_true", help="show the senders, ask nothing")
    pa = sub.add_parser(
        "payback-audit",
        help="counts of person parties whose credits count as Paid back with no owner answer",
        description=payback_audit.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pa.add_argument("--fix", action="store_true", help="dry run: what the repair would change")
    pa.add_argument(
        "--restore", action="store_true", help="dry run: undo an earlier fix where answered"
    )
    pa.add_argument("--apply", action="store_true", help="with --fix or --restore: make it")
    sub.add_parser(
        "bank-survey",
        help="counts of messages by sender family, kind and parse status",
        description=survey.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub.add_parser(
        "generic-preview",
        help="counts of what the generic parser would accept and refuse (writes nothing)",
    )
    rs = sub.add_parser(
        "redact-sample",
        help="a redacted sample of one bank, to the private review folder",
        description=sample_export.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    which = rs.add_mutually_exclusive_group(required=True)
    which.add_argument("--family", help="the bank, as bank-survey names it (e.g. SBI)")
    which.add_argument("--approve", metavar="FAMILY", help="scan again, copy to data/sample/")
    rs.add_argument("--review-dir", type=Path, help="default D:/FlashPrivate/review")
    rs.add_argument(
        "--unparsed", action="store_true",
        help="with --family: only the messages no parser read (approve as <BANK>-UNPARSED)",
    )  # fmt: skip
    sc = sub.add_parser(
        "statement-check",
        help="the HDFC statement against the app, per IST month (counts and rupee sums)",
        description=statement_check.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sc.add_argument("--file", type=Path, action="append", required=True,
                    help="an HDFC NetBanking Delimited statement; repeat for more")  # fmt: skip
    sc.add_argument("--details", action="store_true", help="PRIVATE: list the unmatched rows")
    si = sub.add_parser(
        "statement-import",
        help="the statement-only rows as transactions (dry run: counts by month and cause)",
    )
    si.add_argument("--file", type=Path, action="append", required=True,
                    help="an HDFC NetBanking Delimited statement; repeat for more")  # fmt: skip
    si.add_argument("--apply", action="store_true", help="import them, then recompute")
    sn = sub.add_parser(
        "statement-names",
        help="payer names for nameless UPI credits, from the statement (counts; dry run)",
    )
    sn.add_argument("--file", type=Path, action="append", required=True,
                    help="an HDFC NetBanking Delimited statement; repeat for more")  # fmt: skip
    sn.add_argument("--show", action="store_true", help="PRIVATE: list the proposed names")
    sn.add_argument("--apply", action="store_true", help="name them (owner data, source statement)")
    cd = sub.add_parser(
        "category-diff",
        help="categorise-1.2.0 vs 1.3.0 (counts; changed rows to a PRIVATE CSV, read-only)",
    )
    cd.add_argument("--out", type=Path, required=True, help="the CSV, outside the repository")
    pr = sub.add_parser(
        "payback-review",
        help="paybacks confirmed, suggested and unanswered (counts; rows to a PRIVATE CSV)",
    )
    pr.add_argument("--out", type=Path, required=True, help="the CSV, outside the repository")
    return parser


COMMANDS = {
    "import-sms": cmd_import,
    "reparse": cmd_reparse,
    "stats": cmd_stats,
    "merchant-stats": cmd_merchant_stats,
    "merchant-review": cmd_merchant_review,
    "reconcile-stats": cmd_reconcile_stats,
    "owner-load": cmd_owner_load,
    "recompute": cmd_recompute,
    "reconcile-review": cmd_reconcile_review,
    "owner-export": cmd_owner_export,
    "totals": cmd_totals,
    "category-stats": cmd_category_stats,
    "category-review": cmd_category_review,
    "credit-review": cmd_credit_review,
    "payback-audit": cmd_payback_audit,
    "bank-survey": cmd_bank_survey,
    "generic-preview": cmd_generic_preview,
    "redact-sample": cmd_redact_sample,
    "statement-check": cmd_statement_check,
    "statement-import": cmd_statement_import,
    "statement-names": cmd_statement_names,
    "sender-survey": cmd_sender_survey,
    "auth-cleanup": cmd_auth_cleanup,
    "category-diff": cmd_category_diff,
    "payback-review": cmd_payback_review,
}


def main(argv: list[str] | None = None, session_factory=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "input", None) is not None and not args.input.exists():
        print("input not found", file=sys.stderr)
        return 2
    if session_factory is None:
        from app.db import SessionLocal as session_factory
    with session_factory() as session:
        # Whose data (5C, D-130): --owner, else the admin in app_users, else OWNER_ID.
        saved = settings.owner_id
        settings.owner_id = args.owner or admin_owner(session) or saved
        try:
            return COMMANDS[args.command](session, args) or 0
        finally:
            settings.owner_id = saved


if __name__ == "__main__":
    sys.exit(main())
