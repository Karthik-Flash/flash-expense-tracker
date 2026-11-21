"""CORS allows exactly what the app sends (D-104). The app and the API are on different
origins (Vercel and Render), so every write is preceded by a preflight; a header missing
here makes the browser drop the write before it is sent (the 4F-B bug). The list of what the
app sends is read from frontend/src/api/headers.ts."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import main

HEADERS_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "headers.ts"
ALLOWED = "http://localhost:5173"  # the default CORS_ORIGINS in tests


def client_lists() -> tuple[set[str], set[str], set[str]]:
    text = HEADERS_TS.read_text(encoding="utf-8")
    block = text.split("export const HEADER = {", 1)[1].split("}", 1)[0]
    headers = set(re.findall(r":\s*'([^']+)'", block))
    methods = set(
        re.findall(r"'([A-Z]+)'", text.split("export const METHODS", 1)[1].split("\n")[0])
    )
    exposed = set(re.findall(r"'([^']+)'", text.split("export const EXPOSED", 1)[1].split("\n")[0]))
    return headers, methods, exposed


def test_the_api_allows_exactly_the_client_lists() -> None:
    headers, methods, exposed = client_lists()
    assert {"Idempotency-Key", "X-Defer-Recompute", "Authorization"} <= headers
    assert set(main.REQUEST_HEADERS) == headers
    assert set(main.METHODS) == methods and set(main.EXPOSED) == exposed


def preflight(client: TestClient, origin: str, method: str, headers: set[str]):
    return client.options(
        "/api/v1/senders/s_any",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": ", ".join(sorted(headers)),
        },
    )


def test_a_preflight_for_every_write_is_allowed_from_the_app_origin() -> None:
    headers, methods, _ = client_lists()
    with TestClient(main.app) as client:
        for method in methods:
            answer = preflight(client, ALLOWED, method, headers)
            assert answer.status_code == 200, (method, answer.text)
            assert answer.headers["access-control-allow-origin"] == ALLOWED
            allowed = {
                h.strip().lower() for h in answer.headers["access-control-allow-headers"].split(",")
            }
            assert {h.lower() for h in headers} <= allowed
            assert method in answer.headers["access-control-allow-methods"]


def test_another_origin_or_an_unknown_header_is_refused() -> None:
    headers, _, _ = client_lists()
    with TestClient(main.app) as client:
        other = preflight(client, "https://evil.example", "PUT", headers)
        assert other.status_code == 400 and "access-control-allow-origin" not in other.headers
        extra = preflight(client, ALLOWED, "PUT", headers | {"X-Not-Ours"})
        assert extra.status_code == 400
        assert main.allowed_origins(["*", "https://evil.example"]) == []


def test_the_android_app_origin_when_listed_in_cors_origins() -> None:
    """5A (D-125): the Capacitor WebView is https://localhost. It is allowed only when
    CORS_ORIGINS lists it, exactly (no port), with the same headers as the Vercel app."""
    from fastapi.middleware.cors import CORSMiddleware

    android = main.CAPACITOR_ORIGIN
    assert android == "https://localhost"
    assert main.allowed_origins([android, "https://localhost:8443", "https://localhost.evil"]) == [
        android
    ]
    headers, methods, _ = client_lists()
    wrapped = CORSMiddleware(main.app, **main.cors_options([main.VERCEL_ORIGIN, android]))
    with TestClient(wrapped) as client:
        for method in methods:
            answer = preflight(client, android, method, headers)
            assert answer.status_code == 200, (method, answer.text)
            assert answer.headers["access-control-allow-origin"] == android
        assert preflight(client, "https://localhost:8443", "PUT", headers).status_code == 400
        read = client.get("/health", headers={"Origin": android})
        assert read.headers["access-control-allow-origin"] == android
        assert "etag" in read.headers["access-control-expose-headers"].lower()


def test_etag_is_exposed_to_the_app() -> None:
    with TestClient(main.app) as client:
        answer = client.get("/health", headers={"Origin": ALLOWED})
        assert answer.headers["access-control-allow-origin"] == ALLOWED
        assert "etag" in answer.headers["access-control-expose-headers"].lower()


def test_the_request_log_names_templates_never_values(capsys) -> None:
    from app import requestlog

    lines = []
    handler = requestlog.log.handlers[0]
    emit = handler.emit
    handler.emit = lambda record: lines.append(record.getMessage())
    try:
        with TestClient(main.app) as client:
            preflight(client, ALLOWED, "PUT", {"Idempotency-Key"})
            client.get("/api/v1/transactions/987654?month=2026-01")
    finally:
        handler.emit = emit
    assert lines[0].startswith("OPTIONS /api/v1/senders/{sender_id} 200 ")
    assert lines[1].startswith("GET /api/v1/transactions/{txn_id} ")
    assert all(
        "987654" not in line and "2026-01" not in line and "s_any" not in line for line in lines
    )
