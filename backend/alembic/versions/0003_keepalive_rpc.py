"""keepalive schema and ping() for the Data API heartbeat

Postgres only; a no-op on SQLite. cron-job.org calls keepalive.ping() through
the Supabase Data API, which exposes only the keepalive schema (D-053). The
function is SECURITY DEFINER: anon may execute it but has no access to any
table. It writes the heartbeat row and returns {"ok": true}, nothing else.
RLS on heartbeat (no policies) keeps the table closed to anon even if the
public schema were ever exposed.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15 10:00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PING = """
CREATE OR REPLACE FUNCTION keepalive.ping() RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    INSERT INTO public.heartbeat (id, last_seen) VALUES (1, now())
    ON CONFLICT (id) DO UPDATE SET last_seen = EXCLUDED.last_seen;
    RETURN json_build_object('ok', true);
END
$$
"""

# Supabase has an anon role (the publishable key); plain Postgres does not.
GRANT_ANON = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        GRANT USAGE ON SCHEMA keepalive TO anon;
        GRANT EXECUTE ON FUNCTION keepalive.ping() TO anon;
    END IF;
END
$$
"""

REVOKE_ANON = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE EXECUTE ON FUNCTION keepalive.ping() FROM anon;
        REVOKE USAGE ON SCHEMA keepalive FROM anon;
    END IF;
END
$$
"""


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE SCHEMA IF NOT EXISTS keepalive")
    op.execute(PING)
    op.execute("REVOKE ALL ON FUNCTION keepalive.ping() FROM PUBLIC")
    op.execute(GRANT_ANON)
    op.execute("ALTER TABLE public.heartbeat ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.heartbeat DISABLE ROW LEVEL SECURITY")
    op.execute(REVOKE_ANON)
    op.execute("DROP FUNCTION IF EXISTS keepalive.ping()")
    op.execute("DROP SCHEMA IF EXISTS keepalive")
