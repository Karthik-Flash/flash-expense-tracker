"""raw_messages.origin and data_versions (5B-2)

- raw_messages.origin (D-139): for an SMS a phone uploaded, "inbox" (read from the SMS inbox)
  or "live" (from the SMS_RECEIVED broadcast, sent when its inbox row did not come); null for
  every other source and for every row stored before. The ingest route uses it to tell the
  inbox copy and the live copy of one SMS apart from two real messages. Nullable: additive.
- data_versions (D-140): one counter per owner, raised by every write, upload and recompute;
  the snapshot's ETag comes from it, so an unchanged snapshot is a 304 without being built.
  RLS on (Postgres), no policies; deleted with the account (it has owner_id).
The downgrade drops both; nothing else changes.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-23 01:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("raw_messages", sa.Column("origin", sa.String(length=10), nullable=True))
    op.create_table(
        "data_versions",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("owner_id"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE data_versions ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("data_versions")
    with op.batch_alter_table("raw_messages") as batch:
        batch.drop_column("origin")
