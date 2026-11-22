"""app_users, invites, auth_deletions: several users

- app_users (D-129): a Supabase login, the owner_id its data belongs to, role admin or
  member, email (the admin's member list), created_at, last_seen_at. It replaces the
  AUTH_USERS env var (an entry there is added here as admin on its first request).
- invites (D-128): one-time codes, stored as SHA-256 only; created_by and used_by are
  owner ids; 7-day expiry; revoked_at.
- auth_deletions (D-131): logins whose Supabase deletion failed after "Delete my account";
  the login id only, for the auth-cleanup command.
On Postgres, row level security is enabled with no policies on all three. Additive.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-22 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("app_users", "invites", "auth_deletions")


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("auth_uid", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),  # fmt: skip
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_app_user_role"),
        sa.PrimaryKeyConstraint("auth_uid"),
        sa.UniqueConstraint("owner_id", name="uq_app_user_owner"),
    )
    op.create_table(
        "invites",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),  # fmt: skip
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_by", sa.Uuid(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash", name="uq_invite_code_hash"),
    )
    op.create_index("ix_invites_created_by", "invites", ["created_by"])
    op.create_table(
        "auth_deletions",
        sa.Column("auth_uid", sa.String(length=64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("auth_uid"),
    )
    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("auth_deletions")
    op.drop_index("ix_invites_created_by", table_name="invites")
    op.drop_table("invites")
    op.drop_table("app_users")
