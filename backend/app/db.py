from collections.abc import Iterator

from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# Small pool: one Render free instance against the Supabase session pooler.
# connect_timeout makes an unreachable Postgres fail fast instead of hanging.
_is_postgres = make_url(settings.database_url).get_backend_name() == "postgresql"
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=2,
    max_overflow=2,
    connect_args={"connect_timeout": 5} if _is_postgres else {},
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all ORM models. Alembic autogenerate reads its metadata."""


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with SessionLocal() as session:
        yield session
