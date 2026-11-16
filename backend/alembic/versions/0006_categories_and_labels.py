"""categories and labels

Additive only. Three new owner tables (owner_categories, labels, txn_labels), a
nullable default category on parties, and three columns with defaults on
txn_derived (category, category_rule, category_basis). A category is a slug
with no CHECK, so a new category needs no migration (D-073). On Postgres, row
level security is enabled on every new table with no policies, as in 0002.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-16 14:40:49.602546

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("owner_categories", "labels", "txn_labels")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "labels",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('file', 'terminal', 'app')", name="ck_label_source"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name", name="uq_label_name"),
    )
    op.create_table(
        "owner_categories",
        sa.Column(
            "transaction_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "source IN ('file', 'terminal', 'app')", name="ck_owner_category_source"
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
        ),
        sa.PrimaryKeyConstraint("transaction_id"),
    )
    op.create_table(
        "txn_labels",
        sa.Column(
            "transaction_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("label_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.CheckConstraint("source IN ('file', 'terminal', 'app')", name="ck_txn_label_source"),
        sa.ForeignKeyConstraint(
            ["label_id"],
            ["labels.id"],
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
        ),
        sa.PrimaryKeyConstraint("transaction_id"),
    )
    op.create_index(op.f("ix_txn_labels_label_id"), "txn_labels", ["label_id"], unique=False)
    op.add_column("parties", sa.Column("category", sa.String(length=40), nullable=True))
    op.add_column(
        "txn_derived",
        sa.Column("category", sa.String(length=40), server_default="uncategorised", nullable=False),
    )
    op.add_column(
        "txn_derived",
        sa.Column("category_rule", sa.String(length=32), server_default="NONE", nullable=False),
    )
    op.add_column(
        "txn_derived",
        sa.Column("category_basis", sa.String(length=6), server_default="engine", nullable=False),
    )
    op.create_index(op.f("ix_txn_derived_category"), "txn_derived", ["category"], unique=False)
    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_txn_derived_category"), table_name="txn_derived")
    op.drop_column("txn_derived", "category_basis")
    op.drop_column("txn_derived", "category_rule")
    op.drop_column("txn_derived", "category")
    op.drop_column("parties", "category")
    op.drop_index(op.f("ix_txn_labels_label_id"), table_name="txn_labels")
    op.drop_table("txn_labels")
    op.drop_table("owner_categories")
    op.drop_table("labels")
