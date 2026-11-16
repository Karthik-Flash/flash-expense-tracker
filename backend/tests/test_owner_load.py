"""owner-load: strict file checks, file rows only, counts and field paths only. Fake values."""

import copy
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import settings
from app.engine import reconcile
from app.models import (
    OwnAccount,
    OwnerLinkDecision,
    OwnerRole,
    OwnIdentifier,
    Party,
    PartyText,
    Transaction,
)
from app.pipeline.owner_load import OwnerFileError, parse_owner_file

EXAMPLE = Path(__file__).resolve().parents[2] / "docs" / "owner.example.json"
OWNER_TABLES = (OwnAccount, OwnIdentifier, Party, PartyText, OwnerLinkDecision, OwnerRole)


def example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def write(tmp_path: Path, data: object) -> str:
    path = tmp_path / "owner.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return str(path)


def owner_rows(engine: Engine) -> dict[str, list]:
    with engine.connect() as conn:
        return {
            model.__tablename__: sorted(tuple(r) for r in conn.execute(select(model)))
            for model in OWNER_TABLES
        }


def private_values(data: dict) -> set[str]:
    """Every label, text, income label and last 4 in an owner file."""
    values = set()
    for entry in [*data.get("accounts", []), *data.get("parties", [])]:
        values |= {entry.get("label"), entry.get("income")}
        values |= {*entry.get("texts", []), *entry.get("last4", [])}
    return {v for v in values if isinstance(v, str) and v.strip(" .")}


def assert_private(out: str, data: dict) -> None:
    assert not sorted(v for v in private_values(data) if v in out)


def count(out: str, section: str, what: str) -> int:
    block = re.search(rf"^{section}\n((?:  .*\n)+)", out, flags=re.M).group(1)
    return int(re.search(rf"^  {what}\s+(\d+)$", block, flags=re.M).group(1))


def test_models_repeat_the_engine_vocabulary() -> None:
    # A change on either side needs a migration: the database checks these values.
    assert models.ACCOUNT_KINDS == reconcile.ACCOUNT_KINDS
    assert models.PARTY_KINDS == reconcile.PARTY_KINDS
    assert models.VERDICTS == reconcile.VERDICTS
    assert set(models.OWNER_ROLES) == set(reconcile.ROLES) - {"duplicate"}
    assert set(reconcile.LINK_KINDS) <= set(models.OWNER_LINK_KINDS)


def test_example_file_loads_and_prints_counts_only(run, db_engine: Engine) -> None:
    out = run("owner-load", str(EXAMPLE))
    assert out.startswith("owner-load\n")
    assert [count(out, s, "added") for s in ("accounts", "identifiers", "parties", "texts")] == [
        4,
        9,
        3,
        5,
    ]
    assert re.search(r"^income sources\s+1$", out, flags=re.M)
    assert re.search(
        r"^texts matching no transaction\s+10\n  accounts\[0\]\.texts\[0\]\n", out, re.M
    )
    assert_private(out, example())

    rows = owner_rows(db_engine)
    assert [len(rows[m.__tablename__]) for m in OWNER_TABLES] == [4, 9, 3, 5, 0, 0]
    with sessionmaker(db_engine)() as s:
        assert {a.source for a in s.scalars(select(OwnAccount))} == {"file"}
        assert {t.source for t in s.scalars(select(PartyText))} == {"file"}
        sbi = s.scalar(select(OwnAccount).where(OwnAccount.label == "SBI savings"))
        assert (sbi.kind, sbi.bank, sbi.owner_id) == ("bank_account", "SBI", settings.owner_id)
        identifiers = s.scalars(select(OwnIdentifier).where(OwnIdentifier.own_account_id == sbi.id))
        assert sorted((i.kind, i.value) for i in identifiers) == [
            ("last4", "0003"),
            ("text", "TEST OWNER"),
            ("text", "test.user@oksbi"),
        ]
        parent = s.scalar(select(Party).where(Party.label == "Test Parent"))
        assert (parent.kind, parent.income_label) == ("person", "Pocket money")
        assert s.scalar(select(Party).where(Party.label == "Test Friend")).income_label is None


def test_loading_the_same_file_twice_changes_nothing(run, db_engine: Engine, tmp_path) -> None:
    run("owner-load", str(EXAMPLE))
    before = owner_rows(db_engine)
    out = run("owner-load", str(EXAMPLE))
    assert owner_rows(db_engine) == before
    for section, n in (("accounts", 4), ("identifiers", 9), ("parties", 3), ("texts", 5)):
        assert (count(out, section, "added"), count(out, section, "removed")) == (0, 0)
        assert count(out, section, "unchanged") == n
    with_bom = tmp_path / "bom.json"  # a Windows editor may save a byte order mark
    with_bom.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8-sig")
    run("owner-load", str(with_bom))
    assert owner_rows(db_engine) == before


def test_dry_run_checks_and_saves_nothing(run, db_engine: Engine) -> None:
    out = run("owner-load", str(EXAMPLE), "--dry-run")
    assert (
        out.startswith("owner-load (dry run: nothing saved)")
        and count(out, "parties", "added") == 3
    )
    assert not any(owner_rows(db_engine).values())


def test_a_changed_file_replaces_only_what_changed(run, db_engine: Engine, tmp_path) -> None:
    run("owner-load", str(EXAMPLE))
    with sessionmaker(db_engine)() as s:
        ids = {p.label: p.id for p in s.scalars(select(Party))}
    data = example()
    data["parties"].pop(2)  # Test Mess goes
    moved = data["parties"][1]["texts"].pop(0)  # a text moves from Test Friend to Test Parent
    data["parties"][0]["texts"].append(moved)
    data["parties"][1]["kind"] = "business"
    data["accounts"][3]["label"] = "test WALLET"  # the same entry, label respelt
    data["accounts"].append({"label": "Test FD", "kind": "fd", "bank": "HDFC", "last4": ["0007"]})
    out = run("owner-load", write(tmp_path, data))
    assert [count(out, "parties", w) for w in ("added", "updated", "removed", "unchanged")] == [
        0,
        1,
        1,
        1,
    ]
    assert [count(out, "texts", w) for w in ("added", "removed", "unchanged")] == [1, 2, 3]
    assert [count(out, "accounts", w) for w in ("added", "updated", "unchanged")] == [1, 1, 3]
    with sessionmaker(db_engine)() as s:
        parties = {p.label: p for p in s.scalars(select(Party))}
        assert {label: p.id for label, p in parties.items()} == {
            "Test Parent": ids["Test Parent"],
            "Test Friend": ids["Test Friend"],
        }  # entries that stay keep their ids
        assert parties["Test Friend"].kind == "business"
        owner_of = {t.text: t.party_id for t in s.scalars(select(PartyText))}
        assert owner_of[moved] == ids["Test Parent"] and len(owner_of) == 4
        assert {a.label for a in s.scalars(select(OwnAccount))} >= {"test WALLET", "Test FD"}
    out = run("owner-load", write(tmp_path, {}))  # an empty file removes every file row
    assert count(out, "accounts", "removed") == 5 and not any(owner_rows(db_engine).values())


def test_rows_not_from_a_file_are_left_untouched(run, backup, db_engine: Engine, tmp_path) -> None:
    run("import-sms", "--input", str(backup))
    now = datetime(2026, 1, 21, tzinfo=UTC)
    owner = settings.owner_id
    with sessionmaker(db_engine)() as s:
        a, b = list(s.scalars(select(Transaction.id).order_by(Transaction.id).limit(2)))
        party = Party(owner_id=owner, label="App Party", kind="person", source="app")
        account = OwnAccount(owner_id=owner, label="App Account", kind="wallet", source="app")
        s.add_all([party, account])
        s.flush()
        s.add_all(
            [
                PartyText(owner_id=owner, party_id=party.id, text="TEST APP PERSON", source="app"),
                OwnIdentifier(
                    owner_id=owner,
                    own_account_id=account.id,
                    kind="text",
                    value="TEST APP WALLET",
                    source="app",
                ),
                OwnerRole(
                    transaction_id=a,
                    owner_id=owner,
                    role="ignored",
                    decided_at=now,
                    source="terminal",
                ),
                OwnerLinkDecision(
                    owner_id=owner,
                    kind="duplicate",
                    txn_a=a,
                    txn_b=b,
                    verdict="different",
                    decided_at=now,
                    source="terminal",
                ),
            ]
        )
        s.commit()
    mine = owner_rows(db_engine)

    def without_file_rows() -> dict[str, list]:
        with sessionmaker(db_engine)() as s:
            for model in (OwnIdentifier, PartyText, OwnAccount, Party):
                for row in s.scalars(select(model).where(model.source == "file")):
                    s.delete(row)
                s.flush()
            rows = {
                m.__tablename__: sorted(tuple(r) for r in s.execute(select(m.__table__)))
                for m in OWNER_TABLES
            }
            s.rollback()
        return rows

    for data in (example(), {}):  # load, then remove everything the file brought
        run("owner-load", write(tmp_path, data))
        assert without_file_rows() == mine
    assert owner_rows(db_engine) == mine

    for change, path in (
        ({"label": "app party"}, r"parties\[0\]\.label"),
        ({"texts": ["test app-person"]}, r"parties\[0\]\.texts\[0\]"),
        ({"texts": ["Test App Wallet"]}, r"parties\[0\]\.texts\[0\]"),
    ):
        data = {
            "parties": [{"label": "Test New", "kind": "person", "texts": ["TEST NEW"]} | change]
        }
        out = run("owner-load", write(tmp_path, data), code=2)
        assert re.search(path + ": already used by an entry that is not from a file", out)
        assert "nothing loaded" in out and owner_rows(db_engine) == mine
        assert_private(out, data)


def mutate(change) -> dict:
    data = copy.deepcopy(example())
    change(data)
    return data


def setitem(path: str, value: object):
    """setitem("accounts.0.kind", "x"): a change to the example file."""

    def change(data: dict) -> None:
        *parents, last = path.split(".")
        target = data
        for step in parents:
            target = target[int(step) if step.isdigit() else step]
        target[int(last) if last.isdigit() else last] = value

    return change


SECRET = "TEST SECRET VALUE"
BAD_FILES = [
    ("[1, 2", ["file: line 1, column"]),
    ("[]", ["file: must be an object"]),
    ('{"accounts": [], "accounts": []}', ["file: one object has the same key twice"]),
    (mutate(setitem("decisions", [])), [r"file: 1 unknown key\(s\); allowed: accounts, parties"]),
    (mutate(setitem("accounts", {})), ["accounts: must be a list"]),
    (mutate(setitem("parties", SECRET)), ["parties: must be a list"]),
    (mutate(setitem("accounts.0", SECRET)), [r"accounts\[0\]: must be an object"]),
    (
        mutate(setitem("parties.1.note", SECRET)),
        [r"parties\[1\]: 1 unknown key\(s\); allowed: label"],
    ),
    (mutate(setitem(f"parties.1.{SECRET}", 1)), [r"parties\[1\]: 1 unknown key"]),
    (
        mutate(lambda d: d["accounts"][0].pop("label")),
        [r"accounts\[0\]\.label: must be a non-empty"],
    ),
    (mutate(setitem("accounts.0.label", "  ")), [r"accounts\[0\]\.label: must be a non-empty"]),
    (mutate(setitem("parties.0.label", 7)), [r"parties\[0\]\.label: must be a non-empty string"]),
    (mutate(setitem("parties.0.label", "T" * 81)), [r"parties\[0\]\.label: longer than 80"]),
    (
        mutate(setitem("accounts.1.label", "hdfc SAVINGS")),
        [r"accounts\[1\]\.label: same label as accounts\[0\]"],
    ),
    (
        mutate(setitem("parties.2.label", "Test Parent")),
        [r"parties\[2\]\.label: same label as parties\[0\]"],
    ),
    (
        mutate(setitem("accounts.0.kind", "savings")),
        [r"accounts\[0\]\.kind: must be one of bank_account"],
    ),
    (
        mutate(lambda d: d["parties"][0].pop("kind")),
        [r"parties\[0\]\.kind: must be one of person, business"],
    ),
    (mutate(setitem("parties.0.kind", "wallet")), [r"parties\[0\]\.kind: must be one of person"]),
    (
        mutate(setitem("accounts.0.bank", "HDFC BANK")),
        [r"accounts\[0\]\.bank: must be one of AXIS, HDFC"],
    ),
    (
        mutate(setitem("accounts.3.last4", ["0009"])),
        [r"accounts\[3\]\.bank: needed when last4 is given"],
    ),
    (mutate(setitem("accounts.0.last4", "0001")), [r"accounts\[0\]\.last4: must be a list"]),
    (
        mutate(setitem("accounts.0.last4.1", "12345")),
        [r"accounts\[0\]\.last4\[1\]: must be a string of 4"],
    ),
    (
        mutate(setitem("accounts.0.last4.0", 1234)),
        [r"accounts\[0\]\.last4\[0\]: must be a string of 4"],
    ),
    (
        mutate(setitem("accounts.0.last4.1", "0001")),
        [r"accounts\[0\]\.last4\[1\]: same number as accounts\[0\]\.last4\[0\]"],
    ),
    (
        mutate(lambda d: d["accounts"][1].update(bank="HDFC", last4=["0002"])),
        [r"accounts\[1\]\.last4\[0\]: same number as accounts\[0\]\.last4\[1\]"],
    ),
    (mutate(setitem("accounts.0.texts", SECRET)), [r"accounts\[0\]\.texts: must be a list"]),
    (
        mutate(setitem("parties.0.texts.0", "")),
        [r"parties\[0\]\.texts\[0\]: must be a non-empty string"],
    ),
    (
        mutate(setitem("parties.0.texts.0", 5)),
        [r"parties\[0\]\.texts\[0\]: must be a non-empty string"],
    ),
    (
        mutate(setitem("parties.0.texts.0", "...")),
        [r"parties\[0\]\.texts\[0\]: has no letters or digits"],
    ),
    (
        mutate(setitem("parties.0.texts.0", "T" * 201)),
        [r"parties\[0\]\.texts\[0\]: longer than 200"],
    ),
    (
        mutate(setitem("parties.0.texts.1", "Test.Parent@OKAXIS")),
        [r"parties\[0\]\.texts\[1\]: same text as parties\[0\]\.texts\[0\]"],
    ),
    (
        mutate(setitem("parties.1.texts.0", "test  parent")),
        [r"parties\[1\]\.texts\[0\]: same text as parties\[0\]\.texts\[1\]"],
    ),
    (
        mutate(setitem("parties.2.texts.0", "Test-Owner")),
        [r"parties\[2\]\.texts\[0\]: same text as accounts\[1\]\.texts\[0\]"],
    ),
    (
        mutate(setitem("accounts.3.texts.0", "test.user@oksbi")),
        [r"accounts\[3\]\.texts\[0\]: same text as accounts\[1\]\.texts\[1\]"],
    ),
    (mutate(setitem("accounts.3.texts", [])), [r"accounts\[3\]: needs at least one last4 or text"]),
    (mutate(setitem("parties.2.texts", [])), [r"parties\[2\]\.texts: needs at least one text"]),
    (
        mutate(lambda d: d["parties"][2].pop("texts")),
        [r"parties\[2\]\.texts: needs at least one text"],
    ),
    (
        mutate(setitem("parties.0.income", True)),
        [r"parties\[0\]\.income: must be a non-empty string"],
    ),
    (
        mutate(
            lambda d: (setitem("accounts.0.kind", SECRET)(d), setitem("parties.1.texts.0", "")(d))
        ),
        [r"accounts\[0\]\.kind: must be one of", r"parties\[1\]\.texts\[0\]: must be a non-empty"],
    ),  # every problem is reported, not only the first
]


@pytest.mark.parametrize(("data", "expected"), BAD_FILES)
def test_each_validation_error_names_the_field_and_loads_nothing(
    data, expected: list[str], run, db_engine: Engine, tmp_path: Path
) -> None:
    run("owner-load", str(EXAMPLE))
    before = owner_rows(db_engine)
    out = run("owner-load", write(tmp_path, data), code=2)
    for pattern in expected:
        assert re.search(rf"^{pattern}", out, flags=re.M), out
    assert re.search(r"owner-load: \d+ problem\(s\); nothing loaded", out)
    assert owner_rows(db_engine) == before
    assert SECRET not in out and "T" * 50 not in out
    assert_private(out, example())
    raw = data if isinstance(data, str) else json.dumps(data)
    with pytest.raises(OwnerFileError) as error:
        parse_owner_file(raw)
    assert SECRET not in str(error.value) and SECRET not in "".join(error.value.errors)


def test_file_that_is_missing_or_not_text_is_an_error(run, tmp_path: Path) -> None:
    assert "input not found" in run("owner-load", str(tmp_path / "nope.json"), code=2)
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00\x01")
    assert "file: is not UTF-8 text" in run("owner-load", str(binary), code=2)
