from pathlib import Path
from uuid import UUID

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DRIVER_SCHEME = "postgresql+psycopg://"  # psycopg 3, pinned in requirements.txt


def normalize_database_url(url: str) -> str:
    """Point plain postgres:// and postgresql:// URLs at the pinned psycopg driver."""
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            return DRIVER_SCHEME + url.removeprefix(scheme)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # Local default is a SQLite file; production uses Supabase Postgres via env.
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'flash.db').as_posix()}"
    # Comma-separated list, easy to set as a single env var on Render.
    cors_origins: str = "http://localhost:5173"
    # Shared secret for the X-Ping-Token header on /health/db.
    ping_token: str = ""
    # Owner of imported data until auth exists (single user).
    owner_id: UUID = UUID("00000000-0000-0000-0000-000000000001")

    _normalize_url = field_validator("database_url")(normalize_database_url)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
