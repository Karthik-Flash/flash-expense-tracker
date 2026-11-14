"""import pipeline tables

Additive only. Money is BIGINT paise, times are timestamptz (UTC). On
Postgres, row level security is enabled on every new table with no policies:
defence in depth, as the Data API is off and the app connects as table owner.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14 18:18:06.465091

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLES = (
    "import_batches",
    "raw_messages",
    "parse_results",
    "transactions",
    "transaction_sources",
    "duplicate_candidates",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "import_batches",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("app_version", sa.String(length=20), nullable=False),
        sa.Column("parser_versions", sa.JSON(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.CheckConstraint("status IN ('running', 'done', 'failed')", name="ck_batch_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_import_batches_status"), "import_batches", ["status"], unique=False)
    op.create_table(
        "transactions",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("direction", sa.String(length=6), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("account_last4", sa.String(length=4), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=True),
        sa.Column("counterparty_raw", sa.Text(), nullable=True),
        sa.Column("reference", sa.String(length=128), nullable=True),
        sa.Column("balance_paise", sa.BigInteger(), nullable=True),
        sa.Column("txn_time_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_inferred", sa.Boolean(), nullable=False),
        sa.Column("bank", sa.String(length=20), nullable=False),
        sa.Column("hints", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("direction IN ('debit', 'credit')", name="ck_txn_direction"),
        sa.CheckConstraint("status IN ('active', 'superseded')", name="ck_txn_status"),
        sa.CheckConstraint("amount_paise > 0", name="ck_txn_amount_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "dedupe_key", name="uq_txn_owner_key"),
    )
    op.create_index(op.f("ix_transactions_status"), "transactions", ["status"], unique=False)
    op.create_index(
        op.f("ix_transactions_txn_time_utc"), "transactions", ["txn_time_utc"], unique=False
    )
    op.create_index(
        "ix_txn_candidate",
        "transactions",
        ["owner_id", "bank", "direction", "amount_paise"],
        unique=False,
    )
    op.create_table(
        "duplicate_candidates",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("txn_a", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("txn_b", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("rule", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('open', 'confirmed', 'dismissed')", name="ck_candidate_status"
        ),
        sa.CheckConstraint("txn_a < txn_b", name="ck_candidate_order"),
        sa.ForeignKeyConstraint(
            ["txn_a"],
            ["transactions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["txn_b"],
            ["transactions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("txn_a", "txn_b", name="uq_candidate_pair"),
    )
    op.create_index(
        op.f("ix_duplicate_candidates_status"), "duplicate_candidates", ["status"], unique=False
    )
    op.create_table(
        "raw_messages",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("sender_raw", sa.String(length=64), nullable=False),
        sa.Column("sender_core", sa.String(length=64), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "first_batch_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('sms_backup', 'manual', 'statement', 'live_sms', 'gmail')",
            name="ck_raw_source",
        ),
        sa.ForeignKeyConstraint(
            ["first_batch_id"],
            ["import_batches.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "content_hash", name="uq_raw_owner_hash"),
    )
    op.create_index(
        op.f("ix_raw_messages_sender_core"), "raw_messages", ["sender_core"], unique=False
    )
    op.create_table(
        "parse_results",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column(
            "raw_message_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column("parser_version", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("unknown_reason", sa.String(length=32), nullable=True),
        sa.Column("unknown_detail", sa.Text(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("bank", sa.String(length=20), nullable=True),
        sa.Column("template_id", sa.String(length=20), nullable=True),
        sa.Column("type", sa.String(length=20), nullable=True),
        sa.Column("direction", sa.String(length=6), nullable=True),
        sa.Column("amount_paise", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("account_last4", sa.String(length=4), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=True),
        sa.Column("counterparty_raw", sa.Text(), nullable=True),
        sa.Column("reference", sa.String(length=128), nullable=True),
        sa.Column("balance_paise", sa.BigInteger(), nullable=True),
        sa.Column("txn_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_inferred", sa.Boolean(), nullable=True),
        sa.Column("hints", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('parsed', 'unknown')", name="ck_parse_status"),
        sa.ForeignKeyConstraint(
            ["raw_message_id"],
            ["raw_messages.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_message_id", "parser_version", name="uq_parse_raw_version"),
    )
    op.create_index(
        op.f("ix_parse_results_is_current"), "parse_results", ["is_current"], unique=False
    )
    op.create_index(op.f("ix_parse_results_type"), "parse_results", ["type"], unique=False)
    op.create_index(
        op.f("ix_parse_results_unknown_reason"), "parse_results", ["unknown_reason"], unique=False
    )
    op.create_index(
        "uq_parse_current",
        "parse_results",
        ["raw_message_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )
    op.create_table(
        "transaction_sources",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column(
            "transaction_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column(
            "raw_message_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column(
            "parse_result_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["parse_result_id"],
            ["parse_results.id"],
        ),
        sa.ForeignKeyConstraint(
            ["raw_message_id"],
            ["raw_messages.id"],
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_message_id", name="uq_source_raw"),
    )
    op.create_index(
        op.f("ix_transaction_sources_transaction_id"),
        "transaction_sources",
        ["transaction_id"],
        unique=False,
    )
    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_transaction_sources_transaction_id"), table_name="transaction_sources")
    op.drop_table("transaction_sources")
    op.drop_index(
        "uq_parse_current",
        table_name="parse_results",
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )
    op.drop_index(op.f("ix_parse_results_unknown_reason"), table_name="parse_results")
    op.drop_index(op.f("ix_parse_results_type"), table_name="parse_results")
    op.drop_index(op.f("ix_parse_results_is_current"), table_name="parse_results")
    op.drop_table("parse_results")
    op.drop_index(op.f("ix_raw_messages_sender_core"), table_name="raw_messages")
    op.drop_table("raw_messages")
    op.drop_index(op.f("ix_duplicate_candidates_status"), table_name="duplicate_candidates")
    op.drop_table("duplicate_candidates")
    op.drop_index("ix_txn_candidate", table_name="transactions")
    op.drop_index(op.f("ix_transactions_txn_time_utc"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_status"), table_name="transactions")
    op.drop_table("transactions")
    op.drop_index(op.f("ix_import_batches_status"), table_name="import_batches")
    op.drop_table("import_batches")
