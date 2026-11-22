from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api import analytics, devices, export, health, snapshot, users, v1
from app.config import settings
from app.requestlog import RequestLog

VERCEL_ORIGIN = "https://flash-expense-tracker.vercel.app"
# The Android app's WebView (Capacitor's default https scheme, host localhost; D-125).
CAPACITOR_ORIGIN = "https://localhost"
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
    """Only the Vercel app, the Android app and local dev servers, whatever CORS_ORIGINS holds."""
    return [
        o for o in origins if o in (VERCEL_ORIGIN, CAPACITOR_ORIGIN) or o.startswith(DEV_PREFIXES)
    ]


def cors_options(origins: list[str]) -> dict:
    """The CORS settings for these CORS_ORIGINS (tests build the same middleware)."""
    return {
        "allow_origins": allowed_origins(origins),
        "allow_methods": METHODS,
        "allow_headers": REQUEST_HEADERS,
        "expose_headers": EXPOSED,
    }


MAX_REQUEST_BYTES = 8 * 1024 * 1024  # the largest phone upload is about 1 MB (D-150)


class BodyLimit:
    """413 for a request that says its body is over MAX_REQUEST_BYTES, before reading it. Pure
    ASGI, inside CORS so the answer carries its headers."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        length = dict(scope.get("headers") or ()).get(b"content-length", b"0")
        if scope["type"] == "http" and (not length.isdigit() or int(length) > MAX_REQUEST_BYTES):
            response = JSONResponse({"detail": "request_too_large"}, status_code=413)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


app = FastAPI(title="Flash Expense Tracker", version=__version__, debug=False)
app.add_middleware(BodyLimit)  # innermost of these: CORS still wraps its 413
app.add_middleware(CORSMiddleware, **cors_options(settings.cors_origin_list))
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(RequestLog, router_app=app)  # outermost: sees CORS answers too
app.include_router(health.router)
app.include_router(v1.router)
app.include_router(snapshot.router)
app.include_router(devices.router)
app.include_router(users.router)
app.include_router(export.router)
app.include_router(analytics.router)
