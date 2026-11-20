"""One log line per request (D-104): method (OPTIONS too), route template, status, duration.

Never a body, a query value, an id from the path, a header or a token: the route template
("/api/v1/transactions/{txn_id}/category") is all that names the request. A CORS preflight
is answered by the CORS middleware before routing, so its template is found by matching the
path against the app's routes the same way the router does.
"""

import logging
import re
import sys
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("flash.requests")
if not log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("request %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


_templates: list[tuple[re.Pattern[str], str]] = []


def template(app, scope: Scope) -> str:
    """The route template of a request, or "unmatched"; never the raw path. Templates come
    from the app's OpenAPI paths, so a preflight (answered before routing) gets one too."""
    if not _templates and app is not None:
        for path in app.openapi()["paths"]:
            pattern = re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path))
            _templates.append((re.compile(pattern), path))
    path = scope.get("path", "")
    return next((t for rx, t in _templates if rx.fullmatch(path)), "unmatched")


class RequestLog:
    """Pure ASGI middleware, outermost, so it sees what the CORS middleware answers."""

    def __init__(self, app: ASGIApp, router_app=None) -> None:
        self.app = app
        self.router_app = router_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            ms = (time.perf_counter() - started) * 1000
            log.info(
                "%s %s %d %.0fms", scope["method"], template(self.router_app, scope), status, ms
            )
