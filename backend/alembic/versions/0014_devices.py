"""devices: phones that upload bank SMS

- devices (D-122): one row per phone install of an owner. The device token is shown to the
  phone once and stored only as its SHA-256 (`token_hash`, unique); it can call the SMS
  ingest route and nothing else. `revoked_at` set: the token stops working; rows are never
  deleted. On Postgres, row level security is enabled with no policies.

Additive: no existing table changes.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-22 02:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),  # fmt: skip
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "device_id", name="uq_device_owner_device"),
        sa.UniqueConstraint("token_hash", name="uq_device_token_hash"),
    )
    op.create_index("ix_devices_owner_id", "devices", ["owner_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE devices ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_devices_owner_id", table_name="devices")
    op.drop_table("devices")
