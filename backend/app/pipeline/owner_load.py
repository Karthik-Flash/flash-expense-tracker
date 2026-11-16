"""Owner file: check it strictly, then make the file's rows in the owner tables equal to it.

The file is private. Nothing from it is ever printed or logged: every problem is
reported by its field path, such as parties[2].texts[0], never by its value.

A load touches only rows whose source is "file". Rows written by the review or
the app, and every decision, are left exactly as they are (D-070).

Format (docs/data-model.md, "Owner file"; example in docs/owner.example.json):

  {"accounts": [{"label", "kind", "bank", "last4": [...], "texts": [...]}],
   "parties":  [{"label", "kind", "income", "texts": [...]}]}
"""

import json
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.merchant import normalise_merchant
from app.engine.senders import SENDER_BANKS
from app.models import ACCOUNT_KINDS, PARTY_KINDS, OwnAccount, OwnIdentifier, Party, PartyText

BANKS = tuple(sorted(set(SENDER_BANKS.values())))
TOP_KEYS = ("accounts", "parties")
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
    _unknown_keys(data, "file", TOP_KEYS, errors)

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
            _unknown_keys(item, path, keys, errors)
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
            target.append((label or "", columns, children))
    if errors:
        raise OwnerFileError(errors)
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
