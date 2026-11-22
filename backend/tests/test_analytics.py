"""Analytics (premium B, D-148): every month's bars equal /summary; the ETag; FAKE data."""

import uuid

from app.api.analytics import month_list, share
from tests.apiclient import bearer, get, token

PATH = "/api/v1/analytics"


def fetch(client, start: str, end: str, sub: str = "user-a", **headers):
    return client.get(
        PATH, headers=bearer(token(sub)) | headers, params={"start": start, "end": end}
    )


def test_every_months_bars_equal_its_summary(client, data) -> None:
    answer = fetch(client, "2025-12", "2026-04")
    assert answer.status_code == 200, answer.text
    a = answer.json()
    assert [m["month"] for m in a["months"]] == month_list("2025-12", "2026-04")
    for n, bar in enumerate(a["months"]):
        s = get(client, "/api/v1/summary", month=bar["month"]).json()
        assert bar["spent_paise"] == s["spent_paise"], bar["month"]
        assert bar["invested_paise"] == s["invested_paise"]
        assert bar["paid_back_paise"] == s["paid_back_paise"]
        assert bar["net_paise"] == s["net_paise"]
        assert bar["income_paise"] == s["income_paise"]
        assert bar["to_confirm_paise"] == s["to_confirm"]["amount_paise"]
        cats = {c["slug"]: c["amount_paise"] for c in s["categories"]}
        mine = {c["slug"]: c["months"][n] for c in a["categories"] if c["months"][n]}
        assert mine == {k: v for k, v in cats.items() if v}, bar["month"]
    spent = sum(m["spent_paise"] for m in a["months"])
    assert sum(c["total_paise"] for c in a["categories"]) == spent
    assert a["stats"]["payments"] > 0 and a["stats"]["per_day_paise"] > 0
    assert sum(a["stats"]["ways_bp"].values()) in (0, 9999, 10000, 10001)
    assert a["moves"]["from"] == "2026-03" and a["moves"]["to"] == "2026-04"
    assert all(x["change_paise"] > 0 for x in a["moves"]["up"])
    assert all(x["change_paise"] < 0 for x in a["moves"]["down"])
    assert all(m["total_paise"] > 0 for m in a["merchants"])


def test_an_unchanged_answer_is_a_304_and_a_write_moves_it(client, data) -> None:
    first = fetch(client, "2026-01", "2026-01")
    etag = first.headers["etag"]
    assert fetch(client, "2026-01", "2026-01", **{"If-None-Match": etag}).status_code == 304
    assert fetch(client, "2026-01", "2026-02").headers["etag"] != etag  # another range
    body = {"names": ["TEST OWNER"]}
    headers = bearer(token()) | {"Idempotency-Key": str(uuid.uuid4())}
    answer = client.put("/api/v1/profile/names", headers=headers, json=body)
    assert answer.status_code == 200, answer.text
    assert fetch(client, "2026-01", "2026-01", **{"If-None-Match": etag}).status_code == 200


def test_bad_ranges() -> None:
    assert month_list("2026-01", "2026-01") == ["2026-01"]
    assert month_list("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert share(1, 3) == 3333 and share(2, 3) == 6667 and share(5, 0) == 0


def test_bad_ranges_are_422(client, data) -> None:
    assert fetch(client, "2026-03", "2026-01").status_code == 422
    assert fetch(client, "2023-01", "2026-01").status_code == 422  # more than 24 months
    assert fetch(client, "2026-13", "2026-14").status_code == 422
