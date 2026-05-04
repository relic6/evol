"""ISO 8601 / UTC helpers.

DATA-MODEL §11 requires:
- All timestamps are UTC, ISO 8601, with millisecond precision and ``Z`` suffix.
- The canonical string form is what is stored on disk; cross-SDK consumers MUST
  produce the same form for the same instant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

ISO_FORMAT_MS = "%Y-%m-%dT%H:%M:%S.%fZ"
"""Display format used internally; ``%f`` here is microseconds — we truncate to
milliseconds when serializing."""


def utc_now() -> datetime:
    """Return current UTC time as a tz-aware ``datetime``."""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Return current UTC time as an ISO 8601 string with millisecond precision.

    Example: ``"2026-05-03T14:30:00.123Z"``
    """
    return _to_iso(utc_now())


def _to_iso(dt: datetime) -> str:
    """Format a tz-aware datetime as ISO 8601 with milliseconds + ``Z``."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 timestamp string into a tz-aware ``datetime``.

    Tolerates both ``Z`` suffix and explicit ``+00:00`` offsets, and both
    millisecond and microsecond precision.
    """
    s = s.strip()
    # Normalize "Z" to "+00:00" so fromisoformat works on Python 3.10.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_after(a: str, b: str) -> bool:
    """Return True iff timestamp ``a`` is strictly after ``b``."""
    return parse_iso(a) > parse_iso(b)


def add_hours(iso_ts: str, hours: int) -> str:
    """Return a new ISO timestamp ``hours`` hours after the given one."""
    dt = parse_iso(iso_ts) + timedelta(hours=hours)
    return _to_iso(dt)


__all__ = [
    "ISO_FORMAT_MS",
    "add_hours",
    "is_after",
    "parse_iso",
    "utc_now",
    "utc_now_iso",
]
