from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app import __version__
from app.api import health, snapshot, v1
from app.config import settings
from app.requestlog import RequestLog

VERCEL_ORIGIN = "https://flash-expense-tracker.vercel.app"
DEV_PREFIXES = ("http://localhost:", "http://127.0.0.1:")


# Exactly what the app sends (frontend/src/api/headers.ts; tests/test_cors.py keeps the two
# equal, D-104). The browser blocks a cross-origin request whose preflight lacks one.
REQUEST_HEADERS = [
    "Authorization",
    "Accept",
    "Content-Type",
    "If-None-Match",
    "Idempotency-Key",
    "X-Defer-Recompute",
]
METHODS = ["GET", "PUT", "POST", "DELETE"]
EXPOSED = ["ETag"]


def allowed_origins(origins: list[str]) -> list[str]:
    """Only the Vercel app and local dev servers, whatever CORS_ORIGINS holds."""
    return [o for o in origins if o == VERCEL_ORIGIN or o.startswith(DEV_PREFIXES)]


app = FastAPI(title="Flash Expense Tracker", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(settings.cors_origin_list),
    allow_methods=METHODS,
    allow_headers=REQUEST_HEADERS,
    expose_headers=EXPOSED,
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(RequestLog, router_app=app)  # outermost: sees CORS answers too
app.include_router(health.router)
app.include_router(v1.router)
app.include_router(snapshot.router)
