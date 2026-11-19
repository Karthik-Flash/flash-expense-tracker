"""client ops

Additive only. One new table, client_ops: the final answer of each owner action
sent with an Idempotency-Key, keyed by (owner_id, op_id), never deleted (D-091,
D-092), and a mark for a write whose recompute was deferred (D-094). On
Postgres, row level security is enabled with no policies, as for every app table.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-19 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "client_ops",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("op_id", sa.Uuid(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(length=6), nullable=False),
        sa.Column("path", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "recompute_pending", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.PrimaryKeyConstraint("owner_id", "op_id"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE client_ops ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("client_ops")
