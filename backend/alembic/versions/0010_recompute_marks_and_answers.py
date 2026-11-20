"""recompute marks; the owner's explicit Friend or Family answer on a party

- recompute_marks: one row per owner whose owner data changed since the last recompute
  (D-106). Every owner write sets it in the write's own transaction; the next read
  recomputes and removes it. `failed_at` and `failure` (an error type, never a value) hold
  back retries for 5 minutes. On Postgres, row level security is enabled with no policies.
- parties.answered_at: when the owner last answered Friend or Family for this party (owner
  data, set only by an owner action). payback-audit never calls such a party silent
  (D-099 as corrected in 4F-B). Existing rows stay null: no migration writes owner data.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-21 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recompute_marks",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("owner_id"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE recompute_marks ENABLE ROW LEVEL SECURITY")
    with op.batch_alter_table("parties") as batch:
        batch.add_column(sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("parties") as batch:
        batch.drop_column("answered_at")
    op.drop_table("recompute_marks")
