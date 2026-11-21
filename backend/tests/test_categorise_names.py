"""Categories guessed from names (categorise-1.2.0, D-119). FAKE names only."""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.engine.categorise import (
    CATEGORIES,
    CATEGORISE_VERSION,
    GUESS_RULES,
    Categorised,
    breakdown,
    categorise,
)
from app.engine.reconcile import OwnerData, Party, Txn, derive, totals

NAMES = json.loads(
    (Path(__file__).parent / "fixtures" / "category_names.json").read_text(encoding="utf-8")
)["names"]
T = datetime(2026, 1, 1, tzinfo=UTC)
EVER = (datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))


def debits() -> list[Txn]:
    return [Txn(i, "HDFC", "debit", "debit", 10_000 + i, "0001", "upi", name, T)
            for i, (name, _) in enumerate(NAMES, 1)]  # fmt: skip


def test_every_fake_name_gets_its_category() -> None:
    assert CATEGORISE_VERSION == "categorise-1.2.0"
    assert len(NAMES) >= 150 and {c for _, c in NAMES} <= set(CATEGORIES)
    txns = debits()
    got = categorise(txns, OwnerData(), derive(txns))
    wrong = [(name, want, got[i].category) for i, (name, want) in enumerate(NAMES, 1)
             if got[i].category != want]  # fmt: skip
    assert wrong == []
    traps = {"Sai Medical Hall": "health", "Ravi Kumar": "people", "R K Enterprises":
             "uncategorised", "Hotel Annapurna": "uncategorised", "Mr Arjun S": "people",
             "Taj Travels": "travel", "Kumar Book Depot": "education", "Hunger Point Foodfill":
             "food_drinks", "ravi.k92@okaxis": "people",
             "TEST PROTEIN SHOP": "uncategorised"}  # fmt: skip
    assert traps.items() <= dict(NAMES).items()
    assert all(got[i].rule in GUESS_RULES | {"NONE", "KW_conflict"} for i in got)


def test_the_owner_still_wins_over_a_guess() -> None:
    txns = debits()[:3]  # three food places
    owner = OwnerData(parties=(Party("business", texts=(NAMES[0][0],), category="travel"),),
                      categories={2: "gifts_donations"})  # fmt: skip
    got = categorise(txns, owner, derive(txns, owner))
    assert (got[1].category, got[1].rule) == ("travel", "OWNER_party")
    assert (got[2].category, got[2].rule) == ("gifts_donations", "OWNER_txn")
    assert got[3].rule == "KEYWORD"


def test_totals_are_identical_with_or_without_guesses() -> None:
    """Only the split changes: Spent, Paid back and Net never depend on a category."""
    txns = [*debits(), Txn(999, "HDFC", "credit", "credit", 5_000, "0001", "upi",
                           "test.friend@okaxis", T)]  # fmt: skip
    result = derive(txns)
    guessed = categorise(txns, OwnerData(), result)
    flat = {i: Categorised("uncategorised", "NONE", "engine") for i in guessed}
    t = totals(txns, result.roles, *EVER)
    assert sum(breakdown(txns, result.roles, guessed, *EVER).values()) == t.spent_paise
    assert sum(breakdown(txns, result.roles, flat, *EVER).values()) == t.spent_paise
    split = breakdown(txns, result.roles, guessed, *EVER)
    assert len(split) > 5 and split != breakdown(txns, result.roles, flat, *EVER)
