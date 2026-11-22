"""The per-owner data version (5B-2, D-140): a counter raised by every write, phone upload,
import and recompute, in the same database transaction as the change. The snapshot's ETag is
built from it (api/snapshot.py), so a client whose copy is current gets a 304 without the
server building the snapshot.

Raised in one place per kind of change: ops.write (every owner write from the app), the
device routes, the ingest route, recompute (any run that wrote rows), and the CLI after any
command that may write. A change that misses it would serve a stale copy, so a test checks
that every write route moves the ETag whenever it moves the document.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.models import DataVersion


def bump(session: Session, owner: uuid.UUID) -> None:
    """Raise the owner's version by one (an upsert); the caller commits."""
    dialect = postgresql if session.get_bind().dialect.name == "postgresql" else sqlite
    table = DataVersion.__table__
    statement = dialect.insert(table).values(owner_id=owner, version=1)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.owner_id], set_={"version": table.c.version + 1}
    )
    session.execute(statement)


def current(session: Session, owner: uuid.UUID) -> int:
    """The owner's version; 0 before anything changed."""
    return session.scalar(select(DataVersion.version).where(DataVersion.owner_id == owner)) or 0
