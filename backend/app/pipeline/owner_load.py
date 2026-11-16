"""Owner file: check it strictly, then make the file's rows in the owner tables equal to it.

The file is private. Nothing from it is ever printed or logged: every problem is
reported by its field path, such as parties[2].texts[0], never by its value.

A load touches only rows whose source is "file". Rows written by the review or
the app, and every decision, are left exactly as they are (D-070).

Format (docs/data-model.md, "Owner file"; example in docs/owner.example.json):

  {"accounts": [{"label", "kind", "bank", "last4": [...], "texts": [...]}],
   "parties":  [{"label", "kind", "income", "texts": [...]}]}

An export (owner-export) has the same shape plus "format", a "source" on every
entry, and the decisions ("roles", "links"), each naming its transactions by id
and dedupe key. It is restored only into empty owner tables; ids are mapped by
dedupe key, so a rebuilt database takes it back.
"""

import json
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine.merchant import normalise_merchant
from app.engine.senders import SENDER_BANKS
from app.models import (
    ACCOUNT_KINDS,
    OWNER_LINK_KINDS,
    OWNER_ROLES,
    OWNER_SOURCES,
    PARTY_KINDS,
    VERDICTS,
    OwnAccount,
    OwnerLinkDecision,
    OwnerRole,
    OwnIdentifier,
    Party,
    PartyText,
    Transaction,
)

BANKS = tuple(sorted(set(SENDER_BANKS.values())))
TOP_KEYS = ("accounts", "parties")
EXPORT_FORMAT = "flash-owner-export-1"
EXPORT_KEYS = ("format", *TOP_KEYS, "roles", "links")
ROLE_KEYS = ("transaction", "dedupe_key", "role", "decided_at", "source")
LINK_KEYS = ("kind", "a", "a_key", "b", "b_key", "verdict", "decided_at", "source")
ACCOUNT_KEYS = ("label", "kind", "bank", "last4", "texts")
PARTY_KEYS = ("label", "kind", "income", "texts")
MAX_LABEL, MAX_TEXT = 80, 200  # column sizes
LAST4 = re.compile(r"\d{4}")

Children = set[tuple[str, ...]]


class OwnerFileError(Exception):
    """Problems in an owner file, as "path: what is wrong" lines without any value."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__(f"{len(errors)} problem(s) in the owner file")
        self.errors = errors


@dataclass
class OwnerFile:
    """A checked owner file. Each entry: (label, column values, child rows)."""

    accounts: list[tuple[str, dict, Children]] = field(default_factory=list)  # (kind, value)
    parties: list[tuple[str, dict, Children]] = field(default_factory=list)  # (text,)
    text_paths: dict[str, str] = field(default_factory=dict)  # merchant key -> field path
    export: bool = False  # an owner-export file: sources and decisions included
    roles: list[dict] = field(default_factory=list)  # export only, with "path"
    links: list[dict] = field(default_factory=list)


def text_key(text: str) -> str | None:
    """The merchant key of an owner text: how the engine matches it to a transaction."""
    return normalise_merchant(text, "other").merchant_key


def parse_owner_file(raw: str) -> OwnerFile:
    """Check everything; raise OwnerFileError with every problem found."""

    def pairs(items: list[tuple[str, object]]) -> dict:
        if len({k for k, _ in items}) != len(items):
            raise OwnerFileError(["file: one object has the same key twice"])
        return dict(items)

    try:
        data = json.loads(raw, object_pairs_hook=pairs)
    except json.JSONDecodeError as exc:
        raise OwnerFileError([f"file: line {exc.lineno}, column {exc.colno}: {exc.msg}"]) from None
    errors: list[str] = []
    out = OwnerFile()
    if not isinstance(data, dict):
        raise OwnerFileError(["file: must be an object with accounts and parties"])
    out.export = "format" in data
    if out.export and data["format"] != EXPORT_FORMAT:
        raise OwnerFileError([f"file.format: must be {EXPORT_FORMAT}"])
    _unknown_keys(data, "file", EXPORT_KEYS if out.export else TOP_KEYS, errors)

    numbers: dict[tuple[str, str], str] = {}  # (bank, last 4) -> path
    for name, keys, kinds, target in (
        ("accounts", ACCOUNT_KEYS, ACCOUNT_KINDS, out.accounts),
        ("parties", PARTY_KEYS, PARTY_KINDS, out.parties),
    ):
        entries = data.get(name, [])
        if not isinstance(entries, list):
            errors.append(f"{name}: must be a list")
            continue
        labels: dict[str, str] = {}
        for n, item in enumerate(entries):
            path = f"{name}[{n}]"
            if not isinstance(item, dict):
                errors.append(f"{path}: must be an object")
                continue
            _unknown_keys(item, path, (*keys, "source") if out.export else keys, errors)
            label = _string(item.get("label"), f"{path}.label", MAX_LABEL, errors)
            if label and labels.setdefault(label.casefold(), path) != path:
                errors.append(f"{path}.label: same label as {labels[label.casefold()]}")
            if item.get("kind") not in kinds:
                errors.append(f"{path}.kind: must be one of {', '.join(kinds)}")
            texts = _texts(item.get("texts", []), f"{path}.texts", out.text_paths, errors)
            children: Children = {("text", t) if name == "accounts" else (t,) for t in texts}
            if name == "accounts":
                bank = item.get("bank")
                if bank is not None and bank not in BANKS:
                    errors.append(f"{path}.bank: must be one of {', '.join(BANKS)}")
                last4 = _last4(item.get("last4", []), bank, path, numbers, errors)
                children |= {("last4", v) for v in last4}
                if not children:
                    errors.append(f"{path}: needs at least one last4 or text")
                columns = {"kind": item.get("kind"), "bank": bank}
            else:
                income = item.get("income")
                if income is not None:
                    income = _string(income, f"{path}.income", MAX_LABEL, errors)
                if not texts:
                    errors.append(f"{path}.texts: needs at least one text")
                columns = {"kind": item.get("kind"), "income_label": income}
            if out.export:
                columns["source"] = _choice(
                    item.get("source"), f"{path}.source", OWNER_SOURCES, errors
                )
            target.append((label or "", columns, children))
    if out.export:
        out.roles = _decisions(data, "roles", ROLE_KEYS, errors)
        out.links = _decisions(data, "links", LINK_KEYS, errors)
    if errors:
        raise OwnerFileError(errors)
    return out


def _choice(value: object, path: str, allowed: tuple[str, ...], errors: list[str]) -> str:
    if value not in allowed:
        errors.append(f"{path}: must be one of {', '.join(allowed)}")
    return value  # type: ignore[return-value]


def _decisions(data: dict, name: str, keys: tuple[str, ...], errors: list[str]) -> list[dict]:
    """Decisions in an export. Each keeps its field path for later errors."""
    items = data.get(name, [])
    if not isinstance(items, list):
        errors.append(f"{name}: must be a list")
        return []
    out = []
    for n, item in enumerate(items):
        path = f"{name}[{n}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: must be an object")
            continue
        _unknown_keys(item, path, keys, errors)
        for key in keys:
            value = item.get(key)
            if key in ("transaction", "a", "b"):
                if type(value) is not int or value < 1:
                    errors.append(f"{path}.{key}: must be a transaction id")
            elif key.endswith("key"):
                _string(value, f"{path}.{key}", 64, errors)
            elif key == "decided_at":
                try:
                    if datetime.fromisoformat(value).tzinfo is None:
                        raise ValueError
                except (TypeError, ValueError):
                    errors.append(f"{path}.decided_at: must be an ISO time with a zone")
            else:
                allowed = {
                    "role": OWNER_ROLES,
                    "kind": OWNER_LINK_KINDS,
                    "verdict": VERDICTS,
                    "source": OWNER_SOURCES,
                }[key]
                _choice(value, f"{path}.{key}", allowed, errors)
        out.append(item | {"path": path})
    return out


def _unknown_keys(item: dict, path: str, allowed: tuple[str, ...], errors: list[str]) -> None:
    unknown = len(set(item) - set(allowed))
    if unknown:  # the key itself is not shown: it could be a value typed in the wrong place
        errors.append(f"{path}: {unknown} unknown key(s); allowed: {', '.join(allowed)}")


def _string(value: object, path: str, limit: int, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: must be a non-empty string")
    elif len(value.strip()) > limit:
        errors.append(f"{path}: longer than {limit} characters")
    else:
        return value.strip()
    return None


def _texts(value: object, path: str, seen: dict[str, str], errors: list[str]) -> list[str]:
    """Texts of one entry. One text may belong to one place only, compared by merchant key."""
    if not isinstance(value, list):
        errors.append(f"{path}: must be a list")
        return []
    out = []
    for n, item in enumerate(value):
        here = f"{path}[{n}]"
        text = _string(item, here, MAX_TEXT, errors)
        if text is None:
            continue
        key = text_key(text)
        if key is None:
            errors.append(f"{here}: has no letters or digits")
        elif seen.setdefault(key, here) != here:
            errors.append(f"{here}: same text as {seen[key]}")
        else:
            out.append(text)
    return out


def _last4(
    value: object, bank: object, path: str, seen: dict[tuple[str, str], str], errors: list[str]
) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{path}.last4: must be a list")
        return []
    if value and bank is None:
        errors.append(f"{path}.bank: needed when last4 is given")
    out = []
    for n, item in enumerate(value):
        here = f"{path}.last4[{n}]"
        if not isinstance(item, str) or not LAST4.fullmatch(item):
            errors.append(f"{here}: must be a string of 4 digits")
        elif seen.setdefault((str(bank), item), here) != here:
            errors.append(f"{here}: same number as {seen[str(bank), item]}")
        else:
            out.append(item)
    return out


def sync(session: Session, owner_id: uuid.UUID, owner_file: OwnerFile) -> dict[str, Counter]:
    """Make the file rows equal to the file, in the caller's transaction. Returns counts.

    Raises OwnerFileError when the file claims a label, text or number that a row not
    from a file already holds. Loading the same file twice writes nothing.
    """
    _check_against_other_rows(session, owner_id, owner_file)
    counts: dict[str, Counter] = {}
    account_columns = ("kind", "value")
    counts["accounts"], counts["identifiers"] = _sync(
        session,
        owner_id,
        OwnAccount,
        OwnIdentifier,
        "own_account_id",
        account_columns,
        owner_file.accounts,
    )
    counts["parties"], counts["texts"] = _sync(
        session, owner_id, Party, PartyText, "party_id", ("text",), owner_file.parties
    )
    return counts


def _check_against_other_rows(session: Session, owner_id: uuid.UUID, owner_file: OwnerFile) -> None:
    errors = []
    other = {"accounts": set(), "parties": set()}
    for name, model in (("accounts", OwnAccount), ("parties", Party)):
        rows = session.scalars(select(model).where(model.owner_id == owner_id))
        other[name] = {row.label.casefold() for row in rows if row.source != "file"}
    for name, entries in (("accounts", owner_file.accounts), ("parties", owner_file.parties)):
        for n, (label, _, _) in enumerate(entries):
            if label.casefold() in other[name]:
                errors.append(
                    f"{name}[{n}].label: already used by an entry that is not from a file"
                )
    texts = [
        *session.scalars(
            select(OwnIdentifier.value).where(
                OwnIdentifier.owner_id == owner_id,
                OwnIdentifier.kind == "text",
                OwnIdentifier.source != "file",
            )
        ),
        *session.scalars(
            select(PartyText.text).where(PartyText.owner_id == owner_id, PartyText.source != "file")
        ),
    ]
    for key in {text_key(t) for t in texts} & owner_file.text_paths.keys():
        errors.append(
            f"{owner_file.text_paths[key]}: already used by an entry that is not from a file"
        )
    if errors:
        raise OwnerFileError(sorted(errors))


def _sync(
    session: Session,
    owner_id: uuid.UUID,
    parent_model: type,
    child_model: type,
    link: str,
    columns: tuple[str, ...],
    wanted: list[tuple[str, dict, Children]],
) -> tuple[Counter, Counter]:
    """One parent table and its child table. Only rows with source "file" are touched."""
    parent_counts, child_counts = Counter(), Counter()
    parents = {
        p.label.casefold(): p
        for p in session.scalars(
            select(parent_model).where(
                parent_model.owner_id == owner_id, parent_model.source == "file"
            )
        )
    }
    children: dict[int, dict[tuple[str, ...], object]] = defaultdict(dict)
    not_from_file: Counter[int] = Counter()
    for child in session.scalars(select(child_model).where(child_model.owner_id == owner_id)):
        if child.source == "file":
            children[getattr(child, link)][tuple(getattr(child, c) for c in columns)] = child
        else:
            not_from_file[getattr(child, link)] += 1
    keep = {label.casefold(): keys for label, _, keys in wanted}

    # Removals first, children before parents: a text may move from one entry to another.
    gone = []
    for label, parent in parents.items():
        for key, child in children[parent.id].items():
            if key not in keep.get(label, ()):
                session.delete(child)
                child_counts["removed"] += 1
        if label not in keep and not not_from_file[parent.id]:
            gone.append(parent)
    session.flush()
    for parent in gone:
        session.delete(parent)
        parent_counts["removed"] += 1
    session.flush()

    for label, values, keys in wanted:
        parent = parents.get(label.casefold())
        if parent is None:
            parent = parent_model(owner_id=owner_id, label=label, source="file", **values)
            session.add(parent)
            session.flush()
            parent_counts["added"] += 1
        elif any(getattr(parent, k) != v for k, v in {"label": label, **values}.items()):
            parent.label = label
            for k, v in values.items():
                setattr(parent, k, v)
            parent_counts["updated"] += 1
        else:
            parent_counts["unchanged"] += 1
        have = children[parent.id].keys()
        for key in sorted(keys - have):
            session.add(
                child_model(
                    owner_id=owner_id,
                    source="file",
                    **{link: parent.id},
                    **dict(zip(columns, key, strict=True)),
                )
            )
            child_counts["added"] += 1
        child_counts["unchanged"] += len(keys & have)
    session.flush()
    return parent_counts, child_counts


# --- export and restore -----------------------------------------------------------

OWNER_MODELS = (OwnIdentifier, PartyText, OwnerLinkDecision, OwnerRole, OwnAccount, Party)


def export_owner(session: Session, owner_id: uuid.UUID) -> tuple[dict, Counter]:
    """Every owner row as one export document, plus counts. Decisions carry dedupe keys."""
    keys = dict(
        session.execute(
            select(Transaction.id, Transaction.dedupe_key).where(Transaction.owner_id == owner_id)
        ).all()
    )
    counts: Counter = Counter()
    accounts, parties = [], []
    for model, child, link, target in (
        (OwnAccount, OwnIdentifier, "own_account_id", accounts),
        (Party, PartyText, "party_id", parties),
    ):
        children = defaultdict(list)
        for row in session.scalars(
            select(child).where(child.owner_id == owner_id).order_by(child.id)
        ):
            children[getattr(row, link)].append(row)
        for row in session.scalars(
            select(model).where(model.owner_id == owner_id).order_by(model.id)
        ):
            mine = children[row.id]
            # ponytail: one source per entry; nothing writes a child with another source
            # yet. Give children their own source in the format when the app does.
            if any(c.source != row.source for c in mine):
                raise OwnerFileError(
                    ["an owner entry has rows from two sources; not exportable yet"]
                )
            entry = {"label": row.label, "kind": row.kind}
            if model is OwnAccount:
                if row.bank:
                    entry["bank"] = row.bank
                entry["last4"] = [c.value for c in mine if c.kind == "last4"]
                entry["texts"] = [c.value for c in mine if c.kind == "text"]
                counts["identifiers"] += len(mine)
            else:
                if row.income_label:
                    entry["income"] = row.income_label
                entry["texts"] = [c.text for c in mine]
                counts["texts"] += len(mine)
            entry["source"] = row.source
            target.append(entry)
    roles = [
        {
            "transaction": r.transaction_id,
            "dedupe_key": keys[r.transaction_id],
            "role": r.role,
            "decided_at": r.decided_at.isoformat(),
            "source": r.source,
        }
        for r in session.scalars(
            select(OwnerRole)
            .where(OwnerRole.owner_id == owner_id)
            .order_by(OwnerRole.transaction_id)
        )
    ]
    links = [
        {
            "kind": d.kind,
            "a": d.txn_a,
            "a_key": keys[d.txn_a],
            "b": d.txn_b,
            "b_key": keys[d.txn_b],
            "verdict": d.verdict,
            "decided_at": d.decided_at.isoformat(),
            "source": d.source,
        }
        for d in session.scalars(
            select(OwnerLinkDecision)
            .where(OwnerLinkDecision.owner_id == owner_id)
            .order_by(OwnerLinkDecision.id)
        )
    ]
    counts.update(
        accounts=len(accounts),
        parties=len(parties),
        role_decisions=len(roles),
        link_decisions=len(links),
    )
    document = {"format": EXPORT_FORMAT, "accounts": accounts, "parties": parties}
    return document | {"roles": roles, "links": links}, counts


def restore(session: Session, owner_id: uuid.UUID, owner_file: OwnerFile) -> Counter:
    """Write an export into empty owner tables, in the caller's transaction.

    Decisions are attached by dedupe key; an id that now belongs to another transaction
    is mapped. A decision whose transaction is not in the database stops the restore.
    """
    used = sum(
        session.scalar(select(func.count()).select_from(m).where(m.owner_id == owner_id))
        for m in OWNER_MODELS
    )
    if used:
        raise OwnerFileError(
            ["owner tables: not empty; an export is restored only into empty owner tables"]
        )
    wanted = {d["dedupe_key"] for d in owner_file.roles}
    wanted |= {d[k] for d in owner_file.links for k in ("a_key", "b_key")}
    ids = dict(
        session.execute(
            select(Transaction.dedupe_key, Transaction.id).where(
                Transaction.owner_id == owner_id, Transaction.dedupe_key.in_(wanted)
            )
        ).all()
    )
    errors = [
        f"{d['path']}.{k}: no transaction with this dedupe key; import the messages first"
        for d, k in [(d, "dedupe_key") for d in owner_file.roles]
        + [(d, k) for d in owner_file.links for k in ("a_key", "b_key")]
        if d[k] not in ids
    ]
    if errors:
        raise OwnerFileError(errors)

    counts: Counter = Counter()
    for model, child, link, entries in (
        (OwnAccount, OwnIdentifier, "own_account_id", owner_file.accounts),
        (Party, PartyText, "party_id", owner_file.parties),
    ):
        for label, columns, children in entries:
            parent = model(owner_id=owner_id, label=label, **columns)
            session.add(parent)
            session.flush()
            for key in sorted(children):
                values = dict(
                    zip(("kind", "value") if model is OwnAccount else ("text",), key, strict=True)
                )
                session.add(
                    child(
                        owner_id=owner_id, source=columns["source"], **{link: parent.id}, **values
                    )
                )
            counts["identifiers" if model is OwnAccount else "texts"] += len(children)
        counts["accounts" if model is OwnAccount else "parties"] += len(entries)
    for d in owner_file.roles:
        txn = ids[d["dedupe_key"]]
        counts["mapped to another id"] += txn != d["transaction"]
        session.add(
            OwnerRole(
                transaction_id=txn,
                owner_id=owner_id,
                role=d["role"],
                decided_at=datetime.fromisoformat(d["decided_at"]),
                source=d["source"],
            )
        )
    for d in owner_file.links:
        a, b = ids[d["a_key"]], ids[d["b_key"]]
        counts["mapped to another id"] += (a, b) != (d["a"], d["b"])
        session.add(
            OwnerLinkDecision(
                owner_id=owner_id,
                kind=d["kind"],
                txn_a=min(a, b),
                txn_b=max(a, b),
                verdict=d["verdict"],
                decided_at=datetime.fromisoformat(d["decided_at"]),
                source=d["source"],
            )
        )
    counts.update(role_decisions=len(owner_file.roles), link_decisions=len(owner_file.links))
    session.flush()
    return counts
