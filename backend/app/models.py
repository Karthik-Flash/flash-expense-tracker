from datetime import datetime

from sqlalchemy import DateTime, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Heartbeat(Base):
    """Single row (id=1) written by /health/db so Supabase sees regular activity.

    last_seen is set by the database clock (CURRENT_TIMESTAMP, i.e. now() on
    Postgres) in the upsert, never by the app.
    """

    __tablename__ = "heartbeat"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
