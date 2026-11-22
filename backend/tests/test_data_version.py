"""The data version (5B-2, D-140): the snapshot's ETag moves whenever the snapshot does.

The ETag no longer hashes the document; it comes from a counter every write path raises. A
write path that forgot it would leave the phone on a stale copy, so every write route of the
app is run here as the admin (A), and every change of the document must change the ETag.
"""

import uuid

from sqlalchemy import event

from app.models import AppUser
from tests.apiclient import OWNER_B, SUB_A, SUB_B, bearer, token
from tests.test_isolation import CASES, body_for, fill, key, two_users  # noqa: F401
from tests.test_storage import WHEN

PATH = "/api/v1/sync/snapshot"
NOT_FOR_A = {"/api/v1/signup", "/api/v1/ingest/sms", "/api/v1/account/delete"}


def state(client, sub: str = SUB_A) -> tuple[dict, str]:
    answer = client.get(PATH, headers=bearer(token(sub)))
    document = answer.json()
    document.pop("generated_at")
    return document, answer.headers["etag"]


def test_every_write_route_moves_the_etag_with_the_snapshot(client, two_users) -> None:  # noqa: F811
    ids, a = two_users, bearer(token(SUB_A))
    moved = 0
    for (method, template), (body, _) in sorted(CASES.items()):
        if method in ("GET", "HEAD") or template in NOT_FOR_A:
            continue
        before, tag = state(client)
        answer = client.request(
            method, fill(template, ids), headers=a | key(), json=body_for(body, ids)
        )
        assert answer.status_code < 500, (method, template)
        after, new_tag = state(client)
        if after != before:
            moved += 1
            assert new_tag != tag, (method, template, "changed the snapshot, kept the ETag")
    assert moved >= 12  # most writes change something A sees


def test_an_upload_and_a_members_sync_move_the_admins_etag(client, two_users, db_engine) -> None:  # noqa: F811
    _, tag = state(client)
    device = str(uuid.uuid4())
    made = client.post(
        "/api/v1/devices", headers=bearer(token(SUB_A)), json={"device_id": device, "name": "A"}
    )
    phone = {"Authorization": f"Bearer {made.json()['token']}"}
    _, after_register = state(client)
    assert after_register != tag
    sms = {"sender": "VM-HDFCBK-S", "body": "Update! INR 1.00 deposited", "device_msg_id": "1",
           "received_at_utc": WHEN.isoformat()}  # fmt: skip
    assert (
        client.post("/api/v1/ingest/sms", headers=phone, json={"messages": [sms]}).status_code
        == 200
    )
    _, after_upload = state(client)
    assert after_upload != after_register  # the phone's last upload, the newest SMS
    from sqlalchemy.orm import sessionmaker

    with sessionmaker(db_engine)() as s:  # B is seen later: A's member list shows it
        row = s.get(AppUser, SUB_B)
        row.last_seen_at = WHEN
        s.commit()
    _, now = state(client)
    assert now != after_upload
    assert state(client)[1] == now  # nothing else changed: the same ETag again


def test_a_304_is_a_few_small_reads(client, two_users, db_engine) -> None:  # noqa: F811
    document, tag = state(client)
    seen = []
    listener = lambda *args: seen.append(args[2])  # noqa: E731
    event.listen(db_engine, "before_cursor_execute", listener)
    try:
        again = client.get(PATH, headers=bearer(token(SUB_A)) | {"If-None-Match": tag})
    finally:
        event.remove(db_engine, "before_cursor_execute", listener)
    assert again.status_code == 304 and again.content == b""
    print(f"\n304: {len(seen)} statements")  # for the report (pytest -s)
    assert len(seen) <= 12
    assert not any("txn_derived" in s.lower() for s in seen)  # the snapshot was not built
    assert OWNER_B and document  # (fixtures in use)
