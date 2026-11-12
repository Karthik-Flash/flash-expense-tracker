import logging
import secrets
import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import DateTime, bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.config import settings
from app.db import get_session

log = logging.getLogger(__name__)
router = APIRouter()

# Same SQL works on Postgres and SQLite.
UPSERT_HEARTBEAT = text(
    "INSERT INTO heartbeat (id, last_seen) VALUES (1, :now) "
    "ON CONFLICT (id) DO UPDATE SET last_seen = excluded.last_seen"
).bindparams(bindparam("now", type_=DateTime(timezone=True)))


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness only. Never touches the database."""
    return {"status": "ok", "version": __version__}


@router.get("/health/db")
def health_db(
    session: Annotated[Session, Depends(get_session)], token: str = ""
) -> dict[str, str | int]:
    """Write the heartbeat row. Pinged daily so Supabase does not pause the project."""
    expected = settings.ping_token.encode()
    if not expected or not secrets.compare_digest(token.encode(), expected):
        raise HTTPException(status_code=401, detail="Invalid or missing token")

    start = time.perf_counter()
    try:
        session.execute(UPSERT_HEARTBEAT, {"now": datetime.now(UTC)})
        session.commit()
    except SQLAlchemyError:
        log.exception("Heartbeat write failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return {"db": "ok", "latency_ms": round((time.perf_counter() - start) * 1000)}
