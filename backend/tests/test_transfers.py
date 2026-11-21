"""Money moved between the owner's own HDFC and SBI accounts (D-115). FAKE messages only.

A shared 12-digit reference links both legs at once; the same amount within 30 minutes
without one is only a question for the owner ("Moved between your accounts?").
"""

from datetime import UTC, datetime

from tests.apiclient import all_transactions, get, put
from tests.smsdata import write_backup

T = datetime(2026, 3, 10, 4, 30, tzinfo=UTC)  # 10:00 IST


def at(minutes: int) -> datetime:
    return datetime.fromtimestamp(T.timestamp() + minutes * 60, UTC)


def sbi_upi_in(rupees: str, ref: str, minutes: int) -> tuple:
    body = (f"Dear SBI User, your A/c X7733-credited by Rs.{rupees} on 10Mar26 transfer from "
            f"TEST OWNER Ref No {ref} -SBI")  # fmt: skip
    return ("VM-SBIUPI", body, at(minutes))


def sbi_in(rupees: str, minutes: int) -> tuple:
    body = (f"Dear Customer, Your A/C XXXXX7733 has a credit by Transfer of Rs {rupees} on "
            "10Mar26 by TEST OWNER. Avl Bal Rs 9,000.00.-SBI")  # fmt: skip
    return ("VM-CBSSBI", body, at(minutes))


def sent(rupees: str, ref: str, minutes: int) -> tuple:
    body = (f"Sent Rs.{rupees}\nFrom HDFC Bank A/C *0001\nTo TEST OWNER\nOn 10/03/26\nRef {ref}\n"
            "Not You?\nCall 18000000001/SMS BLOCK UPI to 9000000001\n")  # fmt: skip
    return ("VM-HDFCBK-S", body, at(minutes))


def load(run, tmp_path) -> dict[tuple[str, int], dict]:
    rows = [
        sent("5,000.00", "612345678901", 0), sbi_upi_in("5000.00", "612345678901", 5),  # shared
        sent("700.00", "612345678902", 120), sbi_in("700.00", 130),  # 10 min, no shared ref
        sbi_in("700.00", 140),  # a second possible leg for the same debit
        sent("900.00", "612345678903", 300), sbi_in("900.00", 331),  # 31 minutes: nothing
    ]  # fmt: skip
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", rows)))


def by_amount(client) -> dict[tuple[str, int], list[dict]]:
    out: dict[tuple[str, int], list[dict]] = {}
    for t in all_transactions(client):
        out.setdefault((t["direction"], t["amount_paise"]), []).append(t)
    return out


def transfers(client) -> list[dict]:
    return get(client, "/api/v1/sync/snapshot").json()["todo"]["transfers"]


def test_shared_reference_links_and_close_pairs_are_asked(client, run, tmp_path) -> None:
    load(run, tmp_path)
    rows = by_amount(client)
    assert {t["role"] for t in rows["debit", 500000] + rows["credit", 500000]} == {"self_transfer"}
    assert rows["debit", 90000][0]["role"] == "spend"  # 31 minutes apart: never asked
    asked = transfers(client)
    debit = rows["debit", 70000][0]["id"]
    assert sorted((x["debit"], x["credit"]) for x in asked) == sorted(
        (debit, c["id"]) for c in rows["credit", 70000]
    )
    assert {(x["from_bank"], x["to_bank"], x["amount_paise"]) for x in asked} == {
        ("HDFC", "SBI", 70000)
    }
    assert rows["debit", 70000][0]["role"] == "spend"  # nothing changes until the owner says


def test_yes_makes_both_legs_a_transfer_and_no_drops_the_pair(client, run, tmp_path) -> None:
    load(run, tmp_path)
    rows = by_amount(client)
    debit = rows["debit", 70000][0]["id"]
    first, second = sorted(c["id"] for c in rows["credit", 70000])
    path = f"/api/v1/transfers/{debit}/{first}"
    assert put(client, path, {"verdict": "same"}).status_code == 200
    # One debit, one transfer: a second "same" for it is refused.
    again = put(client, f"/api/v1/transfers/{debit}/{second}", {"verdict": "same"})
    assert again.status_code == 409
    assert (
        put(client, f"/api/v1/transfers/{second}/{debit}", {"verdict": "different"}).status_code
        == 200
    )
    after = {t["id"]: t["role"] for t in all_transactions(client)}  # the read recomputes
    assert (after[debit], after[first], after[second]) == (
        "self_transfer",
        "self_transfer",
        "uncertain",
    )
    assert transfers(client) == []
    # A pair the engine never proposed is not a transfer to answer.
    nine = by_amount(client)
    a, b = nine["debit", 90000][0]["id"], nine["credit", 90000][0]["id"]
    lone = put(client, f"/api/v1/transfers/{a}/{b}", {"verdict": "same"})
    assert lone.status_code == 404
    assert put(client, path, {"verdict": "maybe"}).status_code == 422
