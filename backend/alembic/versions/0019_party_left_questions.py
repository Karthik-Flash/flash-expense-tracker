"""parties.category_left_at and parties.sender_left_at (5G-D)

"Leave as is" in To-do (D-156): the owner stops "Pick a category" or "Who sent you money?"
for one payee. The time it was said; null: still asked. Nothing else changes: no amount,
role or category moves. Nullable: additive. parties already has RLS and is deleted with the
account. The downgrade drops both columns (the questions come back).

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-26 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "parties", sa.Column("category_left_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("parties", sa.Column("sender_left_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("parties") as batch:
        batch.drop_column("sender_left_at")
        batch.drop_column("category_left_at")
