"""Export (5F, D-146): CSV and Excel from the server, FAKE data only."""

import csv
import io
import zipfile
from xml.etree import ElementTree

from app.pipeline.export import Sheet, safe, to_csv, to_xlsx
from tests.apiclient import SUB_B, bearer, get, token
from tests.test_devices import UPI_SENT, WHEN, register, sms, upload

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RANGE = {"start": "2026-01-01", "end": "2026-01-31"}


def fetch(client, sub: str = "user-a", **params):
    return client.get("/api/v1/export", headers=bearer(token(sub)), params=RANGE | params)


def test_formula_cells_are_neutralised() -> None:
    for text in ("=HYPERLINK(1)", "+91 call", "-5", "@SUM(A1)", "\tx", "\rx"):
        assert safe(text) == "'" + text
    assert safe("Swiggy") == "Swiggy" and safe(12.5) == 12.5 and safe("") == ""
    body = to_csv(("a", "b"), [["=1+1", 3.5]]).decode("utf-8-sig")
    assert body.splitlines() == ["a,b", "'=1+1,3.50"]


def test_the_csv_matches_the_transactions(client, data) -> None:
    answer = fetch(client)
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"].startswith("text/csv")
    assert 'filename="flash-2026-01-01-to-2026-01-31.csv"' in answer.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(answer.content.decode("utf-8-sig"))))
    january = [
        t for t in get(client, "/api/v1/transactions", month="2026-01", limit=200).json()["items"]
    ]
    assert len(rows) == len(january) > 5
    assert list(rows[0]) == [
        "Date", "Time", "Name", "Category", "Label", "Counted as", "Money", "Amount", "Bank",
        "Account", "Confirmed by you", "Note",
    ]  # fmt: skip
    assert all(r["Date"].startswith("2026-01-") for r in rows)  # IST days of the range
    assert {r["Money"] for r in rows} <= {"in", "out"}
    total = sum(round(float(r["Amount"]) * 100) for r in rows)
    assert total == sum(t["amount_paise"] for t in january)
    text = answer.content.decode("utf-8-sig")
    assert "Not You?" not in text and "Ref 0000" not in text  # never the SMS text or a reference


def test_the_workbook_has_both_sheets_and_the_summary_of_the_app(client, data) -> None:
    answer = fetch(client, format="xlsx")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("application/vnd.openxmlformats")
    z = zipfile.ZipFile(io.BytesIO(answer.content))
    assert {
        "xl/workbook.xml",
        "xl/styles.xml",
        "xl/worksheets/sheet1.xml",
        "xl/worksheets/sheet2.xml",
    } <= set(z.namelist())
    names = [
        s.get("name")
        for s in ElementTree.fromstring(z.read("xl/workbook.xml")).iter(f"{{{NS['m']}}}sheet")
    ]
    assert names == ["Transactions", "Summary"]
    sheet = ElementTree.fromstring(z.read("xl/worksheets/sheet1.xml"))
    assert sheet.find(".//m:pane", NS).get("state") == "frozen"  # the header stays
    header = sheet.find(".//m:row", NS)
    assert {c.get("s") for c in header} == {"1"}  # bold
    assert "##,##0.00" in z.read("xl/styles.xml").decode()  # Indian grouping
    summary = {}
    for row in ElementTree.fromstring(z.read("xl/worksheets/sheet2.xml")).iterfind(".//m:row", NS):
        cells = list(row)
        key = "".join(cells[0].itertext()) if cells else ""
        value = cells[1].find("m:v", NS) if len(cells) > 1 else None
        if value is not None:
            summary[key] = round(float(value.text) * 100)
    month = get(client, "/api/v1/summary", month="2026-01").json()
    assert summary["Spent"] == month["spent_paise"] and summary["Net"] == month["net_paise"]
    assert summary["Paid back"] == month["paid_back_paise"]
    assert summary["Invested"] == month["invested_paise"]


def test_a_workbook_round_trip_of_odd_text() -> None:
    sheet = Sheet("T", ("x",), (10,), [['a < b & "c" \x07'], [12.5]], frozenset())
    z = zipfile.ZipFile(io.BytesIO(to_xlsx([sheet])))
    root = ElementTree.fromstring(z.read("xl/worksheets/sheet1.xml"))  # valid XML
    texts = ["".join(c.itertext()) for c in root.iterfind(".//m:c", NS)]
    assert texts == ["x", 'a < b & "c" ', "12.5"]


def test_bad_ranges_and_another_owners_rows(client, data) -> None:
    assert fetch(client, start="2026-02-01", end="2026-01-01").status_code == 422
    assert fetch(client, start="2020-01-01", end="2026-01-01").status_code == 422  # > 3 years
    assert fetch(client, format="pdf").status_code == 422
    b = register(client, "user-b").json()["token"]
    upload(client, b, sms(UPI_SENT.replace("TEST CAFE NEW", "TEST B ONLY"), when=WHEN, n=1))
    mine = fetch(client, start="2026-03-01", end="2026-03-31").content.decode("utf-8-sig")
    theirs = fetch(client, SUB_B, start="2026-03-01", end="2026-03-31").content.decode("utf-8-sig")
    assert "Test B Only" not in mine and "Test B Only" in theirs
