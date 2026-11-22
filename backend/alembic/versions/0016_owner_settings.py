"""owner_settings: the owner's choices about how totals are shown (5B-1)

- owner_settings (D-136): one row per owner, written only when the owner changes a setting
  (no row: every default). count_investments_in_spent, default false: investments the owner
  confirmed (role investment) count in Spent only when it is true. updated_at, source.
On Postgres, row level security is enabled with no policies. Additive; the downgrade drops
the table (the owner's setting goes back to the default).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-22 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owner_settings",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "count_investments_in_spent", sa.Boolean(), server_default=sa.false(), nullable=False
        ),  # fmt: skip
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "source IN ('file', 'terminal', 'app')", name="ck_owner_setting_source"
        ),  # fmt: skip
        sa.PrimaryKeyConstraint("owner_id"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE owner_settings ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("owner_settings")
