"""Login and the /api/v1 data API. Local EC key, fake JWKS, no network. Fake values only."""

import json
import re
import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import cli
from app.api import auth, v1
from app.config import settings
from app.engine.categorise import CATEGORIES
from app.engine.credits import CreditRow, credit_senders
from app.engine.reconcile import COUNTED
from app.main import allowed_origins, app
from app.models import OwnerRole, Party, Transaction
from app.pipeline.recompute import _LOCKS, owner_lock
from tests.apiclient import (
    BASE,
    OTHER_KEY,
    OWNER_A,
    OWNER_B,
    SUB_A,
    SUB_B,
    SUB_X,
    all_transactions,
    bearer,
    find,
    get,
    jwk,
    put,
    token,
)
from tests.smsdata import FIXTURES, write_backup
from tests.test_category_storage import LATER
from tests.test_owner_load import write
from tests.test_storage import OWNER_FILE, stored

# --- login --------------------------------------------------------------------


def test_every_data_route_needs_a_login(client) -> None:
    paths = app.openapi()["paths"]
    data_routes = [(m, p) for p, ops in paths.items() if p.startswith("/api/v1") for m in ops]
    # 4E: people name, clear name, join, separate. 4F-A: check, ignore, count again.
    # 4A: a transfer answer.
    assert len(data_routes) == 22
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
        "categories", "counts", "stale", "last_recompute_utc", "previous",
    }  # fmt: skip
    assert s["previous"] == {"month": "2025-12", "whole": True, "spent_paise": 0, "categories": []}
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


@pytest.mark.parametrize("day", [1, 10, 17, 28])
def test_summary_previous_is_last_month_up_to_the_same_ist_day(
    client, data, monkeypatch, day
) -> None:
    january = get(client, "/api/v1/summary", month="2026-01").json()
    # 1 March 00:00 IST is 28 Feb 18:30 UTC: February is past, so January counts whole.
    monkeypatch.setattr(v1, "_now", lambda: datetime(2026, 2, 28, 18, 30, tzinfo=UTC))
    assert get(client, "/api/v1/summary", month="2026-02").json()["previous"] == {
        "month": "2026-01",
        "whole": True,
        "spent_paise": january["spent_paise"],
        "categories": january["categories"],
    }
    # Day `day` of February, 23:59 IST: January up to its day `day`, both included.
    monkeypatch.setattr(v1, "_now", lambda: datetime(2026, 2, day, 18, 29, tzinfo=UTC))
    cut = get(client, "/api/v1/summary", month="2026-02").json()["previous"]
    expected = sum(
        COUNTED[t["role"]][1] * t["amount_paise"]
        for t in all_transactions(client, month="2026-01")
        if COUNTED.get(t["role"], ("",))[0] == "spent" and ist_day(t["time_utc"]) <= day
    )
    assert (cut["month"], cut["whole"], cut["spent_paise"]) == ("2026-01", False, expected)
    assert sum(c["amount_paise"] for c in cut["categories"]) == expected
    if day == 10:
        assert 0 < expected < january["spent_paise"]
    # 31 March: February has 28 days, so all of it.
    monkeypatch.setattr(v1, "_now", lambda: datetime(2026, 3, 31, 6, tzinfo=UTC))
    march = get(client, "/api/v1/summary", month="2026-03").json()["previous"]
    assert (march["month"], march["whole"]) == ("2026-02", False)


def ist_day(time_utc: str) -> int:
    return (datetime.fromisoformat(time_utc) + timedelta(hours=5, minutes=30)).day


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
        "id", "time_utc", "amount_paise", "direction", "display_name", "identifier",
        "person_id", "role", "role_basis", "category", "category_name", "category_basis", "label",
        "generic", "check",
    }  # fmt: skip
    for t in items[:5]:  # one transaction by id: the same item
        assert get(client, f"/api/v1/transactions/{t['id']}").json() == t
    assert get(client, "/api/v1/transactions/999999").status_code == 404
    theirs = all_transactions(client, SUB_B)[0]["id"]
    assert get(client, f"/api/v1/transactions/{theirs}").status_code == 404
    person = {t["person_id"] for t in items if t["display_name"] == "Person_901"}
    assert len(person) == 1 and None not in person  # two payments, one person
    assert {t["person_id"] for t in items if t["category"] == "cash"} == {None}  # no text
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
    assert response.json()["recompute"]["status"] == "deferred"  # D-106
    again = put(client, f"/api/v1/transactions/{debit['id']}/category", body)
    assert again.json()["recompute"]["status"] == "deferred"  # idempotent: the read decides
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
    for bad in ("  ", "S" * 31):
        body = {"answer": "income", "label": bad}
        assert put(client, f"/api/v1/senders/{income['id']}", body).status_code == 422
    good = put(
        client, f"/api/v1/senders/{income['id']}", {"answer": "income", "label": " Test  Stipend"}
    )
    assert good.status_code == 200
    now = get(client, "/api/v1/summary", month="2026-01").json()
    assert now["income_paise"] == after["income_paise"] + income["total_paise"]
    confirmed = {s["id"]: s for s in get(client, "/api/v1/senders", status="confirmed").json()}
    assert confirmed[income["id"]]["income_label"] == "Test Stipend"
    assert confirmed[payback["id"]]["income_label"] is None
    rest = get(client, "/api/v1/senders").json()
    for s in rest:
        assert put(client, f"/api/v1/senders/{s['id']}", {"answer": "ignore"}).status_code == 200
    assert get(client, "/api/v1/senders").json() == []
    ignored = get(client, "/api/v1/senders", status="ignored").json()
    assert {s["id"] for s in ignored} == {s["id"] for s in rest}
    assert {(s["status"], s["role"]) for s in ignored} == {("ignored", "ignored")}
    assert put(client, "/api/v1/senders/s_unknown", {"answer": "ignore"}).status_code == 404
    assert put(client, f"/api/v1/senders/{income['id']}", {"answer": "maybe"}).status_code == 422

    # An ignored sender can be answered again.
    back = ignored[0]
    assert put(client, f"/api/v1/senders/{back['id']}", {"answer": "friend"}).status_code == 200
    assert back["id"] in {
        s["id"] for s in get(client, "/api/v1/senders", status="confirmed").json()
    }


def test_reset_sender_returns_it_to_confirm(client, data, db_engine) -> None:
    listed = get(client, "/api/v1/senders").json()
    start = get(client, "/api/v1/summary", month="2026-01").json()
    payback = next(s for s in listed if s["role"] == "payback")
    other = next(s for s in listed if s["id"] != payback["id"])
    put(client, f"/api/v1/senders/{payback['id']}", {"answer": "friend"})
    put(client, f"/api/v1/senders/{other['id']}", {"answer": "ignore"})
    assert get(client, "/api/v1/senders").json() != listed
    for s in (payback, other):
        response = client.delete(f"/api/v1/senders/{s['id']}", headers=bearer(token()))
        assert response.status_code == 200, response.text
        assert response.json()["recompute"]["status"] == "deferred"  # D-106
    assert get(client, "/api/v1/senders").json() == listed
    end = get(client, "/api/v1/summary", month="2026-01").json()
    assert {k: v for k, v in end.items() if k != "last_recompute_utc"} == {
        k: v for k, v in start.items() if k != "last_recompute_utc"
    }
    with sessionmaker(db_engine)() as s:  # the party made for the answer is gone
        assert not list(s.scalars(select(OwnerRole))) and not list(s.scalars(select(Party)))
    again = client.delete(f"/api/v1/senders/{payback['id']}", headers=bearer(token()))
    assert again.json()["recompute"]["status"] == "deferred"  # idempotent: the read decides
    gone = client.delete("/api/v1/senders/s_unknown", headers=bearer(token()))
    assert gone.status_code == 404
    theirs = client.delete(f"/api/v1/senders/{payback['id']}", headers=bearer(token(SUB_B)))
    assert theirs.status_code == 404


def test_reset_sender_keeps_a_category_default(client, data) -> None:
    """A party that also holds the owner's category keeps it; its credits are to confirm:
    the party has no answer any more (kind unsure), so the engine's own guess is back."""
    payback = next(s for s in get(client, "/api/v1/senders").json() if s["role"] == "payback")
    credit = next(t for t in all_transactions(client) if t["role"] == "payback")
    body = {"category": "gifts_donations", "scope": "merchant"}
    assert put(client, f"/api/v1/transactions/{credit['id']}/category", body).status_code == 200
    put(client, f"/api/v1/senders/{payback['id']}", {"answer": "friend"})
    client.delete(f"/api/v1/senders/{payback['id']}", headers=bearer(token()))
    after = get(client, f"/api/v1/transactions/{credit['id']}").json()
    assert (after["role"], after["role_basis"], after["category"]) == (
        "payback",
        "engine",
        "people",
    )
    assert payback["id"] in {s["id"] for s in get(client, "/api/v1/senders").json()}


def test_labels(client, data) -> None:
    def post(name) -> object:
        return client.post("/api/v1/labels", headers=bearer(token()), json={"name": name})

    created = post("  Test   Trip ")  # trimmed, inner spaces joined (as the client does)
    assert created.status_code == 201 and created.json()["name"] == "Test Trip"
    for same in ("test trip", "TEST  TRIP", " Test Trip"):  # any case: 409
        assert post(same).status_code == 409
    assert post("T" * 30).status_code == 201 and post("₹" * 30).status_code == 201
    for bad in ("", "   ", "T" * 31, "₹" * 31):
        assert post(bad).status_code == 422, bad
    for bad in ({}, {"name": "x", "y": 1}):
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
    view = get(client, f"/api/v1/labels/{label}").json()
    assert view["spent_paise"] == sum(t["amount_paise"] for t in spends)
    assert sum(c["amount_paise"] for c in view["categories"]) == view["spent_paise"]
    listed = {x["name"]: x for x in get(client, "/api/v1/labels").json()}
    assert listed["Test Trip"] == {k: v for k, v in view.items() if k != "categories"}
    assert listed["T" * 30]["transactions"] == listed["T" * 30]["spent_paise"] == 0
    labelled = all_transactions(client, label=label)
    assert {t["id"] for t in labelled} == {t["id"] for t in spends}
    assert {t["label"]["name"] for t in labelled} == {"Test Trip"}
    for _ in range(2):  # idempotent
        response = client.delete(
            f"/api/v1/transactions/{spends[0]['id']}/label", headers=bearer(token())
        )
        assert response.status_code == 200
    assert (
        next(x for x in get(client, "/api/v1/labels").json() if x["id"] == label)["transactions"]
        == 2
    )
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
    ignored = [
        CreditRow(7, 300, when, "vpa:test.b@okaxis", "test.b@okaxis", "ignored", "owner"),
        CreditRow(8, 300, when, "vpa:test.b@okaxis", "test.b@okaxis", "ignored", "owner"),
        CreditRow(9, 300, when, "vpa:test.c@okaxis", "test.c@okaxis", "ignored", "owner"),
        CreditRow(10, 50, when, "vpa:test.c@okaxis", "test.c@okaxis", "uncertain", "engine"),
    ]
    assert [(s.total_paise, s.role, s.status) for s in credit_senders(ignored, "salt-a")] == [
        (600, "ignored", "ignored"),
        (350, "uncertain", "to_confirm"),  # a new credit after "ignore": to confirm again
    ]


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
