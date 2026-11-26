"""The API alone on its own port for the cross-origin check (D-104). FAKE data only.

    python -m tests.cross_origin_server <port> <frontend origin>     (from backend\\)

A throwaway SQLite file with the fake fixture messages, CORS_ORIGINS set to the frontend's
origin, and a test signing key in place of Supabase (no network). The first stdout line is
JSON with a test token for user "user-a"; then one "request ..." line per request
(app/requestlog.py). frontend/scripts/cross-origin-check.mjs starts and reads it.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

port, origin = int(sys.argv[1]), sys.argv[2]
folder = Path(tempfile.mkdtemp(prefix="flash-xo-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(folder / 'xo.db').as_posix()}"
os.environ["CORS_ORIGINS"] = origin
os.environ["SUPABASE_URL"] = "https://test.supabase.co"  # the test tokens' issuer; never fetched

import uvicorn  # noqa: E402

from app import cli  # noqa: E402
from app.api import auth  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, engine  # noqa: E402
from tests.apiclient import KEY, jwk, token  # noqa: E402
from tests.smsdata import bulk_rows, full_rows, write_backup  # noqa: E402

settings.auth_users = f"user-a:{settings.owner_id}"
auth.fetch_jwks = lambda url: {"keys": [jwk(KEY, "k1")]}
Base.metadata.create_all(engine)
with open(os.devnull, "w") as quiet:
    stdout, sys.stdout = sys.stdout, quiet
    try:
        # FLASH_XO_BULK=<n>: n more FAKE payments, for the speed check (perf-check.mjs).
        rows = full_rows() + bulk_rows(int(os.environ.get("FLASH_XO_BULK", "0")))
        cli.main(["import-sms", "--input", str(write_backup(folder / "a.xml", rows))])
    finally:
        sys.stdout = stdout
print(
    json.dumps({"token": token("user-a", exp=int(time.time()) + 3600), "user": "user-a"}),
    flush=True,
)

from app.main import app  # noqa: E402  (after CORS_ORIGINS is set)

uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
