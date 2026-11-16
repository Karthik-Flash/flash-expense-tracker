"""Login and the /api/v1 data API. Local EC key, fake JWKS, no network. Fake values only."""

import json
import re
import time
import uuid
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import cli
from app.api import auth
from app.config import settings
from app.db import get_session
from app.engine.categorise import CATEGORIES
from app.engine.credits import CreditRow, credit_senders
from app.main import allowed_origins, app
from app.models import OwnerRole, Party, Transaction
from app.pipeline.recompute import _LOCKS, owner_lock
from tests.smsdata import FIXTURES, full_rows, write_backup
from tests.test_category_storage import LATER
from tests.test_owner_load import write
from tests.test_storage import OWNER_FILE, PAIR, stored

BASE = "https://test.supabase.co"
SUB_A, SUB_B, SUB_X = "user-a", "user-b", "user-x"
OWNER_A, OWNER_B = settings.owner_id, uuid.UUID("00000000-0000-0000-0000-00000000000b")
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def jwk(key, kid: str) -> dict:
    public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    return public | {"kid": kid, "alg": "ES256", "use": "sig"}


def token(sub: str = SUB_A, key=KEY, kid: str = "k1", alg: str = "ES256", **claims) -> str:
    now = int(time.time())
    body = {"sub": sub, "aud": "authenticated", "iss": f"{BASE}/auth/v1", "exp": now + 600}
    return jwt.encode(body | claims, key, algorithm=alg, headers={"kid": kid})


def bearer(value: str) -> dict:
    return {"Authorization": f"Bearer {value}"}


@pytest.fixture
def jwks(monkeypatch: pytest.MonkeyPatch) -> dict:
    """The fake key set, and how often it was fetched."""
    state = {"keys": [jwk(KEY, "k1")], "fetches": 0}

    def fetch(url: str) -> dict:
        assert url == f"{BASE}/auth/v1/.well-known/jwks.json"
        state["fetches"] += 1
        return {"keys": list(state["keys"])}

    monkeypatch.setattr(auth, "fetch_jwks", fetch)
    monkeypatch.setattr(auth, "keys", auth.KeyCache())
    monkeypatch.setattr(settings, "supabase_url", BASE + "/")
    monkeypatch.setattr(settings, "auth_users", f"{SUB_A}:{OWNER_A}, {SUB_B}:{OWNER_B}")
    return state


@pytest.fixture
def client(db_engine, jwks):
    factory = sessionmaker(db_engine, expire_on_commit=False)

    def session():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def data(run, tmp_path: Path, monkeypatch) -> None:
    """Owner A: the fixture messages and an AutoPay pair. Owner B: one message of its own."""
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", full_rows() + PAIR)))
    monkeypatch.setattr(settings, "owner_id", OWNER_B)
    run("import-sms", "--input", str(write_backup(tmp_path / "b.xml", [LATER])))
    monkeypatch.setattr(settings, "owner_id", OWNER_A)


def get(client, path: str, sub: str = SUB_A, **params):
    return client.get(path, headers=bearer(token(sub)), params=params)


def put(client, path: str, body: dict, sub: str = SUB_A):
    return client.put(path, headers=bearer(token(sub)), json=body)


def all_transactions(client, sub: str = SUB_A, **params) -> list[dict]:
    items, cursor = [], None
    while True:
        page = get(
            client,
            "/api/v1/transactions",
            sub,
            limit=7,
            **params,
            **({"cursor": cursor} if cursor else {}),
        )
        assert page.status_code == 200, page.text
        items += page.json()["items"]
        if not (cursor := page.json()["next_cursor"]):
            return items


def find(client, display_name: str) -> list[dict]:
    return [t for t in all_transactions(client) if t["display_name"] == display_name]


# --- login --------------------------------------------------------------------


def test_every_data_route_needs_a_login(client) -> None:
    paths = app.openapi()["paths"]
    data_routes = [(m, p) for p, ops in paths.items() if p.startswith("/api/v1") for m in ops]
    assert len(data_routes) == 11
    for method, path in data_routes:
        url = re.sub(r"\{[^}]+\}", "1", path)
        response = client.request(method.upper(), url, json={})
        assert response.status_code == 401, (method, path)
        assert response.headers["www-authenticate"] == "Bearer"
    assert {p for p in paths if not p.startswith("/api/v1")} == {"/health", "/health/db"}


@pytest.mark.parametrize(
    ("make", "status"),
    [
        (lambda: token(), 200),
        (lambda: token(exp=int(time.time()) - 60), 401),  # expired
        (lambda: token(iss="https://other.supabase.co/auth/v1"), 401),
        (lambda: token(aud="anon"), 401),
        (lambda: token(sub=SUB_X), 403),  # a real user, not in AUTH_USERS
        (lambda: token(key="TEST SECRET KEY OF THIRTY-TWO BYTES", alg="HS256"), 401),
        (lambda: jwt.encode({"sub": SUB_A}, None, algorithm="none"), 401),
        (lambda: token(kid="k9"), 401),  # unknown key id
        (lambda: token(key=OTHER_KEY), 401),  # right key id, wrong signature
        (lambda: "not.a.token", 401),
    ],
)
def test_token_checks(client, make, status: int) -> None:
    response = client.get("/api/v1/categories", headers=bearer(make()))
    assert response.status_code == status, response.text


def test_header_forms(client) -> None:
    assert client.get("/api/v1/categories").status_code == 401
    assert (
        client.get("/api/v1/categories", headers={"Authorization": f"Basic {token()}"}).status_code
        == 401
    )
    assert client.get("/api/v1/categories", headers={"Authorization": "Bearer "}).status_code == 401
    good = client.get("/api/v1/categories", headers={"Authorization": f"bearer {token()}"})
    assert good.status_code == 200 and len(good.json()) == len(CATEGORIES)


def test_keys_are_cached_and_fetched_again_for_a_new_key_id(client, jwks, monkeypatch) -> None:
    for _ in range(3):
        assert client.get("/api/v1/categories", headers=bearer(token())).status_code == 200
    assert jwks["fetches"] == 1
    jwks["keys"].append(jwk(OTHER_KEY, "k2"))  # the project rotates its key
    rotated = bearer(token(key=OTHER_KEY, kid="k2"))
    assert client.get("/api/v1/categories", headers=rotated).status_code == 401  # within a minute
    assert jwks["fetches"] == 1
    monkeypatch.setattr(auth, "REFRESH_EVERY", 0.0)
    assert client.get("/api/v1/categories", headers=rotated).status_code == 200
    assert jwks["fetches"] == 2
    assert client.get("/api/v1/categories", headers=bearer(token())).status_code == 200
    assert jwks["fetches"] == 2  # a known key id never fetches


def test_keys_that_cannot_be_fetched_give_503(client, monkeypatch) -> None:
    def down(url: str) -> dict:
        raise OSError("TEST network down")

    monkeypatch.setattr(auth, "fetch_jwks", down)
    response = client.get("/api/v1/categories", headers=bearer(token()))
    assert response.status_code == 503 and "TEST" not in response.text


@pytest.mark.parametrize(
    ("url", "users"),
    [("", f"{SUB_A}:{OWNER_A}"), (BASE, ""), (BASE, "no-colon"), (BASE, f"{SUB_A}:not-a-uuid")],
)
def test_missing_settings_give_503_and_health_still_works(client, monkeypatch, url, users) -> None:
    monkeypatch.setattr(settings, "supabase_url", url)
    monkeypatch.setattr(settings, "auth_users", users)
    for path in ("/api/v1/categories", "/api/v1/summary?month=2026-01"):
        assert client.get(path, headers=bearer(token())).status_code == 503
    assert client.get("/health").status_code == 200


def test_cors_allows_only_vercel_and_localhost() -> None:
    origins = [
        "https://flash-expense-tracker.vercel.app",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "https://evil.example",
        "https://flash-expense-tracker.vercel.app.evil.example",
        "http://localhost.evil.example",
    ]
    assert allowed_origins(origins) == origins[:3]


def test_owner_a_cannot_read_or_write_owner_b(client, data, db_engine) -> None:
    mine = all_transactions(client, SUB_A)
    theirs = all_transactions(client, SUB_B)
    assert len(theirs) == 1 and not {t["id"] for t in mine} & {t["id"] for t in theirs}
    other = theirs[0]["id"]
    body = {"category": "travel", "scope": "transaction"}
    assert put(client, f"/api/v1/transactions/{other}/category", body).status_code == 404
    assert put(client, f"/api/v1/transactions/{other}/label", {"label_id": 1}).status_code == 404
    response = client.delete(f"/api/v1/transactions/{other}/label", headers=bearer(token()))
    assert response.status_code == 404
    label = client.post(
        "/api/v1/labels", headers=bearer(token(SUB_B)), json={"name": "Test B"}
    ).json()
    assert get(client, f"/api/v1/labels/{label['id']}").status_code == 404
    assert (
        put(
            client, f"/api/v1/transactions/{mine[0]['id']}/label", {"label_id": label["id"]}
        ).status_code
        == 404
    )
    senders_a = {s["id"] for s in get(client, "/api/v1/senders", status="all").json()}
    senders_b = {s["id"] for s in get(client, "/api/v1/senders", SUB_B, status="all").json()}
    assert senders_a and not senders_a & senders_b
    sender = next(iter(senders_a))
    assert put(client, f"/api/v1/senders/{sender}", {"answer": "ignore"}, SUB_B).status_code == 404
    spent_b = get(client, "/api/v1/summary", SUB_B, month="2026-01").json()["spent_paise"]
    assert spent_b == 55_500
    with sessionmaker(db_engine)() as s:
        assert not list(s.scalars(select(OwnerRole)))  # nothing was written for anyone


# --- reads --------------------------------------------------------------------


def test_summary(client, data) -> None:
    response = get(client, "/api/v1/summary", month="2026-01")
    assert response.status_code == 200
    s = response.json()
    assert set(s) == {
        "month", "spent_paise", "paid_back_paise", "to_confirm", "net_paise", "income_paise",
        "categories", "counts", "stale", "last_recompute_utc",
    }  # fmt: skip
    assert sum(c["amount_paise"] for c in s["categories"]) == s["spent_paise"] > 0
    assert s["net_paise"] == s["spent_paise"] - s["paid_back_paise"]
    assert s["paid_back_paise"] == 0  # nothing confirmed yet (D-076)
    assert s["to_confirm"]["amount_paise"] > 0 and s["to_confirm"]["senders"] >= 2
    assert (
        s["counts"]["uncategorised_spend"] > 0 and s["counts"]["not_counted_yet"] >= 1
    )  # foreign, no parser
    assert s["stale"] is False and s["last_recompute_utc"].endswith("Z")
    assert all(isinstance(c["amount_paise"], int) for c in s["categories"])
    empty = get(client, "/api/v1/summary", month="2026-02").json()
    assert (empty["spent_paise"], empty["categories"]) == (0, [])
    assert get(client, "/api/v1/summary", month="2026-13").status_code == 422
    assert get(client, "/api/v1/summary", month="Jan").status_code == 422
    assert get(client, "/api/v1/summary").status_code == 422


def test_transactions_pages_filters_and_never_shows_message_text(client, data, db_engine) -> None:
    items = all_transactions(client)
    with sessionmaker(db_engine)() as s:
        active = s.scalars(
            select(Transaction.id).where(
                Transaction.owner_id == OWNER_A, Transaction.status == "active"
            )
        ).all()
    assert sorted(t["id"] for t in items) == sorted(active)  # every one, once
    times = [(t["time_utc"], t["id"]) for t in items]
    assert times == sorted(times, reverse=True)
    assert set(items[0]) == {
        "id", "time_utc", "amount_paise", "direction", "display_name", "role", "category",
        "category_name", "category_basis", "label",
    }  # fmt: skip
    text = json.dumps(items)
    for fx in FIXTURES:
        assert not [v for v in (fx["expected"].get("reference"),) if v and v in text]
        assert not [line for line in fx["body"].splitlines() if len(line) > 12 and line in text]
    cash = all_transactions(client, category="cash")
    assert cash and {t["category"] for t in cash} == {"cash"}
    assert len(all_transactions(client, month="2026-02")) == 0
    for bad in (
        {"category": "nope"},
        {"cursor": "abc"},
        {"limit": 0},
        {"limit": 201},
        {"month": "2026"},
    ):
        assert get(client, "/api/v1/transactions", **bad).status_code == 422, bad


# --- writes -------------------------------------------------------------------


def test_merchant_category_covers_older_and_newer_payments(client, data, tmp_path, run) -> None:
    older = find(client, "Test Merchant")
    debit = next(t for t in older if t["direction"] == "debit")
    body = {"category": "groceries", "scope": "merchant"}
    response = put(client, f"/api/v1/transactions/{debit['id']}/category", body)
    assert response.status_code == 200, response.text
    assert response.json()["recompute"]["status"] == "done"
    again = put(client, f"/api/v1/transactions/{debit['id']}/category", body)
    assert again.json()["recompute"]["status"] == "unchanged"  # idempotent
    spends = [t for t in find(client, "Test Merchant") if t["role"] == "spend"]
    assert {(t["category"], t["category_basis"]) for t in spends} == {("groceries", "owner")}

    run("import-sms", "--input", str(write_backup(tmp_path / "later.xml", [LATER])))
    newer = {t["id"]: t for t in find(client, "Test Merchant")}
    (new_id,) = set(newer) - {t["id"] for t in older}
    assert newer[new_id]["category"] == "groceries"

    one_off = put(
        client,
        f"/api/v1/transactions/{new_id}/category",
        {"category": "gifts_donations", "scope": "transaction"},
    )
    assert one_off.status_code == 200
    after = {t["id"]: t["category"] for t in find(client, "Test Merchant") if t["role"] == "spend"}
    assert after.pop(new_id) == "gifts_donations" and set(after.values()) == {"groceries"}
    back = put(
        client,
        f"/api/v1/transactions/{new_id}/category",
        {"category": "groceries", "scope": "merchant"},
    )
    assert back.status_code == 200
    assert {t["category"] for t in find(client, "Test Merchant") if t["role"] == "spend"} == {
        "groceries"
    }


def test_category_validation(client, data) -> None:
    txn = all_transactions(client)[0]["id"]
    url = f"/api/v1/transactions/{txn}/category"
    assert put(client, url, {"category": "nope", "scope": "transaction"}).status_code == 422
    assert put(client, url, {"category": "travel", "scope": "everywhere"}).status_code == 422
    assert put(client, url, {"category": "travel"}).status_code == 422
    assert (
        put(client, url, {"category": "travel", "scope": "transaction", "x": 1}).status_code == 422
    )
    assert (
        put(
            client,
            "/api/v1/transactions/999999/category",
            {"category": "travel", "scope": "transaction"},
        ).status_code
        == 404
    )
    atm = next(t for t in all_transactions(client) if t["category"] == "cash")
    no_text = put(
        client,
        f"/api/v1/transactions/{atm['id']}/category",
        {"category": "travel", "scope": "merchant"},
    )
    assert no_text.status_code == 422 and "merchant" in no_text.json()["detail"]


def test_an_app_write_survives_owner_load_and_recompute(
    client, data, run, tmp_path, db_engine
) -> None:
    debit = next(t for t in find(client, "Test Merchant") if t["direction"] == "debit")
    put(
        client,
        f"/api/v1/transactions/{debit['id']}/category",
        {"category": "health", "scope": "merchant"},
    )
    run("owner-load", write(tmp_path, OWNER_FILE))
    run("recompute")
    assert {t["category"] for t in find(client, "Test Merchant") if t["role"] == "spend"} == {
        "health"
    }
    with sessionmaker(db_engine)() as s:
        party = s.scalar(select(Party).where(Party.label == "Test Merchant"))
        assert (party.source, party.category) == ("app", "health")


def test_senders_confirm_and_net_follows(client, data) -> None:
    listed = get(client, "/api/v1/senders").json()
    assert listed and {s["status"] for s in listed} == {"to_confirm"}
    totals_ = [s["total_paise"] for s in listed]
    assert totals_ == sorted(totals_, reverse=True)
    assert all(
        s["id"].startswith("s_") and "@" not in s["id"] and ":" not in s["id"] for s in listed
    )
    before = get(client, "/api/v1/summary", month="2026-01").json()
    payback = next(s for s in listed if s["role"] == "payback")
    response = put(client, f"/api/v1/senders/{payback['id']}", {"answer": "friend"})
    assert response.status_code == 200, response.text
    after = get(client, "/api/v1/summary", month="2026-01").json()
    assert after["paid_back_paise"] == before["paid_back_paise"] + payback["total_paise"]
    assert after["net_paise"] == before["net_paise"] - payback["total_paise"]
    assert after["to_confirm"]["senders"] == before["to_confirm"]["senders"] - 1
    confirmed = {s["id"]: s for s in get(client, "/api/v1/senders", status="confirmed").json()}
    assert confirmed[payback["id"]]["basis"] == "owner"

    others = get(client, "/api/v1/senders").json()
    income = others[0]
    assert put(client, f"/api/v1/senders/{income['id']}", {"answer": "income"}).status_code == 422
    good = put(
        client, f"/api/v1/senders/{income['id']}", {"answer": "income", "label": "Test Stipend"}
    )
    assert good.status_code == 200
    now = get(client, "/api/v1/summary", month="2026-01").json()
    assert now["income_paise"] == after["income_paise"] + income["total_paise"]
    rest = get(client, "/api/v1/senders").json()
    for s in rest:
        assert put(client, f"/api/v1/senders/{s['id']}", {"answer": "ignore"}).status_code == 200
    assert get(client, "/api/v1/senders").json() == []
    assert put(client, "/api/v1/senders/s_unknown", {"answer": "ignore"}).status_code == 404
    assert put(client, f"/api/v1/senders/{income['id']}", {"answer": "maybe"}).status_code == 422


def test_labels(client, data) -> None:
    created = client.post("/api/v1/labels", headers=bearer(token()), json={"name": "Test Trip"})
    assert created.status_code == 201 and created.json()["created"] is True
    again = client.post("/api/v1/labels", headers=bearer(token()), json={"name": "test trip"})
    assert again.status_code == 200 and again.json()["id"] == created.json()["id"]
    for bad in ({"name": ""}, {"name": "T" * 81}, {}, {"name": "x", "y": 1}):
        assert client.post("/api/v1/labels", headers=bearer(token()), json=bad).status_code == 422
    label = created.json()["id"]
    spends = [t for t in all_transactions(client) if t["role"] == "spend"][:3]
    for t in spends:
        assert (
            put(client, f"/api/v1/transactions/{t['id']}/label", {"label_id": label}).status_code
            == 200
        )
    assert (
        put(
            client, f"/api/v1/transactions/{spends[0]['id']}/label", {"label_id": label}
        ).status_code
        == 200
    )
    assert (
        put(
            client, f"/api/v1/transactions/{spends[0]['id']}/label", {"label_id": 99999}
        ).status_code
        == 404
    )
    assert get(client, "/api/v1/labels").json() == [
        {"id": label, "name": "Test Trip", "transactions": 3}
    ]
    view = get(client, f"/api/v1/labels/{label}").json()
    assert view["spent_paise"] == sum(t["amount_paise"] for t in spends)
    assert sum(c["amount_paise"] for c in view["categories"]) == view["spent_paise"]
    labelled = all_transactions(client, label=label)
    assert {t["id"] for t in labelled} == {t["id"] for t in spends}
    assert {t["label"]["name"] for t in labelled} == {"Test Trip"}
    for _ in range(2):  # idempotent
        response = client.delete(
            f"/api/v1/transactions/{spends[0]['id']}/label", headers=bearer(token())
        )
        assert response.status_code == 200
    assert get(client, "/api/v1/labels").json()[0]["transactions"] == 2
    assert get(client, "/api/v1/labels/99999").status_code == 404


# --- shared pieces ------------------------------------------------------------


def test_credit_senders_group_sort_and_hide_the_key() -> None:
    from datetime import UTC, datetime

    when = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        CreditRow(1, 500, when, "vpa:test.a@okaxis", "test.a@okaxis", "payback", "engine"),
        CreditRow(2, 700, when, "vpa:test.a@okaxis", "test.a@okaxis", "payback", "engine"),
        CreditRow(3, 2000, when, "name:test employer", "Test Employer", "income", "owner"),
        CreditRow(4, 100, when, None, None, "uncertain", "engine"),
        CreditRow(5, 100, when, None, None, "uncertain", "engine"),
        CreditRow(
            6, 900, when, "name:test shop", "Test Shop", "spend", "engine"
        ),  # not a credit role
    ]
    found = credit_senders(rows, "salt-a")
    assert [(s.total_paise, s.count, s.role, s.basis, s.status) for s in found] == [
        (2000, 1, "income", "owner", "confirmed"),
        (1200, 2, "payback", "engine", "to_confirm"),
        (100, 1, "uncertain", "engine", "to_confirm"),
        (100, 1, "uncertain", "engine", "to_confirm"),
    ]
    assert all("test" not in s.id and s.id.startswith("s_") for s in found)
    assert [s.id for s in credit_senders(reversed(rows), "salt-a")] == [s.id for s in found]
    assert not {s.id for s in credit_senders(rows, "salt-b")} & {s.id for s in found}


def test_owner_lock_is_one_lock_per_owner(db_engine) -> None:
    with sessionmaker(db_engine)() as s, owner_lock(s, OWNER_A), owner_lock(s, OWNER_A):
        pass  # the same writer may take it again (a write, then its recompute)
    assert _LOCKS[OWNER_A] is _LOCKS[OWNER_A] and _LOCKS[OWNER_A] is not _LOCKS[OWNER_B]


def test_credit_review_cli(run, data, monkeypatch, db_engine) -> None:
    assert "only to a terminal" in run("credit-review", "--list", code=2)
    monkeypatch.setattr(cli, "is_terminal", lambda: True)
    monkeypatch.setattr(cli, "can_ask", lambda: True)
    listed = run("credit-review", "--list")
    lines = listed.strip().splitlines()
    assert lines[0] == lines[-1] == cli.PRIVATE
    rows = re.findall(
        r"^\[\d+/(\d+)\]\s+(\d+) credits\s+(Rs [\d,]+\.\d\d)  "
        r"last \d{4}-\d\d-\d\d  (\w+) \((\w+)\)",
        listed,
        re.M,
    )
    assert rows and lines[-2] == f"{rows[0][0]} sender(s) to confirm"
    answers = iter(["maybe", "income Test Pocket Money", "friend", "quit"])
    monkeypatch.setattr(cli, "ask", lambda prompt: next(answers))
    out = run("credit-review")
    assert "answer friend, income <label>, ignore, or quit" in out
    assert "saved: 2 answer(s)" in out and re.search(r"^recompute run #\d+ \(owner\)$", out, re.M)
    with sessionmaker(db_engine)() as s:
        labels = {p.income_label for p in s.scalars(select(Party))}
    assert "Test Pocket Money" in labels  # the label keeps its case
    assert {
        d.role_basis for d in stored(db_engine).values() if d.role in ("payback", "income")
    } >= {"owner"}
