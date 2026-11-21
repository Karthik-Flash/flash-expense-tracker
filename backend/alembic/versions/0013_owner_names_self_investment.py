"""owner name variants; parties of kind self and investment; role investment

- owner_names: "Your name as banks show it" (D-117), one row per variant, owner data. On
  Postgres, row level security is enabled with no policies.
- parties.kind gains "self" ("It's me": every payment of the party is a transfer between
  the owner's own accounts, D-117) and "investment" (money to or from a broker or fund,
  D-118).
- parties.dismissed: the suggestions the owner answered No to ("self", "investment").
- owner_roles.role and txn_derived.role gain "investment": in no total, like fd_move, but
  shown as an investment and never paired as an FD closure (D-118).

No migration writes owner data: existing rows keep their values.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-21 21:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


OLD_KINDS = ("person", "business", "unsure")
NEW_KINDS = (*OLD_KINDS, "self", "investment")
OLD_ROLES = ("spend", "card_bill_counted", "refund", "payback", "income", "self_transfer",
             "card_bill_excluded", "fd_move", "ignored", "uncertain")  # fmt: skip
NEW_ROLES = (*OLD_ROLES[:8], "investment", *OLD_ROLES[8:])


def _kinds(values: tuple[str, ...]) -> None:
    with op.batch_alter_table("parties") as batch:
        batch.drop_constraint("ck_party_kind", type_="check")
        batch.create_check_constraint("ck_party_kind", _in("kind", values))


def _roles(values: tuple[str, ...]) -> None:
    with op.batch_alter_table("owner_roles") as batch:
        batch.drop_constraint("ck_owner_role_role", type_="check")
        batch.create_check_constraint("ck_owner_role_role", _in("role", values))
    with op.batch_alter_table("txn_derived") as batch:
        batch.drop_constraint("ck_derived_role", type_="check")
        batch.create_check_constraint("ck_derived_role", _in("role", (*values, "duplicate")))


def upgrade() -> None:
    op.create_table(
        "owner_names",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),  # fmt: skip
        sa.CheckConstraint("source IN ('file', 'terminal', 'app')", name="ck_owner_name_source"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name", name="uq_owner_name"),
    )
    op.create_index("ix_owner_names_owner_id", "owner_names", ["owner_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE owner_names ENABLE ROW LEVEL SECURITY")
    with op.batch_alter_table("parties") as batch:
        batch.add_column(sa.Column("dismissed", sa.JSON(), server_default="[]", nullable=False))
    _kinds(NEW_KINDS)
    _roles(NEW_ROLES)


def downgrade() -> None:
    _roles(OLD_ROLES)
    _kinds(OLD_KINDS)
    with op.batch_alter_table("parties") as batch:
        batch.drop_column("dismissed")
    op.drop_index("ix_owner_names_owner_id", table_name="owner_names")
    op.drop_table("owner_names")
