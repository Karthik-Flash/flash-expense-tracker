"""derived tables

Additive only: three new tables, nothing existing changes. They hold what the
engine works out (merchant, role, links) and are written only by recompute:
one pure function of the active transactions, the owner tables and the engine
versions (D-059). They can be emptied and rebuilt at any time. On Postgres,
row level security is enabled on every new table with no policies, as in 0002.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-16 08:57:22.559550

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "derive_runs",
    "txn_derived",
    "txn_links",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "derive_runs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("trigger", sa.String(length=10), nullable=False),
        sa.Column("versions", sa.JSON(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.CheckConstraint("status IN ('running', 'done', 'failed')", name="ck_run_status"),
        sa.CheckConstraint(
            "trigger IN ('import', 'reparse', 'owner', 'manual')", name="ck_run_trigger"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "txn_derived",
        sa.Column(
            "transaction_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_key", sa.Text(), nullable=True),
        sa.Column("merchant_kind", sa.String(length=10), nullable=False),
        sa.Column("merchant_confidence", sa.String(length=4), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("brand_id", sa.String(length=40), nullable=True),
        sa.Column("merchant_reasons", sa.JSON(), nullable=False),
        sa.Column("party_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column(
            "own_account_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("role_rule", sa.String(length=32), nullable=False),
        sa.Column("role_basis", sa.String(length=6), nullable=False),
        sa.Column("role_reasons", sa.JSON(), nullable=False),
        sa.Column(
            "duplicate_of", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True
        ),
        sa.CheckConstraint(
            "(role = 'duplicate') = (duplicate_of IS NOT NULL)", name="ck_derived_duplicate"
        ),
        sa.CheckConstraint(
            "merchant_kind IN ('business', 'person', 'unsure', 'none')",
            name="ck_derived_merchant_kind",
        ),
        sa.CheckConstraint(
            "role IN ('spend', 'card_bill_counted', 'refund', 'payback', 'income', "
            "'self_transfer', 'card_bill_excluded', 'fd_move', 'ignored', 'uncertain', "
            "'duplicate')",
            name="ck_derived_role",
        ),
        sa.CheckConstraint("role_basis IN ('engine', 'owner')", name="ck_derived_basis"),
        sa.ForeignKeyConstraint(
            ["duplicate_of"],
            ["transactions.id"],
        ),
        sa.ForeignKeyConstraint(["own_account_id"], ["own_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
        ),
        sa.PrimaryKeyConstraint("transaction_id"),
    )
    op.create_index(
        op.f("ix_txn_derived_merchant_key"), "txn_derived", ["merchant_key"], unique=False
    )
    op.create_index(op.f("ix_txn_derived_role"), "txn_derived", ["role"], unique=False)
    op.create_table(
        "txn_links",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("txn_a", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("txn_b", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("rule", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("decided_by", sa.String(length=6), nullable=False),
        sa.CheckConstraint("decided_by IN ('engine', 'owner')", name="ck_link_decided_by"),
        sa.CheckConstraint(
            "kind IN ('duplicate', 'self_transfer', 'card_bill', 'refund', 'fd')",
            name="ck_link_kind",
        ),
        sa.CheckConstraint("status IN ('linked', 'candidate')", name="ck_link_status"),
        sa.CheckConstraint("txn_a < txn_b", name="ck_link_order"),
        sa.ForeignKeyConstraint(
            ["txn_a"],
            ["transactions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["txn_b"],
            ["transactions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "txn_a", "txn_b", name="uq_link_pair"),
    )
    op.create_index("ix_link_status_kind", "txn_links", ["status", "kind"], unique=False)

    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_link_status_kind", table_name="txn_links")
    op.drop_table("txn_links")
    op.drop_index(op.f("ix_txn_derived_role"), table_name="txn_derived")
    op.drop_index(op.f("ix_txn_derived_merchant_key"), table_name="txn_derived")
    op.drop_table("txn_derived")
    op.drop_table("derive_runs")
