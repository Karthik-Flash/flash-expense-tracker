from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # Local default is a SQLite file; production uses Supabase Postgres via env.
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'flash.db').as_posix()}"
    # Comma-separated list, easy to set as a single env var on Render.
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
