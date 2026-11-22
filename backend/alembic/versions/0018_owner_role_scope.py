"""owner_roles.scope (premium C)

- owner_roles.scope (D-149): "one" when the owner answered Paid back or Not paid back for this
  one credit; null for every other row (a person-level answer, Not a payment, the owner
  file, every row stored before). A person-level answer never overwrites or deletes a "one"
  row, so a per-credit answer beats it. Nullable: additive. owner_roles already has RLS and
  is deleted with the account.
The downgrade drops the column (per-credit answers then read as plain role decisions).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-23 06:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("owner_roles", sa.Column("scope", sa.String(length=10), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("owner_roles") as batch:
        batch.drop_column("scope")
