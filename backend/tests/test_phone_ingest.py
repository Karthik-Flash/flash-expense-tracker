"""5B-2 ingest (D-139, D-141): the inbox copy and the live copy of one SMS are one payment; two
real payments stay two; the answer lists only the transactions this upload created. FAKE."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models import RawMessage, Transaction
from app.pipeline.dedupe import normal_body
from tests.test_devices import UPI_SENT, WHEN, register, sms, upload

# A card spend: no reference, so only the twin rule can join its two copies.
CARD = (
    "Spent Rs.33.00 From HDFC Bank Card x0002 At TEST KIOSK On 2026-03-10:11:30:00 "
    "Bal Rs.24000 Not You? Call 18000000001/SMS BLOCK DC 0002 to 9000000001"
)
CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "body_normalise.json").read_text(encoding="utf-8")
)


@pytest.fixture
def token(client) -> str:
    """A registered phone's device token (owner A)."""
    return register(client).json()["token"]


def counts(db_engine) -> tuple[int, int]:
    with sessionmaker(db_engine)() as s:
        raw = s.scalar(select(func.count()).select_from(RawMessage))
        return raw, s.scalar(select(func.count()).select_from(Transaction))


def test_the_shared_normal_body_cases() -> None:
    """The phone's Wire.normalBody passes the same file (WireTest.kt)."""
    assert len(CASES) >= 6
    for case in CASES:
        assert normal_body(case["in"]) == case["out"], case["name"]


def live(body: str, when, n: int) -> dict:
    return sms(body, when=when, n=n) | {"origin": "live"}


def test_live_and_inbox_copies_of_one_sms_are_one_payment(client, db_engine, token) -> None:
    inbox = sms(CARD, n=1)
    copy = live(
        CARD.replace(" Bal", "\nBal").replace("On ", "On  "), WHEN + timedelta(seconds=4), 2
    )
    for first, second in ((inbox, copy), (copy, inbox)):  # either may come first
        client_rows = upload(client, token, first).json()
        assert client_rows["results"][0]["status"] in ("stored", "duplicate")
        assert upload(client, token, second).json()["results"][0]["status"] == "duplicate"
        assert counts(db_engine) == (1, 1)


def test_two_real_payments_of_one_amount_to_one_payee_stay_two(client, db_engine, token) -> None:
    """The owner paid Rs 1 twice to one payee within minutes: two references, two payments;
    each also arrives both ways, and the second real one is never swallowed."""
    one = UPI_SENT.replace("Rs.250.00", "Rs.1.00")
    two = one.replace("612300000002", "612300000003")
    later = WHEN + timedelta(minutes=2)
    for m in (sms(one, n=1), live(one, WHEN, 2), live(two, later, 3), sms(two, when=later, n=4)):
        assert upload(client, token, m).status_code == 200
    assert counts(db_engine) == (2, 2)
    # No reference at all, the same text twice in ten minutes, both ways in: still two.
    spend = CARD.replace("Rs.33.00", "Rs.44.00")
    again = WHEN + timedelta(minutes=5)
    for m in (
        live(spend, WHEN, 5),
        live(spend, again, 6),
        sms(spend, n=7),
        sms(spend, when=again, n=8),
    ):
        upload(client, token, m)
    assert counts(db_engine) == (4, 4)


def test_a_laptop_import_after_the_live_copy_adds_nothing(
    client, db_engine, run, tmp_path, token
) -> None:
    from tests.smsdata import write_backup

    upload(client, token, live(CARD, WHEN + timedelta(seconds=3), 1))
    run(
        "import-sms",
        "--input",
        str(write_backup(tmp_path / "x.xml", [("VM-HDFCBK-S", CARD, WHEN)])),
    )
    assert counts(db_engine) == (1, 1)


def test_the_answer_lists_new_payments_only(client, db_engine, token) -> None:
    first = upload(client, token, sms(CARD, n=1)).json()
    (item,) = first["new_transactions"]
    assert set(item) == {
        "device_msg_id", "id", "direction", "amount_paise", "display_name", "category",
        "category_name", "role", "paid_back_question",
    }  # fmt: skip
    assert (item["device_msg_id"], item["direction"], item["amount_paise"]) == ("1", "debit", 3300)
    assert item["role"] == "spend" and item["display_name"] == "Test Kiosk"
    assert item["paid_back_question"] is False
    again = upload(
        client, token, sms(CARD, n=1), sms("Your A/C XX0001 was updated. TEST notice", n=2)
    )
    assert again.json()["new_transactions"] == []  # a duplicate and a notice: nothing new


def test_a_person_credit_asks_paid_back(client, token) -> None:
    credit = ("Credit Alert!\nRs.75.00 credited to HDFC Bank A/c XX0001 on 10-03-26 from VPA "
              "test.friend7@okaxis (UPI 612300000099)\n")  # fmt: skip
    (item,) = upload(client, token, sms(credit, n=1)).json()["new_transactions"]
    assert (item["direction"], item["role"], item["paid_back_question"]) == (
        "credit",
        "uncertain",
        True,
    )


def test_a_device_token_never_gets_another_owners_payment(client, db_engine, token) -> None:
    """B's phone uploads the same SMS as A's: B gets B's own new payment, never A's."""
    a, b = token, register(client, "user-b").json()["token"]
    mine = upload(client, a, sms(CARD, n=1)).json()["new_transactions"]
    theirs = upload(client, b, sms(CARD, n=1)).json()["new_transactions"]
    assert len(mine) == len(theirs) == 1 and mine[0]["id"] != theirs[0]["id"]
    with sessionmaker(db_engine)() as s:
        owners = {t.id: t.owner_id for t in s.scalars(select(Transaction))}
    assert owners[mine[0]["id"]] != owners[theirs[0]["id"]]
    assert upload(client, b, sms(CARD, n=1)).json()["new_transactions"] == []


def test_recompute_and_reparse_never_join_stored_payments(run, db_engine, tmp_path) -> None:
    """Premium A.3 (b): the live/inbox join runs only when a message is stored
    (store.ingest). Payments stored before it, here two same-amount card spends to one payee
    five minutes apart and two Rs 1 UPI payments, stay four through recompute and reparse,
    and none gets role duplicate (DUP_same_amount is only ever a candidate)."""
    from app.models import TxnDerived
    from tests.smsdata import write_backup

    one = UPI_SENT.replace("Rs.250.00", "Rs.1.00")
    rows = [
        ("VM-HDFCBK-S", CARD, WHEN),
        ("VM-HDFCBK-S", CARD, WHEN + timedelta(minutes=5)),
        ("VM-HDFCBK-S", one, WHEN + timedelta(hours=2)),
        ("VM-HDFCBK-S", one.replace("612300000002", "612300000003"), WHEN + timedelta(hours=3)),
    ]
    run("import-sms", "--input", str(write_backup(tmp_path / "x.xml", rows)))
    for argv in (("recompute",), ("reparse",), ("recompute",)):
        run(*argv)
        with sessionmaker(db_engine)() as s:
            active = s.scalar(
                select(func.count()).select_from(Transaction).where(Transaction.status == "active")
            )
            roles = s.scalars(select(TxnDerived.role)).all()
        assert active == 4 and len(roles) == 4 and "duplicate" not in roles, argv


def test_an_emoji_written_as_two_replacement_characters_is_one_sms(
    client, db_engine, run, tmp_path, token
) -> None:
    """Open item 5c (D-150): the phone sends the emoji; SMS Backup & Restore writes it as two
    U+FFFD. The laptop import afterwards adds nothing; a different text is still stored."""
    from tests.smsdata import write_backup

    phone = CARD.replace("TEST KIOSK", "TEST KIOSK \U0001f6a8")
    laptop = CARD.replace("TEST KIOSK", "TEST KIOSK ��")
    upload(client, token, sms(phone, n=1))
    assert counts(db_engine) == (1, 1)
    backup = write_backup(tmp_path / "x.xml", [("VM-HDFCBK-S", laptop, WHEN)])
    run("import-sms", "--input", str(backup))
    assert counts(db_engine) == (1, 1)
    other = laptop.replace("Rs.33.00", "Rs.34.00")
    run(
        "import-sms",
        "--input",
        str(write_backup(tmp_path / "y.xml", [("VM-HDFCBK-S", other, WHEN)])),
    )
    assert counts(db_engine) == (2, 2)
