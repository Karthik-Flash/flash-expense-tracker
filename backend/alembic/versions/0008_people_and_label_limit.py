"""people: names and joins; one label limit of 30

- labels.name: 30 characters (was 80), with a CHECK so SQLite holds it too (D-097).
  Stops with a clear message, before changing anything, when a stored label is longer.
- parties.display_name: the name the owner gives a person in the app (D-096).
- parties.kind: also "unsure", a party with no role answer yet.
- party_texts.created_at and ended_at: a join that ends keeps its row. The unique
  (owner_id, text) constraint becomes a unique index on active rows only.

No new table, so no new row level security.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-20 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LABEL_MAX = 30
KINDS_NEW = "kind IN ('person', 'business', 'unsure')"
KINDS_OLD = "kind IN ('person', 'business')"
ACTIVE = sa.text("ended_at IS NULL")


def upgrade() -> None:
    too_long = sa.text(f"SELECT count(*) FROM labels WHERE length(name) > {LABEL_MAX}")
    longer = op.get_bind().scalar(too_long)
    if longer:
        raise RuntimeError(
            f"0008 stopped: {longer} label(s) are longer than {LABEL_MAX} characters. "
            "Shorten them first; nothing was changed."
        )
    with op.batch_alter_table("labels") as batch:
        batch.alter_column(
            "name", existing_type=sa.String(80), type_=sa.String(LABEL_MAX), existing_nullable=False
        )
        batch.create_check_constraint("ck_label_name_length", f"length(name) <= {LABEL_MAX}")
    with op.batch_alter_table("parties") as batch:
        batch.add_column(sa.Column("display_name", sa.String(LABEL_MAX), nullable=True))
        batch.drop_constraint("ck_party_kind", type_="check")
        batch.create_check_constraint("ck_party_kind", KINDS_NEW)
    with op.batch_alter_table("party_texts") as batch:
        batch.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            )
        )
        batch.add_column(sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))
        batch.drop_constraint("uq_party_text", type_="unique")
    op.create_index(
        "uq_party_text_active",
        "party_texts",
        ["owner_id", "text"],
        unique=True,
        postgresql_where=ACTIVE,
        sqlite_where=ACTIVE,
    )


def downgrade() -> None:
    """Back to 0007. Ended join rows and the app's names go; an unsure party becomes a
    business (no role answer either way)."""
    op.drop_index("uq_party_text_active", table_name="party_texts")
    op.execute("DELETE FROM party_texts WHERE ended_at IS NOT NULL")
    with op.batch_alter_table("party_texts") as batch:
        batch.drop_column("ended_at")
        batch.drop_column("created_at")
        batch.create_unique_constraint("uq_party_text", ["owner_id", "text"])
    op.execute("UPDATE parties SET kind = 'business' WHERE kind = 'unsure'")
    with op.batch_alter_table("parties") as batch:
        batch.drop_constraint("ck_party_kind", type_="check")
        batch.create_check_constraint("ck_party_kind", KINDS_OLD)
        batch.drop_column("display_name")
    with op.batch_alter_table("labels") as batch:
        batch.drop_constraint("ck_label_name_length", type_="check")
        batch.alter_column(
            "name", existing_type=sa.String(LABEL_MAX), type_=sa.String(80), existing_nullable=False
        )
