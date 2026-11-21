"""who gave a party its display name: app, terminal, file or statement

- parties.name_source: set with every display name from now on (D-116). "statement": a
  payer name taken from the owner's bank statement by `statement-names --apply`, only for a
  party with no name yet. Null: no name, or a name given before 4A. Existing rows stay
  null: no migration writes owner data. No new table, so no new row level security.

Revision 0011 was not used (4H needed no migration).

Revision ID: 0012
Revises: 0010
Create Date: 2026-11-21 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCES = "name_source IS NULL OR name_source IN ('file', 'terminal', 'app', 'statement')"


def upgrade() -> None:
    with op.batch_alter_table("parties") as batch:
        batch.add_column(sa.Column("name_source", sa.String(length=10), nullable=True))
        batch.create_check_constraint("ck_party_name_source", SOURCES)


def downgrade() -> None:
    with op.batch_alter_table("parties") as batch:
        batch.drop_constraint("ck_party_name_source", type_="check")
        batch.drop_column("name_source")
