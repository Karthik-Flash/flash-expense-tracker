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


def test_apply_needs_fix(run, db_engine) -> None:
    assert "--apply needs --fix" in run("payback-audit", "--apply", code=2)
