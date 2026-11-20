"""People (D-096): name a person, join identifiers ("same as"), separate, role conflicts.
Owner data only; the engine never names or joins anyone. FAKE data only."""

import json
import re
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.engine.parsers import PARSERS
from app.models import (
    ClientOp,
    Label,
    OwnerCategory,
    OwnerRole,
    Party,
    PartyText,
    TxnDerived,
    TxnLabel,
)
from app.pipeline.owner_load import export_owner, parse_owner_file, restore
from tests.apiclient import OWNER_A, all_transactions, bearer, get, put, token
from tests.smsdata import full_rows, write_backup
from tests.test_category_storage import old_hdfc
from tests.test_storage import PAIR

PAYEE, MASKED, OTHER = "Test Payee", "*test@oksbi", "test.user@okaxis"  # FAKE identifiers


def first(client, name: str) -> dict:
    return next(t for t in all_transactions(client) if t["display_name"] == name)


def send(client, method: str, path: str, body=None, key=None):
    headers = bearer(token())
    if key:
        headers["Idempotency-Key"] = str(key)
    return client.request(method, path, headers=headers, json=body)


def snapshot(client) -> dict:
    return get(client, "/api/v1/sync/snapshot").json()


def person(snap: dict, key: str) -> dict:
    return next(p for p in snap["people"] if p["key"] == key)


def count(db_engine, model, *where) -> int:
    with sessionmaker(db_engine)() as s:
        return s.scalar(select(func.count()).select_from(model).where(*where))


def test_name_rename_and_clear(client, data, db_engine) -> None:
    payee = first(client, PAYEE)
    path = f"/api/v1/people/{payee['id']}/name"
    assert put(client, path, {"name": "  Test   Rohit "}).status_code == 200
    named = get(client, f"/api/v1/transactions/{payee['id']}").json()
    assert (named["display_name"], named["identifier"]) == ("Test Rohit", PAYEE)
    p = person(snapshot(client), named["person_id"])
    assert p["named"] and p["name"] == "Test Rohit"
    assert p["identifiers"] == [{"name": PAYEE, "txn_id": payee["id"], "from_file": False}]
    # Naming decides nothing about money: role and category stay the engine's.
    assert (named["role"], named["category"]) == (payee["role"], payee["category"])

    assert put(client, path, {"name": "Test Rohit V"}).status_code == 200
    assert get(client, f"/api/v1/transactions/{payee['id']}").json()["display_name"] == (
        "Test Rohit V"
    )
    for bad in ("", "   ", "T" * 31):
        assert put(client, path, {"name": bad}).status_code == 422, bad

    cleared = client.delete(path, headers=bearer(token()))
    assert cleared.status_code == 200
    back = get(client, f"/api/v1/transactions/{payee['id']}").json()
    assert (back["display_name"], back["identifier"]) == (PAYEE, None)
    assert count(db_engine, Party) == 1  # the party stays (kind unsure), only the name went
    assert client.delete(path, headers=bearer(token())).status_code == 404


def test_join_separate_and_rejoin_keep_history(client, data, db_engine) -> None:
    payee, masked = first(client, PAYEE), first(client, MASKED)
    before = get(client, "/api/v1/senders").json()
    join = f"/api/v1/people/{masked['id']}/join"
    assert put(client, join, {"into": payee["id"]}).status_code == 200  # one side: no credits
    a = get(client, f"/api/v1/transactions/{payee['id']}").json()
    b = get(client, f"/api/v1/transactions/{masked['id']}").json()
    assert a["person_id"] == b["person_id"] and a["person_id"].startswith("p_")
    assert b["role"] == masked["role"]  # still to confirm: nothing was answered
    assert len(get(client, "/api/v1/senders").json()) == len(before)
    p = person(snapshot(client), a["person_id"])
    assert {i["name"] for i in p["identifiers"]} == {PAYEE, MASKED} and p["role"] == "none"
    assert put(client, join, {"into": payee["id"]}).status_code == 409  # already one person

    separate = client.delete(join, headers=bearer(token()))
    assert separate.status_code == 200
    c = get(client, f"/api/v1/transactions/{masked['id']}").json()
    assert c["person_id"] != a["person_id"] and c["identifier"] is None
    assert count(db_engine, PartyText, PartyText.ended_at.is_not(None)) == 1  # kept, ended
    only = client.delete(f"/api/v1/people/{payee['id']}/join", headers=bearer(token()))
    assert only.status_code == 409  # the person's only identifier
    assert client.delete(join, headers=bearer(token())).status_code == 404  # on its own now

    assert put(client, join, {"into": payee["id"]}).status_code == 200  # rejoin: a new row
    again = get(client, f"/api/v1/transactions/{masked['id']}").json()
    assert again["person_id"] == a["person_id"]
    assert (
        count(db_engine, PartyText) == 3
        and count(db_engine, PartyText, PartyText.ended_at.is_(None)) == 2
    )


def test_role_conflict_needs_an_explicit_choice(client, data, db_engine) -> None:
    senders = {s["display_name"]: s for s in get(client, "/api/v1/senders").json()}
    put(client, f"/api/v1/senders/{senders[MASKED]['id']}", {"answer": "friend"})
    put(client, f"/api/v1/senders/{senders[OTHER]['id']}", {"answer": "ignore"})
    masked, other = first(client, MASKED), first(client, OTHER)
    join = f"/api/v1/people/{other['id']}/join"
    texts, roles = count(db_engine, PartyText), count(db_engine, OwnerRole)

    refused = put(client, join, {"into": masked["id"]})
    assert refused.status_code == 409 and "choose" in refused.json()["detail"]
    assert (count(db_engine, PartyText), count(db_engine, OwnerRole)) == (texts, roles)
    assert put(client, join, {"into": masked["id"], "role": "income"}).status_code == 422

    assert put(client, join, {"into": masked["id"], "role": "friend"}).status_code == 200
    joined = get(client, f"/api/v1/transactions/{other['id']}").json()
    assert (joined["role"], joined["role_basis"]) == ("payback", "owner")  # Friend, kept
    with sessionmaker(db_engine)() as s:
        assert s.get(OwnerRole, other["id"]) is None  # its "ignore" gave way, as chosen
    confirmed = get(client, "/api/v1/senders", status="confirmed").json()
    assert [s["display_name"] for s in confirmed].count(MASKED) == 1  # one card per person


def test_choosing_the_joined_sides_answer_applies_it_to_every_credit(client, data) -> None:
    senders = {s["display_name"]: s for s in get(client, "/api/v1/senders").json()}
    put(client, f"/api/v1/senders/{senders[MASKED]['id']}", {"answer": "friend"})
    put(client, f"/api/v1/senders/{senders[OTHER]['id']}", {"answer": "ignore"})
    masked, other = first(client, MASKED), first(client, OTHER)
    body = {"into": masked["id"], "role": "ignore"}
    assert put(client, f"/api/v1/people/{other['id']}/join", body).status_code == 200
    for t in (masked, other):
        assert get(client, f"/api/v1/transactions/{t['id']}").json()["role"] == "ignored"


def test_ledger_and_to_confirm_group_by_person(client, data) -> None:
    masked, other = first(client, MASKED), first(client, OTHER)
    month = masked["time_utc"][:7]
    before = get(client, "/api/v1/summary", month=month).json()
    assert (
        put(client, f"/api/v1/people/{other['id']}/join", {"into": masked["id"]}).status_code == 200
    )
    after = get(client, "/api/v1/summary", month=month).json()
    same_month = other["time_utc"][:7] == month
    assert after["to_confirm"]["amount_paise"] == before["to_confirm"]["amount_paise"]
    assert after["to_confirm"]["senders"] == before["to_confirm"]["senders"] - same_month
    snap = snapshot(client)
    key = get(client, f"/api/v1/transactions/{masked['id']}").json()["person_id"]
    rows = [p for m in snap["months"] for p in m["people"] if p["key"] == key]
    assert rows and all(p["to_confirm_paise"] > 0 for p in rows)
    open_cards = [s for s in snap["todo"]["senders"] if s["person_id"] == key]
    assert len(open_cards) == 1 and open_cards[0]["count"] == 2
    for m in snap["months"]:  # the snapshot still says what /summary says
        summary = get(client, "/api/v1/summary", month=m["month"]).json()
        assert m["summary"] == summary


def test_a_category_alone_never_answers_a_person(client, data) -> None:
    """Before 4E "All from" on a person-like text made a person party and so confirmed its
    credits as paybacks. Now the party has no answer (kind unsure)."""
    masked = first(client, MASKED)
    body = {"category": "gifts_donations", "scope": "merchant"}
    assert put(client, f"/api/v1/transactions/{masked['id']}/category", body).status_code == 200
    after = get(client, f"/api/v1/transactions/{masked['id']}").json()
    assert (after["role"], after["role_basis"]) == (masked["role"], masked["role_basis"])


def test_names_and_joins_survive_reparse_and_a_rebuild(run, client, db_engine, tmp_path):
    old = pytest.MonkeyPatch()  # its own: undo must not undo the login fixture
    old.setitem(PARSERS, "HDFC", old_hdfc())
    run("import-sms", "--input", str(write_backup(tmp_path / "all.xml", full_rows() + PAIR)))
    run("recompute")
    payee, masked = first(client, PAYEE), first(client, MASKED)
    assert (
        put(client, f"/api/v1/people/{masked['id']}/join", {"into": payee["id"]}).status_code == 200
    )
    assert (
        put(client, f"/api/v1/people/{payee['id']}/name", {"name": "Test Rohit"}).status_code == 200
    )
    old.undo()
    assert re.search(r"^reparsed\s+[1-9]", run("reparse"), flags=re.M)
    with sessionmaker(db_engine)() as s:  # derived rows from nothing: only owner text is kept
        s.execute(delete(TxnDerived))
        s.commit()
    run("recompute")
    a = get(client, f"/api/v1/transactions/{payee['id']}").json()
    b = get(client, f"/api/v1/transactions/{masked['id']}").json()
    assert (
        a["person_id"] == b["person_id"] and a["display_name"] == b["display_name"] == "Test Rohit"
    )
    assert b["identifier"] == MASKED


def test_owner_file_texts_stay_with_the_file_and_export_still_works(
    run, client, data, db_engine, tmp_path
):
    file = tmp_path / "owner.json"
    file.write_text(
        '{"parties": [{"label": "Test Friend", "kind": "person", "texts": ["TEST PAYEE"]}]}'
    )
    run("owner-load", str(file))
    payee, masked = first(client, "Test Friend"), first(client, MASKED)
    assert payee["identifier"] == PAYEE  # the file's label is shown, the text under it
    refused = client.delete(f"/api/v1/people/{payee['id']}/join", headers=bearer(token()))
    assert refused.status_code == 409  # the only identifier and from the file
    assert (
        put(client, f"/api/v1/people/{payee['id']}/join", {"into": masked["id"]}).status_code == 409
    )
    assert (
        put(client, f"/api/v1/people/{masked['id']}/join", {"into": payee["id"]}).status_code == 200
    )
    assert (
        put(client, f"/api/v1/people/{payee['id']}/name", {"name": "Test Rohit"}).status_code == 200
    )
    file_side = client.delete(f"/api/v1/people/{payee['id']}/join", headers=bearer(token()))
    assert file_side.status_code == 409 and "owner file" in file_side.json()["detail"]
    run("owner-load", str(file))  # the next file load keeps the app's text and name
    assert (
        get(client, f"/api/v1/transactions/{masked['id']}").json()["display_name"] == "Test Rohit"
    )

    factory = sessionmaker(db_engine, expire_on_commit=False)
    with factory() as s:
        document, _ = export_owner(s, OWNER_A)
    (friend,) = [p for p in document["parties"] if p["label"] == "Test Friend"]
    assert friend["display_name"] == "Test Rohit" and friend["texts"] == ["TEST PAYEE"]
    assert [t["source"] for t in friend["more_texts"]] == ["app"]
    parsed = parse_owner_file(json.dumps(document))
    with factory() as s:
        for model in (PartyText, Party):
            s.execute(delete(model))
        s.execute(delete(OwnerRole))
        for model in (OwnerCategory, TxnLabel, Label):
            s.execute(delete(model))
        s.execute(TxnDerived.__table__.update().values(party_id=None))
        s.commit()
        restore(s, OWNER_A, parsed)
        s.commit()
        (back,) = s.scalars(select(Party).where(Party.label == "Test Friend"))
        assert back.display_name == "Test Rohit"
        assert sorted(
            t.source for t in s.scalars(select(PartyText).where(PartyText.party_id == back.id))
        ) == [
            "app",
            "file",
        ]


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("PUT", "name", {"name": "Test Rohit"}),
        ("DELETE", "name", None),
        ("PUT", "join", "into"),
        ("DELETE", "join", None),
    ],
)
def test_every_new_write_replays_with_its_key(client, data, db_engine, method, suffix, body):
    payee, masked = first(client, PAYEE), first(client, MASKED)
    if suffix == "name" and method == "DELETE":
        put(client, f"/api/v1/people/{payee['id']}/name", {"name": "Test Rohit"})
    if suffix == "join" and method == "DELETE":
        put(client, f"/api/v1/people/{masked['id']}/join", {"into": payee["id"]})
    body = {"into": payee["id"]} if body == "into" else body
    target = masked if suffix == "join" else payee
    path, key = f"/api/v1/people/{target['id']}/{suffix}", uuid.uuid4()
    one = send(client, method, path, body, key)
    rows = (count(db_engine, Party), count(db_engine, PartyText))
    two = send(client, method, path, body, key)
    assert one.status_code == two.status_code == 200 and one.json() == two.json()
    assert (count(db_engine, Party), count(db_engine, PartyText)) == rows
    assert count(db_engine, ClientOp, ClientOp.op_id == key) == 1


def test_a_label_of_31_characters_is_refused_by_the_database_too(db_engine) -> None:
    with sessionmaker(db_engine)() as s:
        s.add(Label(owner_id=OWNER_A, name="T" * 30, source="app"))
        s.commit()
        s.add(Label(owner_id=OWNER_A, name="T" * 31, source="app"))
        with pytest.raises(IntegrityError):
            s.commit()
