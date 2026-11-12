import logging
import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.config import settings
from app.db import get_session

log = logging.getLogger(__name__)
router = APIRouter()

# The database sets the time. Same SQL works on Postgres and SQLite.
UPSERT_HEARTBEAT = text(
    "INSERT INTO heartbeat (id, last_seen) VALUES (1, CURRENT_TIMESTAMP) "
    "ON CONFLICT (id) DO UPDATE SET last_seen = CURRENT_TIMESTAMP"
)


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness only. Never touches the database."""
    return {"status": "ok", "version": __version__}


@router.get("/health/db")
def health_db(
    session: Annotated[Session, Depends(get_session)],
    x_ping_token: Annotated[str | None, Header()] = None,
) -> dict[str, str | int]:
    """Write the heartbeat row. Pinged daily so Supabase does not pause the project."""
    if not settings.ping_token:
        raise HTTPException(status_code=503, detail="ping token not configured")
    if x_ping_token is None or not secrets.compare_digest(
        x_ping_token.encode(), settings.ping_token.encode()
    ):
        raise HTTPException(status_code=401, detail="invalid or missing X-Ping-Token")

    start = time.perf_counter()
    try:
        session.execute(UPSERT_HEARTBEAT)
        session.commit()
    except SQLAlchemyError:
        log.exception("Heartbeat write failed")
        raise HTTPException(status_code=503, detail="database unavailable") from None
    return {"db": "ok", "latency_ms": round((time.perf_counter() - start) * 1000)}
