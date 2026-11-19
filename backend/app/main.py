from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app import __version__
from app.api import health, snapshot, v1
from app.config import settings

VERCEL_ORIGIN = "https://flash-expense-tracker.vercel.app"
DEV_PREFIXES = ("http://localhost:", "http://127.0.0.1:")


def allowed_origins(origins: list[str]) -> list[str]:
    """Only the Vercel app and local dev servers, whatever CORS_ORIGINS holds."""
    return [o for o in origins if o == VERCEL_ORIGIN or o.startswith(DEV_PREFIXES)]


app = FastAPI(title="Flash Expense Tracker", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(settings.cors_origin_list),
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "If-None-Match"],
    expose_headers=["ETag"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.include_router(health.router)
app.include_router(v1.router)
app.include_router(snapshot.router)
