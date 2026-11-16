"""owner tables

Additive only: six new tables, nothing existing changes. They hold what the
owner tells the app (own accounts, parties, decisions) and are written only by
owner commands, never by import, reparse or recompute (D-059, D-065). Every
row carries its source (file, terminal, app): a file load touches only file
rows (D-070). On Postgres, row level security is enabled on every new table
with no policies, as in 0002.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-16 08:48:58.763297

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "own_accounts",
    "own_identifiers",
    "parties",
    "party_texts",
    "owner_link_decisions",
    "owner_roles",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "own_accounts",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("bank", sa.String(length=20), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('bank_account', 'credit_card', 'wallet', 'fd')", name="ck_own_account_kind"
        ),
        sa.CheckConstraint("source IN ('file', 'terminal', 'app')", name="ck_own_account_source"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "label", name="uq_own_account_label"),
    )
    op.create_table(
        "parties",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("income_label", sa.String(length=80), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('person', 'business')", name="ck_party_kind"),
        sa.CheckConstraint("source IN ('file', 'terminal', 'app')", name="ck_party_source"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "label", name="uq_party_label"),
    )
    op.create_table(
        "own_identifiers",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "own_account_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.CheckConstraint("kind IN ('last4', 'text')", name="ck_own_identifier_kind"),
        sa.CheckConstraint(
            "source IN ('file', 'terminal', 'app')", name="ck_own_identifier_source"
        ),
        sa.ForeignKeyConstraint(
            ["own_account_id"],
            ["own_accounts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "kind", "value", "own_account_id", name="uq_own_identifier"
        ),
    )
    op.create_index(
        op.f("ix_own_identifiers_own_account_id"),
        "own_identifiers",
        ["own_account_id"],
        unique=False,
    )
    op.create_table(
        "owner_link_decisions",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("txn_a", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("txn_b", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("verdict", sa.String(length=10), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "kind IN ('duplicate', 'self_transfer', 'card_bill', 'refund', 'fd')",
            name="ck_owner_link_kind",
        ),
        sa.CheckConstraint("source IN ('file', 'terminal', 'app')", name="ck_owner_link_source"),
        sa.CheckConstraint("verdict IN ('same', 'different')", name="ck_owner_link_verdict"),
        sa.CheckConstraint("txn_a < txn_b", name="ck_owner_link_order"),
        sa.ForeignKeyConstraint(
            ["txn_a"],
            ["transactions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["txn_b"],
            ["transactions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "kind", "txn_a", "txn_b", name="uq_owner_link"),
    )
    op.create_table(
        "owner_roles",
        sa.Column(
            "transaction_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "role IN ('spend', 'card_bill_counted', 'refund', 'payback', 'income', "
            "'self_transfer', 'card_bill_excluded', 'fd_move', 'ignored', 'uncertain')",
            name="ck_owner_role_role",
        ),
        sa.CheckConstraint("source IN ('file', 'terminal', 'app')", name="ck_owner_role_source"),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
        ),
        sa.PrimaryKeyConstraint("transaction_id"),
    )
    op.create_table(
        "party_texts",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("party_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("text", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.CheckConstraint("source IN ('file', 'terminal', 'app')", name="ck_party_text_source"),
        sa.ForeignKeyConstraint(
            ["party_id"],
            ["parties.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "text", name="uq_party_text"),
    )
    op.create_index(op.f("ix_party_texts_party_id"), "party_texts", ["party_id"], unique=False)

    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_party_texts_party_id"), table_name="party_texts")
    op.drop_table("party_texts")
    op.drop_table("owner_roles")
    op.drop_table("owner_link_decisions")
    op.drop_index(op.f("ix_own_identifiers_own_account_id"), table_name="own_identifiers")
    op.drop_table("own_identifiers")
    op.drop_table("parties")
    op.drop_table("own_accounts")
