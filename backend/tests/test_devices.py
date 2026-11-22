"""Devices and bank-only SMS ingest (D-122, D-123, D-126). FAKE messages only.

A phone registers with the owner's login and gets a device token once (stored hashed). The
token uploads bank SMS and can call nothing else. Uploads are stored exactly as import-sms
stores them, so the same SMS from the laptop and from the phone is one raw message.
"""

import dataclasses
import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api import devices as dev
from app.config import settings
from app.engine.parsers import PARSERS
from app.main import app
from app.models import (
    ClientOp,
    Device,
    ImportBatch,
    OwnerCategory,
    RawMessage,
    RecomputeMark,
    Transaction,
    TransactionSource,
)
from tests.apiclient import OWNER_B, SUB_B, bearer, get, token
from tests.smsdata import FIXTURES, write_backup
from tests.statements import statement_text, upi

INGEST = "/api/v1/ingest/sms"
WHEN = datetime(2026, 3, 10, 6, 0, 0, 123000, tzinfo=UTC)  # milliseconds matter: the hash
UPI_SENT = (
    "Sent Rs.250.00\nFrom HDFC Bank A/C *0001\nTo TEST CAFE NEW\nOn 10/03/26\nRef 612300000002\n"
    "Not You?\nCall 18000000001/SMS BLOCK UPI to 9000000001\n"
)


def sms(body: str = UPI_SENT, sender: str = "VM-HDFCBK-S", when: datetime = WHEN, n: int = 1):
    return {
        "sender": sender,
        "body": body,
        "received_at_utc": when.isoformat().replace("+00:00", "Z"),
        "device_msg_id": str(n),
    }


def register(client, sub: str = "user-a", device_id: uuid.UUID | None = None, name="TEST PHONE"):
    body = {"device_id": str(device_id or uuid.uuid4()), "name": name}
    return client.post("/api/v1/devices", headers=bearer(token(sub)), json=body)


def upload(client, device_token: str, *messages: dict):
    return client.post(INGEST, headers=bearer(device_token), json={"messages": list(messages)})


def statuses(answer) -> list[str]:
    assert answer.status_code == 200, answer.text
    return [r["status"] for r in answer.json()["results"]]


def count(db_engine, model, *where) -> int:
    with sessionmaker(db_engine)() as s:
        return s.scalar(select(func.count()).select_from(model).where(*where))


@pytest.fixture
def phone(client) -> str:
    answer = register(client)
    assert answer.status_code == 201, answer.text
    return answer.json()["token"]


# --- devices -------------------------------------------------------------------------------


def test_register_returns_a_token_once_and_stores_only_its_hash(client, db_engine) -> None:
    device_id = uuid.uuid4()
    answer = register(client, device_id=device_id, name="  TEST   PHONE  ")
    assert answer.status_code == 201
    body = answer.json()
    secret = body["token"]
    assert len(secret) >= 43 and re.fullmatch(r"[A-Za-z0-9_-]+", secret)  # 256 random bits
    assert body["device"]["created_utc"].endswith("Z")
    assert body["device"] | {"created_utc": None} == {
        "device_id": str(device_id), "name": "TEST PHONE", "created_utc": None,
        "last_seen_utc": None, "revoked_utc": None,
    }  # fmt: skip
    with sessionmaker(db_engine)() as s:
        row = s.scalars(select(Device)).one()
        assert row.token_hash == hashlib.sha256(secret.encode()).hexdigest()
        assert secret not in {row.token_hash, row.name, str(row.device_id)}
    listed = get(client, "/api/v1/devices").json()["devices"]
    assert listed == [body["device"]] and "token" not in str(listed)


def test_registering_again_replaces_the_token(client, db_engine) -> None:
    device_id = uuid.uuid4()
    first = register(client, device_id=device_id).json()["token"]
    second = register(client, device_id=device_id).json()["token"]
    assert first != second and count(db_engine, Device) == 1
    assert upload(client, first, sms()).status_code == 401
    assert statuses(upload(client, second, sms())) == ["stored"]


def test_a_name_is_required_and_bounded(client) -> None:
    assert register(client, name="   ").status_code == 422
    long = register(client, name="X" * 80)
    assert long.status_code == 201 and long.json()["device"]["name"] == "X" * 60


def test_revoke_stops_uploads_and_is_an_outbox_write(client, phone, db_engine) -> None:
    device_id = get(client, "/api/v1/devices").json()["devices"][0]["device_id"]
    key = str(uuid.uuid4())
    headers = bearer(token()) | {"Idempotency-Key": key}
    one = client.delete(f"/api/v1/devices/{device_id}", headers=headers)
    two = client.delete(f"/api/v1/devices/{device_id}", headers=headers)  # a resend: replayed
    assert one.status_code == two.status_code == 200 and one.json() == two.json()
    assert one.json()["revoked_utc"] and count(db_engine, ClientOp) == 1
    refused = upload(client, phone, sms())
    assert refused.status_code == 401 and refused.json()["detail"] == "device_revoked"
    again = client.delete(f"/api/v1/devices/{device_id}", headers=bearer(token()))
    assert again.json()["revoked_utc"] == one.json()["revoked_utc"]  # revoked once
    assert count(db_engine, RawMessage) == 0


def test_another_owners_device_is_not_found(client, phone) -> None:
    device_id = get(client, "/api/v1/devices").json()["devices"][0]["device_id"]
    other = client.delete(f"/api/v1/devices/{device_id}", headers=bearer(token(SUB_B)))
    assert other.status_code == 404
    assert get(client, "/api/v1/devices", SUB_B).json()["devices"] == []
    assert statuses(upload(client, phone, sms())) == ["stored"]


def test_the_device_token_calls_nothing_but_the_ingest(client, phone) -> None:
    paths = app.openapi()["paths"]
    routes = [(m, p) for p, ops in paths.items() if p.startswith("/api/v1") for m in ops]
    for method, path in routes:
        if path in (INGEST, "/api/v1/signup"):  # sign-up takes no token at all (5C)
            continue
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()) if "device" in path else "1", path)
        answer = client.request(method.upper(), url, headers=bearer(phone), json={})
        assert answer.status_code == 401, (method, path)
    # And a login token is no device token.
    assert upload(client, token(), sms()).status_code == 401
    assert client.post(INGEST, json={"messages": [sms()]}).status_code == 401
    assert upload(client, "not-a-token", sms()).json()["detail"] == "invalid device token"


# --- ingest --------------------------------------------------------------------------------


def test_only_bank_messages_are_stored(client, phone, db_engine) -> None:
    answer = upload(
        client,
        phone,
        sms(n=1),
        sms("Hello from a TEST friend", sender="+919000000001", n=2),
        sms("Your TEST CO order is on the way", sender="AB-TESTCO-S", n=3),
        sms("Rs 33 debited from A/c XX0009 on 20-01-26", sender="VM-PHONPE-S", n=4),  # an app
        sms("123456 is your OTP for txn of Rs 33 at TEST STORE", n=5),
        sms("Get 10% cashback on TEST OFFER. Apply now", sender="VM-HDFCBK-P", n=6),
    )
    assert statuses(answer) == [
        "stored", "refused_not_bank", "refused_not_bank", "refused_not_bank",
        "refused_filtered", "refused_filtered",
    ]  # fmt: skip
    assert [r["device_msg_id"] for r in answer.json()["results"]] == list("123456")
    assert answer.json()["counts"] == {
        "stored": 1, "duplicate": 0, "refused_not_bank": 3, "refused_filtered": 2,
    }  # fmt: skip
    with sessionmaker(db_engine)() as s:
        raw = s.scalars(select(RawMessage)).one()
        assert (raw.source, raw.sender_core, raw.body) == ("live_sms", "HDFCBK", UPI_SENT)
        assert raw.received_at == WHEN
        assert s.scalars(select(Transaction)).one().amount_paise == 25000
        batch = s.scalars(select(ImportBatch)).one()
        assert (batch.source, batch.status) == ("live_sms", "done")
        assert s.get(RecomputeMark, settings.owner_id) is not None  # the next read recomputes
        assert s.scalars(select(Device)).one().last_seen_at is not None


def test_every_bank_fixture_is_stored_and_parsed_as_on_import(client, phone, db_engine) -> None:
    fixtures = [sms(f["body"], f["sender"], datetime.fromisoformat(f["received_at"]), i)
                for i, f in enumerate(FIXTURES)]  # fmt: skip
    answer = upload(client, phone, *fixtures)
    assert set(statuses(answer)) == {"stored"}
    assert count(db_engine, RawMessage) == len(FIXTURES)


def test_the_same_message_twice_is_one(client, phone, db_engine) -> None:
    assert statuses(upload(client, phone, sms(), sms(n=2))) == ["stored", "duplicate"]
    assert statuses(upload(client, phone, sms(n=3))) == ["duplicate"]
    assert count(db_engine, RawMessage) == 1 and count(db_engine, Transaction) == 1


def test_laptop_import_then_phone_upload_is_one_message(run, client, phone, tmp_path, db_engine):
    run(
        "import-sms",
        "--input",
        str(write_backup(tmp_path / "a.xml", [("VM-HDFCBK-S", UPI_SENT, WHEN)])),
    )  # noqa: E501
    assert statuses(upload(client, phone, sms())) == ["duplicate"]
    # The other way round: the phone first, then the laptop's export.
    later = WHEN + timedelta(minutes=5)
    body = UPI_SENT.replace("612300000002", "612300000009")
    assert statuses(upload(client, phone, sms(body, when=later))) == ["stored"]
    out = run(
        "import-sms",
        "--input",
        str(write_backup(tmp_path / "b.xml", [("VM-HDFCBK-S", body, later)])),
    )  # noqa: E501
    assert re.search(r"duplicate\s+1\b", out) and count(db_engine, RawMessage) == 2
    assert count(db_engine, Transaction) == 2


def test_a_different_millisecond_is_another_message(client, phone, db_engine) -> None:
    """The phone must send the inbox row's date exactly: it is part of the content hash."""
    other = WHEN + timedelta(milliseconds=1)
    assert statuses(upload(client, phone, sms(), sms(when=other, n=2))) == ["stored", "stored"]
    assert count(db_engine, Transaction) == 1  # the reference still makes them one payment


@pytest.mark.parametrize(
    "messages",
    [
        [],  # at least one
        [sms(n=i) for i in range(501)],  # at most 500
        [sms("x" * 2049)],  # a body of at most 2 KB
        [sms(chr(0x20B9) * 700)],  # 700 characters, 2100 bytes
        [sms() | {"received_at_utc": "2026-03-10T06:00:00"}],  # no time zone
        [sms() | {"extra": 1}],
        [{k: v for k, v in sms().items() if k != "device_msg_id"}],
    ],
)
def test_batch_and_size_limits(client, phone, db_engine, messages) -> None:
    answer = client.post(INGEST, headers=bearer(phone), json={"messages": messages})
    assert answer.status_code == 422
    assert count(db_engine, RawMessage) == 0


def test_500_messages_and_a_2_kb_body_are_accepted(client, phone, db_engine) -> None:
    batch = [sms(when=WHEN + timedelta(seconds=i), n=i) for i in range(499)]
    batch.append(sms("Hello " + "x" * 2042, n=499))  # 2048 bytes, an amount-free notice
    assert set(statuses(upload(client, phone, *batch))) == {"stored"}
    assert count(db_engine, RawMessage) == 500


def test_an_upload_shows_in_the_next_snapshot(client, data, phone) -> None:
    before = get(client, "/api/v1/sync/snapshot").json()
    upload(client, phone, sms())
    after = get(client, "/api/v1/sync/snapshot").json()
    old = {t["id"] for t in before["transactions"]}
    new = [t for t in after["transactions"] if t["id"] not in old]
    assert [(t["amount_paise"], t["role"]) for t in new] == [(25000, "spend")]  # recomputed
    assert after["devices"][0]["last_seen_utc"] and after["sms"]["newest_utc"]


def test_the_request_log_never_holds_a_body_or_a_token(client, phone, capsys) -> None:
    from app import requestlog

    lines = []
    handler = requestlog.log.handlers[0]
    emit = handler.emit
    handler.emit = lambda record: lines.append(record.getMessage())
    try:
        upload(client, phone, sms())
    finally:
        handler.emit = emit
    assert lines == [lines[0]] and lines[0].startswith("POST /api/v1/ingest/sms 200 ")
    assert phone not in lines[0] and "TEST CAFE" not in lines[0] and "250" not in lines[0]


def test_owner_b_uploads_into_owner_b(client, db_engine) -> None:
    secret = register(client, SUB_B).json()["token"]
    assert statuses(upload(client, secret, sms())) == ["stored"]
    with sessionmaker(db_engine)() as s:
        assert s.scalars(select(RawMessage.owner_id)).one() == OWNER_B


# --- statement rows keep their id (D-126) --------------------------------------------------

DAY = "10/03/26"
LINES = [
    (DAY, upi("TEST CAFE NEW", "cafe@okaxis", "612300000002"), "250.00", "", "0"),
    (DAY, "CHQ PAID-TEST LANDLORD", "4000.00", "", "0"),
]
NETBANKING = ("Payment Successful! Rs. 4000.00 from A/c **********0001 to TEST LANDLORD via "
              "HDFC Bank NetBanking. Not you?Call 18000000001")  # fmt: skip


def statement_rows(run, tmp_path, factory) -> dict[int, int]:
    """Import the statement; {amount: transaction id} of its two rows."""
    path = tmp_path / "statement.txt"
    path.write_text(statement_text(LINES), encoding="utf-8")
    run("statement-import", "--file", str(path), "--apply")
    with factory() as s:
        return dict(s.execute(select(Transaction.amount_paise, Transaction.id)).all())


def test_an_sms_keeps_the_statement_rows_id_and_owner_data(
    run, client, phone, tmp_path, db_engine, monkeypatch
) -> None:
    factory = sessionmaker(db_engine, expire_on_commit=False)
    ids = statement_rows(run, tmp_path, factory)
    assert set(ids) == {25000, 400000}
    for amount, txn in ids.items():  # the owner answers on the statement rows first
        put = client.put(
            f"/api/v1/transactions/{txn}/category", headers=bearer(token()),
            json={"category": "travel", "scope": "transaction"},
        )  # fmt: skip
        assert put.status_code == 200, (amount, put.text)
    # By reference (the phone) and by amount and day (the laptop, no reference in the SMS).
    assert statuses(upload(client, phone, sms())) == ["stored"]
    run("import-sms", "--input", str(write_backup(tmp_path / "n.xml", [
        ("VM-HDFCBK-S", NETBANKING, WHEN + timedelta(hours=1)),
    ])))  # fmt: skip
    # A later parser version reparses both SMS: the ids still hold.
    hdfc = PARSERS["HDFC"]
    monkeypatch.setitem(PARSERS, "HDFC", dataclasses.replace(hdfc, version="hdfc-9.9.9"))
    run("reparse")
    with factory() as s:
        active = dict(
            s.execute(
                select(Transaction.amount_paise, Transaction.id).where(
                    Transaction.status == "active"
                )
            ).all()
        )
        assert active == ids  # the same two transactions, no new one
        for txn in ids.values():
            assert s.get(OwnerCategory, txn).category == "travel"
            sources = s.scalars(
                select(RawMessage.source)
                .join(TransactionSource, TransactionSource.raw_message_id == RawMessage.id)
                .where(TransactionSource.transaction_id == txn)
            ).all()
            assert sorted(sources) in (["live_sms", "statement"], ["sms_backup", "statement"])
            assert "statement" not in s.get(Transaction, txn).hints  # the SMS's words now
    items = {t["id"]: t for t in client.get(
        "/api/v1/sync/snapshot", headers=bearer(token())).json()["transactions"]}  # fmt: skip
    assert {items[i]["category"] for i in ids.values()} == {"travel"}


def test_refusal_reasons_match_import_skips() -> None:
    assert dev.refusal("VM-HDFCBK-S", "Sent Rs.1") is None
    assert dev.refusal("JD-SBIUPI-T", "Sent Rs.1") is None
    assert dev.refusal("VK-SBIUPI-P", "Sent Rs.1") == "refused_filtered"
    assert dev.refusal("VM-PHONPE-S", "Sent Rs.1") == "refused_not_bank"
    assert dev.refusal("ABC123@RBM.GOOG", "Sent Rs.1") == "refused_not_bank"
