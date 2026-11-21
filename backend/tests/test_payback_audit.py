"""D-099: silent paybacks are found by payback-audit and repaired only by --fix --apply.
FAKE data only."""

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.engine.reconcile import IST, totals
from app.models import Party, PartyText, Transaction, TxnDerived
from app.pipeline.recompute import active_txns
from tests.smsdata import full_rows, write_backup

FAR = (datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))


def count(out: str, label: str) -> int:
    return int(re.search(rf"^{label}\s+(\d+)$", out, re.M).group(1))


def person_credits(factory) -> list[Transaction]:
    """Credits from different person-like texts, one per text."""
    with factory() as s:
        rows = s.scalars(
            select(Transaction)
            .join(TxnDerived, TxnDerived.transaction_id == Transaction.id)
            .where(Transaction.type == "credit", TxnDerived.merchant_kind == "person")
            .order_by(Transaction.id)
        ).all()
    seen, out = set(), []
    for t in rows:
        if t.counterparty_raw not in seen:
            seen.add(t.counterparty_raw)
            out.append(t)
    return out


def add_party(factory, t: Transaction, **fields) -> int:
    with factory() as s:
        party = Party(owner_id=settings.owner_id, label=f"T{t.id}", **fields)
        s.add(party)
        s.flush()
        s.add(PartyText(owner_id=settings.owner_id, party_id=party.id, text=t.counterparty_raw,
                        source=party.source))  # fmt: skip
        s.commit()
        return party.id


def state(factory) -> tuple[dict, list[tuple]]:
    with factory() as s:
        derived = {
            d.transaction_id: (d.role, d.role_basis) for d in s.scalars(select(TxnDerived)).all()
        }
        roles = {i: type("D", (), {"role": r, "basis": b}) for i, (r, b) in derived.items()}
        t = totals(active_txns(s, settings.owner_id), roles, *FAR)
        parties = [
            (p.id, p.kind, p.source, p.category, p.income_label)
            for p in s.scalars(select(Party).order_by(Party.id))
        ]
    return {"spent": t.spent_paise, "paid_back": t.paid_back_paise, "net": t.net_paise,
            "roles": derived}, parties  # fmt: skip


def test_audit_dry_run_and_apply(run, db_engine, tmp_path) -> None:
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", full_rows())))
    factory = sessionmaker(db_engine, expire_on_commit=False)
    credits = person_credits(factory)
    assert len(credits) >= 3
    silent, friend, family = credits[:3]
    silent_id = add_party(factory, silent, kind="person", category="food_drinks", source="app")
    friend_id = add_party(factory, friend, kind="person", source="app")  # a Friend answer
    add_party(factory, family, kind="person", income_label="Test Family", category="people",
              source="app")  # fmt: skip
    run("recompute")
    before, parties_before = state(factory)
    assert before["roles"][silent.id] == ("payback", "owner")

    out = run("payback-audit")
    assert count(out, "silent person parties") == 1 and count(out, "credits in Paid back") == 1
    assert silent.txn_time_utc.astimezone(IST).strftime("%Y-%m") in out  # the month key

    dry = run("payback-audit", "--fix")
    assert "dry run" in dry and "would change 1 party" in dry
    assert state(factory) == (before, parties_before)  # nothing changed

    applied = run("payback-audit", "--fix", "--apply")
    assert "changed 1 party" in applied and "recompute run" in applied
    after, parties_after = state(factory)
    assert after["roles"][silent.id][1] == "engine"  # the engine's guess: To confirm again
    assert after["roles"][friend.id] == ("payback", "owner")  # Friend untouched
    assert after["roles"][family.id] == ("income", "owner")  # Family untouched
    assert after["net"] >= before["net"] and after["spent"] == before["spent"]
    changed = {p[0]: p for p in parties_after if p not in parties_before}
    assert changed == {silent_id: (silent_id, "unsure", "terminal", "food_drinks", None)}
    with factory() as s:  # texts kept, nothing ended
        texts = s.scalars(select(PartyText).where(PartyText.party_id == silent_id)).all()
        assert len(texts) == 1 and texts[0].ended_at is None
        assert s.get(Party, friend_id).kind == "person"

    again = run("payback-audit", "--fix", "--apply")  # idempotent
    assert count(again, "silent person parties") == 0 and "changed 0 parties" in again
    assert state(factory) == (after, parties_after)


def test_an_explicit_answer_is_never_silent(run, db_engine, tmp_path) -> None:
    """Corrected in 4F-B: Friend with a category is not silent when the answer is on record,
    as answered_at or as a stored app answer for its sender."""
    import uuid
    from datetime import UTC, datetime

    from app.models import ClientOp
    from app.pipeline.owner_actions import senders

    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", full_rows())))
    factory = sessionmaker(db_engine, expire_on_commit=False)
    credits = person_credits(factory)
    on_record, in_app, silent = credits[:3]
    now = datetime.now(UTC)
    add_party(factory, on_record, kind="person", category="food_drinks", source="app",
              answered_at=now)  # fmt: skip
    in_app_party = add_party(factory, in_app, kind="person", category="food_drinks", source="app")
    add_party(factory, silent, kind="person", category="food_drinks", source="app")
    run("recompute")
    with factory() as s:
        sender = next(x for x in senders(s, settings.owner_id) if x.party_id == in_app_party)
        s.add(ClientOp(owner_id=settings.owner_id, op_id=uuid.uuid4(), received_at=now,
                       method="PUT", path=f"/api/v1/senders/{sender.id}", request_hash="x" * 64,
                       status_code=200, response_body={}, completed_at=now))  # fmt: skip
        s.commit()
    out = run("payback-audit")
    assert count(out, "silent person parties") == 1 and count(out, "credits in Paid back") == 1


def test_a_friend_answer_is_recorded_and_a_reset_forgets_it(client, data, db_engine) -> None:
    from tests.apiclient import bearer, get, put, token

    sender = next(s for s in get(client, "/api/v1/senders").json() if s["status"] == "to_confirm")
    assert put(client, f"/api/v1/senders/{sender['id']}", {"answer": "friend"}).status_code == 200
    answered = select(Party).where(Party.answered_at.is_not(None))
    with sessionmaker(db_engine)() as s:
        parties = s.scalars(answered).all()
    assert len(parties) == 1 and parties[0].kind == "person"
    get(client, "/api/v1/senders")  # the read recomputes (D-106): the sender is a party now
    reset = client.delete(f"/api/v1/senders/{sender['id']}", headers=bearer(token()))
    assert reset.status_code == 200
    with sessionmaker(db_engine)() as s:
        assert s.scalars(answered).all() == []


def test_apply_needs_fix(run, db_engine) -> None:
    assert "--apply needs --fix or --restore" in run("payback-audit", "--apply", code=2)
    assert "not both" in run("payback-audit", "--fix", "--restore", code=2)


def sender_op(factory, party_id: int, method: str, body: dict | None, when: datetime) -> None:
    """A stored app write for the sender of this party, as client_ops keeps it."""
    import uuid

    from app.api.ops import request_hash
    from app.models import ClientOp
    from app.pipeline.owner_actions import senders

    with factory() as s:
        sender = next(x for x in senders(s, settings.owner_id) if x.party_id == party_id)
        path = f"/api/v1/senders/{sender.id}"
        s.add(ClientOp(owner_id=settings.owner_id, op_id=uuid.uuid4(), received_at=when,
                       method=method, path=path, request_hash=request_hash(method, path, body),
                       status_code=200, response_body={}, completed_at=when))  # fmt: skip
        s.commit()


def owner_role(factory, txn_id: int, role: str) -> None:
    from app.models import OwnerRole

    with factory() as s:
        s.add(OwnerRole(transaction_id=txn_id, owner_id=settings.owner_id, role=role,
                        decided_at=datetime.now(UTC), source="file"))  # fmt: skip
        s.commit()


FRIEND = {"answer": "friend", "label": None}


def test_any_owner_answer_on_record_is_never_silent(run, db_engine, tmp_path) -> None:
    """D-111: a role decision on a credit (any source) or the newest app answer counts; an
    Ignore answer or an "Ask me again later" after the answer does not."""
    from datetime import timedelta

    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", full_rows())))
    factory = sessionmaker(db_engine, expire_on_commit=False)
    by_role, family, ignored = person_credits(factory)[:3]
    ids = {t.id: add_party(factory, t, kind="person", category="food_drinks", source="app")
           for t in (by_role, family, ignored)}  # fmt: skip
    run("recompute")
    assert count(run("payback-audit"), "silent person parties") == 3
    now = datetime.now(UTC)
    owner_role(factory, by_role.id, "payback")
    sender_op(factory, ids[family.id], "PUT", {"answer": "income", "label": "Test"}, now)
    sender_op(factory, ids[ignored.id], "PUT", {"answer": "ignore", "label": None}, now)
    run("recompute")
    assert count(run("payback-audit"), "silent person parties") == 1  # the Ignore one
    sender_op(factory, ids[family.id], "DELETE", None, now + timedelta(seconds=1))
    assert count(run("payback-audit"), "silent person parties") == 2  # forgotten again


def test_restore_undoes_the_fix_only_where_a_friend_answer_is_on_record(
    run, db_engine, tmp_path
) -> None:
    run("import-sms", "--input", str(write_backup(tmp_path / "a.xml", full_rows())))
    factory = sessionmaker(db_engine, expire_on_commit=False)
    plain, friend, by_role = person_credits(factory)[:3]
    ids = {t.id: add_party(factory, t, kind="person", category="food_drinks", source="app")
           for t in (plain, friend, by_role)}  # fmt: skip
    run("recompute")
    assert "changed 3 parties" in run("payback-audit", "--fix", "--apply")
    fixed, parties_fixed = state(factory)

    nothing = run("payback-audit", "--restore")  # no answer on record yet: nothing to restore
    assert count(nothing, "parties to restore") == 0
    assert "restored 0 parties" in run("payback-audit", "--restore", "--apply")
    assert state(factory)[0]["net"] == fixed["net"]

    sender_op(factory, ids[friend.id], "PUT", FRIEND, datetime.now(UTC))  # a Friend answer
    owner_role(factory, by_role.id, "payback")  # one credit only: not a party answer
    run("recompute")
    marked, _ = state(factory)
    dry = run("payback-audit", "--restore")
    assert count(dry, "parties to restore") == 1 and count(dry, "their credits") >= 1
    assert "dry run" in dry and state(factory)[0] == marked

    applied = run("payback-audit", "--restore", "--apply")
    assert "restored 1 party" in applied and "recompute run" in applied
    after, parties_after = state(factory)
    assert after["roles"][friend.id] == ("payback", "owner")  # the answered one is back
    assert after["roles"][plain.id] == marked["roles"][plain.id]  # unanswered: untouched
    with factory() as s:
        assert s.get(Party, ids[friend.id]).kind == "person"
        assert s.get(Party, ids[plain.id]).kind == "unsure"
        assert s.get(Party, ids[by_role.id]).kind == "unsure"
    # Net moved only by the answered party's credits.
    others = [i for i, r in after["roles"].items() if i != friend.id]
    assert all(after["roles"][i] == marked["roles"][i] for i in others if i in marked["roles"])

    again = run("payback-audit", "--restore", "--apply")  # idempotent
    assert "restored 0 parties" in again and state(factory) == (after, parties_after)
