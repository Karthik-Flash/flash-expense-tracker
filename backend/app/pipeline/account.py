"""Delete my account (D-131): every row of one owner, in every table, in one transaction.

This is the one exception to "nothing is deleted". The tables come from the models, children
first (the reverse of SQLAlchemy's dependency order), so a new table cannot be forgotten:
`plan()` fails for a table it cannot place, and a test checks every table of the metadata.

- a table with an `owner_id` column: its rows of the owner;
- a table keyed only through another table (parse results by raw message, sources and
  duplicate candidates by transaction): BY_PARENT;
- invites: the ones the owner used or made;
- GLOBAL tables hold no one's data (heartbeat) or outlive the account on purpose
  (auth_deletions: the login still to delete when Supabase could not be reached).

Counts per table only; never a value.
"""

import uuid
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import Table, delete, or_, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import AuthDeletion, Invite, RawMessage, Transaction
from app.pipeline.recompute import owner_lock

GLOBAL = frozenset({"heartbeat", "auth_deletions"})
BY_PARENT = {  # table -> (its columns that point at an owned table's id, that table)
    "parse_results": (("raw_message_id",), RawMessage),
    "transaction_sources": (("transaction_id",), Transaction),
    "duplicate_candidates": (("txn_a", "txn_b"), Transaction),
}


def tables() -> list[Table]:
    """Every app table, children before the tables they point at."""
    return list(reversed(Base.metadata.sorted_tables))


def placed(table: Table) -> str:
    """How a table's rows of one owner are found: owner_id, parent, invites, or global."""
    if table.name in GLOBAL:
        return "global"
    if table.name in BY_PARENT:
        return "parent"
    if table.name == Invite.__tablename__:
        return "invites"
    if "owner_id" in table.c:
        return "owner_id"
    raise ValueError(f"table {table.name} has no rule for deleting an account")


def delete_owner(session: Session, owner: uuid.UUID, auth_uid: str) -> Counter:
    """Every row of the owner, then a pending auth deletion for the login. Commits."""
    counts: Counter = Counter()
    with owner_lock(session, owner):
        for table in tables():
            rule = placed(table)
            if rule == "global":
                continue
            if rule == "parent":
                columns, parent = BY_PARENT[table.name]
                owned = select(parent.id).where(parent.owner_id == owner).scalar_subquery()
                where = or_(*(table.c[c].in_(owned) for c in columns))
            elif rule == "invites":
                where = or_(table.c.used_by == owner, table.c.created_by == owner)
            else:
                where = table.c.owner_id == owner
            counts[table.name] = session.execute(delete(table).where(where)).rowcount or 0
        session.add(AuthDeletion(auth_uid=auth_uid, requested_at=datetime.now(UTC), attempts=0))
        session.commit()
    return counts


def finish_auth(session: Session, auth_uid: str, delete_user) -> bool:
    """Try to delete the login (Supabase); True when it is gone. A failure keeps the pending
    row with the error type, for `auth-cleanup`. Commits."""
    row = session.get(AuthDeletion, auth_uid)
    if row is None:
        return True
    row.attempts += 1
    try:
        delete_user(auth_uid)
    except Exception as exc:  # the message could hold data: the type only
        row.last_error = (getattr(exc, "code", None) or type(exc).__name__)[:40]
        session.commit()
        return False
    session.delete(row)
    session.commit()
    return True
