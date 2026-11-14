"""Import an SMS Backup & Restore XML file (or a folder of them).

Streams with iterparse and clears finished elements, so memory stays flat.
Stores only senders in the engine's bank registry (with or without a parser
yet, so a new parser needs only a reparse). OTP, promotional and MMS
messages are never stored. Commits every `commit_every` messages; a re-run
after a crash skips what was committed and finishes the rest.
"""

import hashlib
import re
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app import __version__
from app.engine.filters import is_otp, is_promotional
from app.engine.senders import bank_for, parse_sender
from app.models import ImportBatch
from app.pipeline.dedupe import EPOCH
from app.pipeline.store import Counts, ingest, parser_versions

SOURCE = "sms_backup"
CHARREF_RE = re.compile(rb"&#(?:x([0-9a-fA-F]{1,6})|(\d{1,7}));")


def _fix_charref(m: re.Match) -> bytes:
    cp = int(m[1], 16) if m[1] else int(m[2])
    valid = (
        cp in (0x9, 0xA, 0xD)
        or 0x20 <= cp <= 0xD7FF
        or 0xE000 <= cp <= 0xFFFD
        or 0x10000 <= cp <= 0x10FFFF
    )
    return m[0] if valid else b"&#65533;"


class CharRefCleaner:
    """File wrapper that rewrites XML-invalid character references while streaming.

    SMS Backup & Restore writes emoji as UTF-16 surrogate pairs (&#55357;&#56832;),
    which XML parsers reject; they become U+FFFD. Same as scripts/redact_sms.py.
    """

    def __init__(self, f) -> None:
        self.f, self.tail = f, b""

    def read(self, n: int = 1 << 16) -> bytes:
        while True:
            chunk = self.f.read(n if n and n > 0 else 1 << 16)
            data = self.tail + chunk
            if not chunk:
                self.tail = b""
                return CHARREF_RE.sub(_fix_charref, data)
            cut = data.find(b"&", max(0, len(data) - 10))  # a reference split across chunks
            cut = len(data) if cut == -1 else cut
            data, self.tail = data[:cut], data[cut:]
            if data:
                return CHARREF_RE.sub(_fix_charref, data)


def input_files(path: Path) -> list[Path]:
    return sorted(path.glob("*.xml")) if path.is_dir() else [path]


def fingerprint(paths: list[Path]) -> str:
    """sha256 over the input bytes (file names are not included)."""
    h = hashlib.sha256()
    for path in paths:
        with path.open("rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
    return h.hexdigest()


def iter_sms(paths: list[Path]) -> Iterator[dict[str, str] | None]:
    """Attributes of each <sms>, or None for each <mms>."""
    for path in paths:
        with path.open("rb") as f:
            context = ET.iterparse(CharRefCleaner(f), events=("start", "end"))
            _, root = next(context)
            for event, elem in context:
                if event == "end" and elem.tag in ("sms", "mms"):
                    yield dict(elem.attrib) if elem.tag == "sms" else None
                    root.clear()


def received_at(date_ms: str) -> datetime:
    """SMS Backup & Restore 'date' (epoch milliseconds) -> exact aware UTC datetime."""
    return (EPOCH + timedelta(milliseconds=int(date_ms))).astimezone(UTC)


def skip_reason(sms: dict[str, str] | None) -> str | None:
    if sms is None:
        return "mms"
    if not sms.get("body") or not sms.get("date", "").isdigit():
        return "invalid"
    core, suffix = parse_sender(sms.get("address", ""))
    if bank_for(core) is None:
        return "unregistered_sender"
    if is_promotional(suffix):
        return "promotional"
    if is_otp(sms["body"]):
        return "otp"
    return None


def import_sms(
    session: Session,
    path: Path,
    owner_id: uuid.UUID,
    *,
    dry_run: bool = False,
    commit_every: int = 500,
    progress: Callable[[int], None] | None = None,
) -> tuple[int, Counts]:
    """Import one file or folder. Returns (batch id, counts). Dry run saves nothing."""
    paths = input_files(path)
    started = time.monotonic()
    batch = ImportBatch(
        owner_id=owner_id,
        source=SOURCE,
        started_at=datetime.now(UTC),
        status="running",
        input_fingerprint=fingerprint(paths),
        app_version=__version__,
        parser_versions=parser_versions(),
        counts={},
    )
    session.add(batch)
    session.flush() if dry_run else session.commit()
    batch_id, counts = batch.id, Counts()
    try:
        for sms in iter_sms(paths):
            counts.read += 1
            if progress and counts.read % 5000 == 0:
                progress(counts.read)
            reason = skip_reason(sms)
            if reason:
                counts.skipped[reason] += 1
                continue
            sender = sms["address"]
            ingest(
                session,
                owner_id,
                batch_id,
                SOURCE,
                sender,
                parse_sender(sender)[0],
                sms["body"],
                received_at(sms["date"]),
                counts,
            )
            if counts.read % commit_every == 0:
                session.flush() if dry_run else session.commit()
    except BaseException:
        session.rollback()
        if not dry_run:
            _finish(session, batch_id, "failed", counts, started)
        raise
    if dry_run:
        session.rollback()
    else:
        _finish(session, batch_id, "done", counts, started)
    return batch_id, counts


def _finish(session: Session, batch_id: int, status: str, counts: Counts, started: float) -> None:
    batch = session.get(ImportBatch, batch_id)
    batch.status, batch.finished_at = status, datetime.now(UTC)
    batch.counts = counts.as_dict() | {"seconds": round(time.monotonic() - started, 1)}
    session.commit()
