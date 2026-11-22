"""Several users (5C, D-128, D-129, D-131): app_users from AUTH_USERS, invite codes, sign-up
through the Supabase Admin API (a stand-in: no network), the admin's lists, the device
tokens of a removed user, and Delete my account. FAKE values only."""

import re
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api import auth, supabase_admin, users
from app.config import settings
from app.db import Base
from app.models import AppUser, AuthDeletion, Invite, RawMessage, Transaction
from app.pipeline import account
from tests.apiclient import OWNER_A, SUB_A, bearer, token
from tests.smsdata import write_backup
from tests.test_category_storage import LATER
from tests.test_devices import UPI_SENT, WHEN, sms

SECRET = "sb_secret_TEST_ONLY_0000"
MEMBER_SUB = "member-sub-0001"


@pytest.fixture
def admin_api(monkeypatch):
    """The Auth Admin API: every call is recorded; `fail` makes the next calls fail."""
    state = {"calls": [], "fail": None, "users": {}}

    def request(method: str, path: str, body=None):
        state["calls"].append((method, path, body))
        if state["fail"]:
            return state["fail"], {}
        if method == "POST":
            if body["email"] in state["users"].values():
                return 422, {"msg": "TEST already registered"}
            uid = f"{MEMBER_SUB}-{len(state['users'])}"
            state["users"][uid] = body["email"]
            return 200, {"id": uid, "email": body["email"]}
        state["users"].pop(path.rsplit("/", 1)[1], None)
        return 200, {}

    monkeypatch.setattr(supabase_admin, "request", request)
    monkeypatch.setattr(settings, "supabase_secret_key", SECRET)
    for name in ("PER_IP", "PER_CODE", "OVERALL"):
        old = getattr(users, name)
        monkeypatch.setattr(users, name, users.Limiter(old.limit, old.window))
    return state


def admin_headers(**claims) -> dict:
    return bearer(token(SUB_A, **claims))


def fresh(sub: str) -> dict:
    return bearer(token(sub, amr=[{"method": "password", "timestamp": int(time.time())}]))


def make_invite(client) -> str:
    answer = client.post("/api/v1/invites", headers=admin_headers())
    assert answer.status_code == 201, answer.text
    return answer.json()["code"]


def join(client, code: str, email: str = "tester@example.invalid", password: str = "test-pass-1"):
    body = {"email": email, "password": password, "code": code}
    return client.post("/api/v1/signup", json=body)


def member(db_engine, sub: str) -> AppUser:
    with sessionmaker(db_engine)() as s:
        return s.get(AppUser, sub)


# --- app_users from AUTH_USERS (D-129) --------------------------------------------------------


def test_the_auth_users_login_becomes_the_admin_then_app_users_is_enough(
    client, db_engine, monkeypatch
):
    assert (
        client.get(
            "/api/v1/categories", headers=admin_headers(email="owner@example.invalid")
        ).status_code
        == 200
    )  # noqa: E501
    row = member(db_engine, SUB_A)
    assert (row.owner_id, row.role, row.email) == (OWNER_A, "admin", "owner@example.invalid")
    monkeypatch.setattr(settings, "auth_users", "")  # the owner removes the env var
    assert client.get("/api/v1/categories", headers=admin_headers()).status_code == 200
    assert (
        client.get("/api/v1/categories", headers=bearer(token("someone-else"))).status_code == 403
    )


# --- invites (D-128) ---------------------------------------------------------------------------


def test_an_invite_is_shown_once_and_stored_hashed(client, db_engine, admin_api) -> None:
    code = make_invite(client)
    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", code)
    with sessionmaker(db_engine)() as s:
        row = s.scalars(select(Invite)).one()
        assert row.code_hash == users.code_hash(code) and code not in row.code_hash
        assert row.expires_at - row.created_at > timedelta(days=6, hours=23)
    listed = client.get("/api/v1/invites", headers=admin_headers()).json()["invites"]
    assert len(listed) == 1 and code not in str(listed) and listed[0]["used_utc"] is None
    assert users.code_hash(code.lower().replace("-", " ")) == users.code_hash(code)


def test_revoke_an_unused_invite_through_the_outbox_and_never_a_used_one(client, admin_api) -> None:
    make_invite(client)
    used = make_invite(client)
    assert join(client, used).status_code == 201
    first, second = client.get("/api/v1/invites", headers=admin_headers()).json()["invites"]
    key = {"Idempotency-Key": str(uuid.uuid4())}
    one = client.delete(f"/api/v1/invites/{first['id']}", headers=admin_headers() | key)
    two = client.delete(f"/api/v1/invites/{first['id']}", headers=admin_headers() | key)
    assert one.status_code == two.status_code == 200 and one.json()["revoked_utc"]
    assert (
        client.delete(f"/api/v1/invites/{second['id']}", headers=admin_headers()).status_code == 409
    )
    assert client.delete("/api/v1/invites/999999", headers=admin_headers()).status_code == 404


# --- sign-up (D-128) ---------------------------------------------------------------------------


def test_signup_makes_a_member_with_its_own_owner(client, db_engine, admin_api) -> None:
    code = make_invite(client)
    assert join(client, code, " Tester@Example.invalid ").status_code == 201
    method, path, body = admin_api["calls"][-1]
    assert (method, path) == ("POST", "/admin/users")
    assert body == {
        "email": "tester@example.invalid",
        "password": "test-pass-1",
        "email_confirm": True,
    }
    uid = next(iter(admin_api["users"]))
    row = member(db_engine, uid)
    assert (
        row.role == "member" and row.owner_id != OWNER_A and row.email == "tester@example.invalid"
    )
    with sessionmaker(db_engine)() as s:
        invite = s.scalars(select(Invite)).one()
        assert invite.used_by == row.owner_id and invite.used_at is not None
    # The member signs in (Supabase) and sees only an empty account of their own.
    snap = client.get("/api/v1/sync/snapshot", headers=bearer(token(uid))).json()
    assert snap["owner_id"] == str(row.owner_id) and snap["transactions"] == []
    assert snap["account"]["role"] == "member" and "admin" not in snap
    for path in ("/api/v1/invites", "/api/v1/members"):
        assert client.get(path, headers=bearer(token(uid))).status_code == 403
    assert client.post("/api/v1/invites", headers=bearer(token(uid))).status_code == 403
    # The code is used: once only.
    again = join(client, code, "other@example.invalid")
    assert again.status_code == 400 and again.json()["detail"] == users.BAD_CODE


@pytest.mark.parametrize("bad", ["expired", "revoked", "unknown"])
def test_a_code_that_does_not_work_says_only_that(client, db_engine, admin_api, bad) -> None:
    code = make_invite(client)
    with sessionmaker(db_engine)() as s:
        row = s.scalars(select(Invite)).one()
        if bad == "expired":
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        if bad == "revoked":
            row.revoked_at = datetime.now(UTC)
        s.commit()
    answer = join(client, "AAAA-BBBB-CCCC" if bad == "unknown" else code)
    assert answer.status_code == 400 and answer.json()["detail"] == users.BAD_CODE
    assert admin_api["calls"] == []  # no login was made


def test_an_email_that_exists_is_never_named(client, db_engine, admin_api) -> None:
    assert join(client, make_invite(client), "taken@example.invalid").status_code == 201
    code = make_invite(client)
    answer = join(client, code, "taken@example.invalid")
    assert answer.status_code == 400 and answer.json()["detail"] == users.NO_ACCOUNT
    assert "taken" not in answer.text and "exist" not in answer.text.lower()
    with sessionmaker(db_engine)() as s:  # the code was not spent
        assert (
            s.scalar(select(Invite.used_at).where(Invite.code_hash == users.code_hash(code)))
            is None
        )
    admin_api["fail"] = 503
    assert join(client, code, "new@example.invalid").status_code == 503


def test_a_failed_save_deletes_the_new_login_again(
    client, db_engine, admin_api, monkeypatch
) -> None:
    code = make_invite(client)
    real = users.AppUser  # a row the database refuses (role CHECK)
    monkeypatch.setattr(users, "AppUser", lambda **kw: real(**kw | {"role": "nobody"}))
    answer = join(client, code)
    assert answer.status_code == 503 and answer.json()["detail"] == users.NO_ACCOUNT
    assert [c[0] for c in admin_api["calls"]] == ["POST", "DELETE"] and admin_api["users"] == {}
    with sessionmaker(db_engine)() as s:
        assert s.scalar(select(Invite.used_at)) is None
        assert s.scalar(select(func.count()).select_from(AppUser)) == 1  # the admin only


def test_signup_is_rate_limited_per_code_and_per_ip(client, admin_api) -> None:
    code = make_invite(client)
    for _ in range(5):
        assert join(client, code, "not-an-email").status_code == 422
    assert join(client, code).status_code == 429  # 5 tries per code an hour
    for i in range(4):
        assert join(client, f"WXYZ-WXYZ-WX{i:02d}").status_code == 400
    limited = join(client, "WXYZ-WXYZ-WXYZ")
    assert limited.status_code == 429 and limited.json()["detail"] == users.TOO_MANY  # 10 per IP


def test_signup_never_shows_the_secret_and_needs_it(client, admin_api, monkeypatch, capsys) -> None:
    code = make_invite(client)
    answer = join(client, code)
    assert SECRET not in answer.text and SECRET not in capsys.readouterr().out
    monkeypatch.setattr(settings, "supabase_secret_key", "")
    assert join(client, make_invite(client), "x@example.invalid").status_code == 503


def test_the_secret_key_goes_on_the_apikey_header(monkeypatch) -> None:
    seen = {}

    class Answer:
        status = 200

        def read(self):
            return b'{"id": "u-1"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        seen.update(req.headers, url=req.full_url, method=req.get_method())
        return Answer()

    monkeypatch.setattr(supabase_admin.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(settings, "supabase_url", "https://test.supabase.co/")
    monkeypatch.setattr(settings, "supabase_secret_key", SECRET)
    assert supabase_admin.create_user("a@example.invalid", "test-pass-1") == "u-1"
    assert seen["Apikey"] == SECRET and "Authorization" not in seen
    assert (
        seen["url"] == "https://test.supabase.co/auth/v1/admin/users" and seen["method"] == "POST"
    )


def test_members_list_counts_only(client, admin_api, data) -> None:
    join(client, make_invite(client))
    listed = client.get("/api/v1/members", headers=admin_headers()).json()["members"]
    assert [m["role"] for m in listed] == ["admin", "member"]
    assert listed[0]["transactions"] > 0 and listed[1]["transactions"] == 0
    assert set(listed[0]) == {
        "email",
        "role",
        "joined_utc",
        "last_seen_utc",
        "transactions",
        "phones",
    }


# --- a removed user's phone (1.7) --------------------------------------------------------------


def test_a_removed_users_device_token_stops(client, db_engine, admin_api) -> None:
    join(client, make_invite(client))
    uid = next(iter(admin_api["users"]))
    body = {"device_id": str(uuid.uuid4()), "name": "TEST PHONE"}
    secret = client.post("/api/v1/devices", headers=bearer(token(uid)), json=body).json()["token"]
    upload = {"messages": [sms()]}
    assert client.post("/api/v1/ingest/sms", headers=bearer(secret), json=upload).status_code == 200
    with sessionmaker(db_engine)() as s:  # the admin removes the member's login by hand
        s.delete(s.get(AppUser, uid))
        s.commit()
    gone = client.post("/api/v1/ingest/sms", headers=bearer(secret), json=upload)
    assert gone.status_code == 401 and gone.json()["detail"] == "device_revoked"
    assert client.get("/api/v1/sync/snapshot", headers=bearer(token(uid))).status_code == 403


# --- delete my account (D-131) -----------------------------------------------------------------


def test_fresh_login_is_a_password_in_the_last_10_minutes() -> None:
    now = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    at = int(now.timestamp())
    assert auth.fresh_login({"amr": [{"method": "password", "timestamp": at - 599}]}, now)
    assert not auth.fresh_login({"amr": [{"method": "password", "timestamp": at - 601}]}, now)
    assert not auth.fresh_login({"amr": [{"method": "token_refresh", "timestamp": at}]}, now)
    assert not auth.fresh_login({}, now)


def test_every_table_has_a_rule_for_deleting_an_account() -> None:
    rules = {t.name: account.placed(t) for t in Base.metadata.sorted_tables}
    assert rules["heartbeat"] == "global" and rules["parse_results"] == "parent"
    assert rules["app_users"] == "owner_id" and rules["invites"] == "invites"
    assert set(rules.values()) <= {"global", "parent", "invites", "owner_id"}


def counts_of(db_engine, owner: uuid.UUID, raw_ids, txn_ids) -> dict[str, int]:
    """Rows of one owner in every table, found from the models."""
    out = {}
    with db_engine.connect() as conn:
        for table in account.tables():
            rule = account.placed(table)
            if rule == "global":
                continue
            if rule == "parent":
                columns, parent = account.BY_PARENT[table.name]
                ids = raw_ids if parent is RawMessage else txn_ids
                where = [table.c[c].in_(ids) for c in columns]
                n = sum(
                    conn.scalar(select(func.count()).select_from(table).where(w)) for w in where
                )
            elif rule == "invites":
                n = conn.scalar(
                    select(func.count()).select_from(table)
                    .where((table.c.used_by == owner) | (table.c.created_by == owner))
                )  # fmt: skip
            else:
                n = conn.scalar(
                    select(func.count()).select_from(table).where(table.c.owner_id == owner)
                )
            out[table.name] = n
    return out


def ids_of(db_engine, owner):
    with sessionmaker(db_engine)() as s:
        raw = list(s.scalars(select(RawMessage.id).where(RawMessage.owner_id == owner)))
        txns = list(s.scalars(select(Transaction.id).where(Transaction.owner_id == owner)))
    return raw, txns


def test_delete_my_account_deletes_every_row_and_the_login(
    run, client, db_engine, admin_api, data, tmp_path
):
    join(client, make_invite(client))
    uid = next(iter(admin_api["users"]))
    owner = member(db_engine, uid).owner_id
    # The member's data: messages from the laptop, a phone, an owner answer, a label.
    run(
        "--owner",
        str(owner),
        "import-sms",
        "--input",
        str(write_backup(tmp_path / "m.xml", [LATER, ("VM-HDFCBK-S", UPI_SENT, WHEN)])),
    )  # noqa: E501
    headers = bearer(token(uid))
    client.post(
        "/api/v1/devices", headers=headers, json={"device_id": str(uuid.uuid4()), "name": "TEST"}
    )
    txn = client.get("/api/v1/sync/snapshot", headers=headers).json()["transactions"][0]["id"]
    put = client.put(
        f"/api/v1/transactions/{txn}/label",
        headers=headers | {"Idempotency-Key": str(uuid.uuid4())},
        json={"new_label": "Test Trip"},
    )  # noqa: E501
    assert put.status_code == 200
    raw_ids, txn_ids = ids_of(db_engine, owner)
    before = counts_of(db_engine, owner, raw_ids, txn_ids)
    assert before["raw_messages"] == 2 and before["devices"] == 1 and before["labels"] == 1
    assert before["app_users"] == before["invites"] == 1 and before["client_ops"] == 1
    admin_before = counts_of(db_engine, OWNER_A, *ids_of(db_engine, OWNER_A))
    admin_before["invites"] -= 1  # the invite the member used goes with the account

    stale = client.post("/api/v1/account/delete", headers=headers, json={"confirm": "DELETE"})
    assert stale.status_code == 409 and stale.json()["detail"] == "fresh_login_required"
    typo = client.post("/api/v1/account/delete", headers=fresh(uid), json={"confirm": "delete"})
    assert typo.status_code == 422
    done = client.post("/api/v1/account/delete", headers=fresh(uid), json={"confirm": "DELETE"})
    assert done.status_code == 200 and done.json()["login_deleted"] is True
    assert ("DELETE", f"/admin/users/{uid}", None) in admin_api["calls"]
    after = counts_of(db_engine, owner, raw_ids, txn_ids)
    assert after == dict.fromkeys(after, 0)  # no row of the owner in any table
    assert counts_of(db_engine, OWNER_A, *ids_of(db_engine, OWNER_A)) == admin_before
    with sessionmaker(db_engine)() as s:
        assert s.scalar(select(func.count()).select_from(AuthDeletion)) == 0
    assert client.get("/api/v1/sync/snapshot", headers=headers).status_code == 403


def test_a_login_that_cannot_be_deleted_waits_for_auth_cleanup(run, client, db_engine, admin_api):
    join(client, make_invite(client))
    uid = next(iter(admin_api["users"]))
    admin_api["fail"] = 503
    done = client.post("/api/v1/account/delete", headers=fresh(uid), json={"confirm": "DELETE"})
    assert done.status_code == 200 and done.json()["login_deleted"] is False
    assert member(db_engine, uid) is None  # the data deletion stands
    with sessionmaker(db_engine)() as s:
        row = s.get(AuthDeletion, uid)
        assert row.attempts == 1 and row.last_error == "unavailable"
    out = run("auth-cleanup", code=1)
    assert "pending 1, deleted 0, still pending 1" in out and uid not in out
    admin_api["fail"] = None
    assert "pending 1, deleted 1, still pending 0" in run("auth-cleanup")
    assert uid not in admin_api["users"]


def test_the_admin_cannot_delete_their_own_account(client, admin_api) -> None:
    answer = client.post("/api/v1/account/delete", headers=fresh(SUB_A), json={"confirm": "DELETE"})
    assert answer.status_code == 409 and answer.json()["detail"] == "admin_cannot_delete"


# --- owner commands (D-130) --------------------------------------------------------------------


def test_owner_commands_default_to_the_admin_or_take_owner(
    run, client, db_engine, tmp_path, monkeypatch
):
    client.get("/api/v1/categories", headers=admin_headers())  # the admin row exists
    other = uuid.uuid4()
    monkeypatch.setattr(settings, "owner_id", other)  # OWNER_ID says someone else
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", [LATER])))
    run(
        "--owner",
        str(other),
        "import-sms",
        "--input",
        str(write_backup(tmp_path / "b.xml", [("VM-HDFCBK-S", UPI_SENT, WHEN)])),
    )  # noqa: E501
    with sessionmaker(db_engine)() as s:
        owners = dict(
            s.execute(select(RawMessage.owner_id, func.count()).group_by(RawMessage.owner_id)).all()
        )  # noqa: E501
        assert owners == {OWNER_A: 1, other: 1}
    assert settings.owner_id == other  # restored after each run
