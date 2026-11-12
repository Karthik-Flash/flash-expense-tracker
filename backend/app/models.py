from datetime import datetime

from sqlalchemy import DateTime, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Heartbeat(Base):
    """Single row (id=1) written by /health/db so Supabase sees regular activity."""

    __tablename__ = "heartbeat"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
