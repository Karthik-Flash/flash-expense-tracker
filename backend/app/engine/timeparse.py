"""Dates and times from bank SMS -> UTC.

Banks write local Indian time. IST is a fixed UTC+05:30 offset (no DST), so a
constant offset is used instead of zoneinfo (Windows has no tz data without an
extra package).
"""

import re
from datetime import UTC, date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")
MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}

# 2026-01-08:10:00:00 (date and time joined by a colon)
DATETIME_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2}):(\d{2}):(\d{2}):(\d{2})")
# 31-03-26, 09/04/26, 03/04/2026 (day first)
NUMERIC_DATE_RE = re.compile(r"(\d{2})([-/])(\d{2})\2(\d{2}|\d{4})")
# 19-OCT-2026, 18-JAN-26, 12-Nov-26
MONTH_DATE_RE = re.compile(r"(\d{2})-([A-Za-z]{3})-(\d{2}|\d{4})")


def _year(text: str) -> int:
    return 2000 + int(text) if len(text) == 2 else int(text)


def parse_date(text: str) -> date:
    """Day-first date in any catalogued format. Raises ValueError if invalid."""
    if m := NUMERIC_DATE_RE.fullmatch(text):
        return date(_year(m[4]), int(m[3]), int(m[1]))
    if m := MONTH_DATE_RE.fullmatch(text):
        month = MONTHS.get(m[2].upper())
        if month is None:
            raise ValueError(f"unknown month: {text!r}")
        return date(_year(m[3]), month, int(m[1]))
    raise ValueError(f"unknown date format: {text!r}")


def parse_ist_datetime(text: str) -> datetime:
    """'2026-01-08:10:00:00' (IST) -> aware UTC datetime. Raises ValueError if invalid."""
    m = DATETIME_RE.fullmatch(text)
    if not m:
        raise ValueError(f"unknown date-time format: {text!r}")
    local = datetime(*(int(g) for g in m.groups()), tzinfo=IST)
    return local.astimezone(UTC)


def as_utc(received_at: datetime) -> datetime:
    """received_at must be timezone-aware; it is returned in UTC."""
    if received_at.tzinfo is None:
        raise ValueError("received_at must be timezone-aware")
    return received_at.astimezone(UTC)


def txn_time(datetime_text: str | None, received_at: datetime) -> tuple[datetime, bool]:
    """(txn_time_utc, time_inferred). Without a time in the message, received_at is used."""
    if datetime_text is not None:
        return parse_ist_datetime(datetime_text), False
    return as_utc(received_at), True
