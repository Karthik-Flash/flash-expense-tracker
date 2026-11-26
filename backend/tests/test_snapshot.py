"""GET /api/v1/sync/snapshot (D-088): the one read model of the app. FAKE data only."""

import gzip
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api import snapshot as snap
from app.main import app
from app.models import TxnDerived
from app.pipeline import version
from tests.apiclient import OWNER_A, SUB_B, SUB_X, all_transactions, bearer, get, put, token
from tests.smsdata import Row, write_backup

PATH = "/api/v1/sync/snapshot"


def fetch(client, sub: str = "user-a", **headers):
    return client.get(PATH, headers=bearer(token(sub)) | headers)


def body(client, sub: str = "user-a") -> dict:
    response = fetch(client, sub)
    assert response.status_code == 200, response.text
    return response.json()


def without_time(document: dict) -> dict:
    return {k: v for k, v in document.items() if k != "generated_at"}


# --- login and shape ---------------------------------------------------------------


def test_snapshot_needs_a_login(client) -> None:
    assert client.get(PATH).status_code == 401
    assert fetch(client, SUB_X).status_code == 403


def test_shape(client, data) -> None:
    s = body(client)
    assert set(s) == {
        "schema_version", "generated_at", "owner_id", "engine_versions", "months",
        "transactions", "todo", "labels", "categories", "people", "profile", "devices", "sms",
        "account", "admin", "paybacks",
    }  # fmt: skip
    assert s["profile"]["settings"] == {"count_investments_in_spent": False}  # D-136 default
    # The FAKE friend credit (H02, test.user@okaxis) pays back the one payment to them.
    assert [x["status"] for x in s["paybacks"]] == ["linked"]
    assert s["account"]["role"] == "admin"  # AUTH_USERS' login, the seed (D-129)
    assert set(s["admin"]) == {"invites", "members"}
    assert s["devices"] == [] and s["sms"]["newest_utc"].endswith("Z")
    assert s["schema_version"] == 1 and s["owner_id"] == str(OWNER_A)
    assert s["generated_at"].endswith("Z") and set(s["engine_versions"]) >= {"merchant"}
    assert [m["month"] for m in s["months"]] == sorted(m["month"] for m in s["months"])
    assert set(s["months"][0]) == {"month", "summary", "changes", "chart", "merchants", "people"}
    assert set(s["todo"]) == {
        "senders", "answered", "merchants", "unnamed", "transfers", "suggestions"
    }  # fmt: skip
    assert len(s["categories"]) == 20


# --- the same numbers as the other routes ------------------------------------------


def check_against_routes(client, s: dict) -> int:
    """Every number of the snapshot equals the route that shows it today; returns months."""
    for m in s["months"]:
        assert m["summary"] == get(client, "/api/v1/summary", month=m["month"]).json()
    assert s["transactions"] == all_transactions(client)
    senders = get(client, "/api/v1/senders", status="all").json()
    assert s["todo"]["senders"] + s["todo"]["answered"] == sorted(
        senders, key=lambda x: x["status"] != "to_confirm"
    )
    assert s["todo"]["senders"] == get(client, "/api/v1/senders").json()
    labels = get(client, "/api/v1/labels").json()
    assert [{k: v for k, v in x.items() if k != "categories"} for x in s["labels"]] == labels
    for x in s["labels"]:
        assert x == get(client, f"/api/v1/labels/{x['id']}").json()
    assert s["categories"] == get(client, "/api/v1/categories").json()
    return len(s["months"])


def check_derived(s: dict) -> None:
    """The figures no other route has add up to the summary's."""
    for m in s["months"]:
        summary = m["summary"]
        for c in summary["categories"]:
            if c["slug"] != "people":
                assert sum(g["total_paise"] for g in m["merchants"][c["slug"]]) == c["amount_paise"]
        people = {c["slug"]: c["amount_paise"] for c in summary["categories"]}.get("people", 0)
        assert sum(p["sent_paise"] for p in m["people"]) == people
        assert sum(p["got_back_paise"] for p in m["people"]) == summary["paid_back_paise"]
        assert (
            sum(p["to_confirm_paise"] for p in m["people"]) == summary["to_confirm"]["amount_paise"]
        )
        assert all(p["net_paise"] == p["sent_paise"] - p["got_back_paise"] for p in m["people"])
        assert m["chart"]["total_paise"] == sum(x["amount_paise"] for x in m["chart"]["slices"])
        assert len(m["chart"]["slices"]) <= snap.RING_SLICES + 1
        before = summary["previous"]
        assert m["changes"]["spent_paise"] == summary["spent_paise"] - before["spent_paise"]


def test_numbers_equal_the_routes(client, data) -> None:
    s = body(client)
    assert check_against_routes(client, s) >= 1
    check_derived(s)


def test_owner_b_sees_only_its_own(client, data) -> None:
    a, b = body(client), body(client, SUB_B)
    assert len(b["transactions"]) == 1
    assert not {t["id"] for t in a["transactions"]} & {t["id"] for t in b["transactions"]}


# --- the figures only the snapshot has (moved from the app, D-088) -----------------


def item(**over) -> dict:
    base = {
        "id": 1, "time_utc": "2026-10-10T06:00:00Z", "amount_paise": 10000, "direction": "debit",
        "display_name": "Someone", "person_id": None, "role": "spend", "role_basis": "engine",
        "category": "food_drinks",
    }  # fmt: skip
    return base | over


def test_people_ledger_rows() -> None:
    credit = {"direction": "credit", "role": "payback", "category": "people"}
    rows = snap.people([
        item(display_name="Rohit V", person_id="p_1", category="people", amount_paise=600000),
        item(**credit, display_name="rohit.v@okaxis", person_id="p_1", amount_paise=125000,
             role_basis="owner"),
        item(**credit, display_name="Rohit V", person_id="p_1", amount_paise=5000),
        item(display_name="Meera S", person_id="s_2", category="people", amount_paise=120000),
        item(display_name="Meera S", person_id="s_2", category="gifts_donations"),
        item(**credit, display_name="ramesh.k@okaxis", person_id="s_3", amount_paise=1000000),
        item(display_name="Pay Co", direction="credit", role="income", category="other"),
        item(display_name=None, category="people", amount_paise=7000),
    ])  # fmt: skip
    assert rows == [
        {"key": "p_1", "name": "Rohit V", "sent_paise": 600000, "got_back_paise": 125000,
         "to_confirm_paise": 5000, "net_paise": 475000},
        {"key": "s_2", "name": "Meera S", "sent_paise": 120000, "got_back_paise": 0,
         "to_confirm_paise": 0, "net_paise": 120000},
        {"key": "name:Bank transfer", "name": "Bank transfer", "sent_paise": 7000,
         "got_back_paise": 0, "to_confirm_paise": 0, "net_paise": 7000},
        {"key": "s_3", "name": "ramesh.k@okaxis", "sent_paise": 0, "got_back_paise": 0,
         "to_confirm_paise": 1000000, "net_paise": 0},
    ]  # fmt: skip


def test_ring_six_biggest_and_other() -> None:
    def part(slug: str, amount: int) -> dict:
        return {"slug": slug, "name": slug, "amount_paise": amount}

    nine = [part(f"c{n}", n * 100) for n in (1, 9, 2, 8, 3, 7, 4, 6, 5)]
    ring = snap.chart([*nine, part("refunded", -300), part("zero", 0)])
    assert [s["slug"] for s in ring["slices"]] == ["c9", "c8", "c7", "c6", "c5", "c4", None]
    assert ring["slices"][-1] == {"slug": None, "name": "Other (3)", "amount_paise": 600}
    assert ring["total_paise"] == 4500
    assert len(snap.chart(nine[:7])["slices"]) == 7  # seven fit: no Other of one
    assert snap.chart([part("refunded", -300)]) == {"total_paise": 0, "slices": []}


def test_merchants_and_todo_groups() -> None:
    rows = [
        item(id=3, display_name="Shop", category="uncategorised", amount_paise=500),
        item(id=2, display_name="Shop", category="uncategorised", role="refund", amount_paise=200),
        item(id=1, display_name=None, category="uncategorised", amount_paise=900),
        item(id=4, display_name="Cafe", amount_paise=300),
    ]
    assert snap.merchants(rows)["uncategorised"] == [
        {"name": "Bank transfer", "total_paise": 900, "count": 1},
        {"name": "Shop", "total_paise": 300, "count": 2},
    ]
    groups, unnamed = snap.todo_merchants(rows)
    assert groups == [
        {"name": "Shop", "total_paise": 500, "count": 1, "txn_id": 3,
         "last_time_utc": "2026-10-10T06:00:00Z"}
    ]  # fmt: skip
    assert unnamed == 1


# --- ETag and 304 ------------------------------------------------------------------


def test_etag_is_stable_and_changes_with_the_data(client, data, run, db_engine) -> None:
    first = fetch(client)
    etag = first.headers["etag"]
    assert etag.startswith('"v-') and len(etag) == 68  # from the data version (D-140)
    again = fetch(client)
    assert again.headers["etag"] == etag  # generated_at differs, the ETag does not
    assert again.json()["generated_at"] >= first.json()["generated_at"]

    not_modified = fetch(client, **{"If-None-Match": etag})
    assert not_modified.status_code == 304 and not_modified.content == b""
    assert not_modified.headers["etag"] == etag
    assert fetch(client, **{"If-None-Match": f'"other", W/{etag}'}).status_code == 304
    assert fetch(client, **{"If-None-Match": '"other"'}).status_code == 200

    sender = body(client)["todo"]["senders"][0]["id"]
    assert put(client, f"/api/v1/senders/{sender}", {"answer": "friend"}).status_code == 200
    after_answer = fetch(client, **{"If-None-Match": etag})
    assert after_answer.status_code == 200 and after_answer.headers["etag"] != etag

    etag = after_answer.headers["etag"]
    run("recompute")  # nothing changed: same data, same ETag
    assert fetch(client, **{"If-None-Match": etag}).status_code == 304

    with sessionmaker(db_engine)() as s:  # stored rows that a recompute will put right
        row = s.scalar(select(TxnDerived).where(TxnDerived.category != "travel"))
        row.category = "travel"
        s.commit()
    # An edit by hand, outside every write path: the ETag (the data version, D-140) cannot see
    # it, so the same 304 holds until something raises the version.
    assert fetch(client, **{"If-None-Match": etag}).status_code == 304
    with sessionmaker(db_engine)() as s:
        version.bump(s, OWNER_A)
        s.commit()
    stale = fetch(client)
    assert stale.headers["etag"] != etag and any(
        m["summary"]["stale"] for m in stale.json()["months"]
    )
    run("recompute")
    fixed = fetch(client, **{"If-None-Match": stale.headers["etag"]})
    assert fixed.status_code == 200 and fixed.headers["etag"] != stale.headers["etag"]


# --- a year of FAKE messages: equality, gzip, size and time --------------------------


def year_rows(months: int = 11, per_month: int = 64) -> list[Row]:
    """About 700 FAKE HDFC messages from Jan 2026: UPI payments to shops and people, card
    spends, ATM withdrawals, refunds and UPI money in."""
    rows: list[Row] = []
    shops = ["SWIGGY", "ZOMATO", "UBER", "BLINKIT", "TEST STORE", "TEST CANTEEN", "TEST XEROX"]
    ref = 500_000_000_000
    for month in range(1, months + 1):
        for i in range(per_month):
            day, hour = 1 + i % 28, 3 + i % 12
            when = datetime(2026, month, day, hour, i % 60, tzinfo=UTC)
            ist = when + timedelta(hours=5, minutes=30)
            amount = 40 + (i * 37 + month * 11) % 900
            ref += 1
            kind = i % 8
            if kind in (0, 1, 2):
                to = shops[(i + month) % len(shops)] if kind else f"PERSON_{900 + i % 6}"
                body = (
                    f"Sent Rs.{amount}.00\nFrom HDFC Bank A/C *0001\nTo {to}\n"
                    f"On {ist:%d/%m/%y}\nRef {ref}\nNot You?\n"
                    "Call 18000000001/SMS BLOCK UPI to 9000000001\n"
                )
            elif kind in (3, 4):
                body = (
                    f"Spent Rs.{amount} From HDFC Bank Card x0002 At {shops[i % len(shops)]} "
                    f"On {ist:%Y-%m-%d:%H:%M:%S} Bal Rs.24000 Not You? "
                    "Call 18000000001/SMS BLOCK DC 0002 to 9000000001"
                )
            elif kind == 5:
                body = (
                    f"Credit Alert!\nRs.{amount}.00 credited to HDFC Bank A/c XX0001 on "
                    f"{ist:%d-%m-%y} from VPA friend{i % 5}@okaxis (UPI {ref})\n"
                )
            elif kind == 6:
                body = (
                    f"Withdrawn Rs.{amount * 10} From HDFC Bank Card x0002 At TEST ATM 0001 "
                    f"On {ist:%Y-%m-%d:%H:%M:%S} Bal Rs.66666.00 Not You? "
                    "Call 18000000001/SMS BLOCK DC 0002 to 9000000001"
                )
            else:
                body = (
                    f"Rs.{amount}.00 refund credited to HDFC Bank A/c XX0001 from SWIGGY on "
                    f"{ist:%d-%m-%y} (UPI Ref {ref})"
                )
            rows.append(("HDFCBK", body, when))
    return rows


@pytest.fixture
def year(run, tmp_path: Path) -> None:
    run("import-sms", "--input", str(write_backup(tmp_path / "year.xml", year_rows())))


def test_a_year_of_messages(client, year, db_engine) -> None:
    s = body(client)
    assert len(s["transactions"]) >= 650
    assert check_against_routes(client, s) == 11
    check_derived(s)

    response = fetch(client)
    assert response.headers["content-encoding"] == "gzip"
    raw = snap.canonical(response.json())
    zipped = len(gzip.compress(raw))
    assert zipped < len(raw) / 4
    with sessionmaker(db_engine)() as session:
        start = time.perf_counter()
        snap.build(session, OWNER_A)
        seconds = time.perf_counter() - start
    # Printed for the report (pytest -s): sizes in bytes, build time in seconds.
    count = len(s["transactions"])
    print(f"\nsnapshot: {count} txns, raw {len(raw)}, gzip {zipped}, build {seconds:.2f}s")
    assert seconds < 20


def test_small_answers_are_not_gzipped(client) -> None:
    response = client.get("/health")
    assert "content-encoding" not in response.headers
    assert json.loads(response.content)["status"] == "ok"


def test_the_snapshot_route_is_in_the_app() -> None:
    assert PATH in app.openapi()["paths"]


def test_profile_shows_member_since_and_the_payments_it_spans(client, data) -> None:
    """Premium A.2: the account's start and the payments' count and first and last days."""
    s = body(client)
    assert s["account"]["since_utc"].endswith("Z")
    info = s["profile"]["data"]
    times = sorted(t["time_utc"] for t in s["transactions"])
    assert info == {"payments": len(times), "first_utc": times[0], "last_utc": times[-1]}


def test_the_snapshot_reads_do_not_grow_with_months(client, db_engine) -> None:
    """D-150: every month's summary comes from rows read once, so one month and a year of them cost
    the same number of statements (47 when measured)."""
    from sqlalchemy import event

    from tests.test_devices import UPI_SENT, WHEN, register, sms, upload

    phone = register(client).json()["token"]

    def statements() -> int:
        body(client)  # fresh first
        seen: list[str] = []

        def listen(conn, cursor, statement, *args) -> None:
            seen.append(statement)

        event.listen(db_engine, "before_cursor_execute", listen)
        body(client)
        event.remove(db_engine, "before_cursor_execute", listen)
        return len(seen)

    upload(client, phone, sms(n=1))
    one = statements()
    for n in range(1, 12):
        ref = UPI_SENT.replace("612300000002", f"61230000{n:04d}")
        upload(client, phone, sms(ref, when=WHEN - timedelta(days=31 * n), n=n + 1))
    assert len(body(client)["months"]) >= 10
    assert statements() == one <= 55


def test_the_snapshot_is_gzipped_and_its_etag_still_gives_304(client, data) -> None:
    """5G-A: GZipMiddleware compresses the answer; the ETag stays the same and If-None-Match
    still answers 304 with no body."""
    first = fetch(client, **{"Accept-Encoding": "gzip"})
    assert first.status_code == 200 and first.headers["content-encoding"] == "gzip"
    etag = first.headers["etag"]
    assert etag.startswith('"v-')
    again = fetch(client, **{"Accept-Encoding": "gzip", "If-None-Match": etag})
    assert again.status_code == 304 and again.content == b"" and again.headers["etag"] == etag
    plain = fetch(client, **{"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and plain.headers["etag"] == etag
