"""owner checks of generic-parsed transactions; recompute trigger "read"

- txn_checks: the owner's "Looks right" on a transaction the generic parser read
  (D-101), one row per transaction. Owner data: written only by an owner action.
  On Postgres, row level security is enabled with no policies, as for every app table.
- derive_runs.trigger: also "read", a recompute the first read ran because the stored
  rows were made by other engine versions (D-102).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-20 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGERS_NEW = "trigger IN ('import', 'reparse', 'owner', 'manual', 'read')"
TRIGGERS_OLD = "trigger IN ('import', 'reparse', 'owner', 'manual')"


def upgrade() -> None:
    op.create_table(
        "txn_checks",
        sa.Column("transaction_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                  autoincrement=False, nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.CheckConstraint("source IN ('file', 'terminal', 'app')", name="ck_txn_check_source"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("transaction_id"),
    )  # fmt: skip
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE txn_checks ENABLE ROW LEVEL SECURITY")
    with op.batch_alter_table("derive_runs") as batch:
        batch.drop_constraint("ck_run_trigger", type_="check")
        batch.create_check_constraint("ck_run_trigger", TRIGGERS_NEW)


def downgrade() -> None:
    """Back to 0008. The owner's checks go; a run made on a read is recorded as "owner"."""
    op.execute("UPDATE derive_runs SET trigger = 'owner' WHERE trigger = 'read'")
    with op.batch_alter_table("derive_runs") as batch:
        batch.drop_constraint("ck_run_trigger", type_="check")
        batch.create_check_constraint("ck_run_trigger", TRIGGERS_OLD)
    op.drop_table("txn_checks")
