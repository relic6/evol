"""Unit tests for evol.core.time_utils."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from evol.core.time_utils import add_hours, is_after, parse_iso, utc_now_iso

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def test_utc_now_iso_format() -> None:
    s = utc_now_iso()
    assert _ISO_RE.match(s), s


def test_parse_round_trip_z() -> None:
    s = "2026-05-03T14:30:00.123Z"
    dt = parse_iso(s)
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timezone.utc.utcoffset(None)


def test_parse_accepts_explicit_offset() -> None:
    dt = parse_iso("2026-05-03T14:30:00+00:00")
    assert dt == datetime(2026, 5, 3, 14, 30, tzinfo=timezone.utc)


def test_is_after_basic() -> None:
    earlier = "2026-05-03T14:30:00.000Z"
    later = "2026-05-03T14:30:00.500Z"
    assert is_after(later, earlier)
    assert not is_after(earlier, later)
    assert not is_after(earlier, earlier)  # strict


def test_add_hours_positive() -> None:
    assert add_hours("2026-05-03T14:00:00.000Z", 24).startswith("2026-05-04T14:00:00")


@pytest.mark.parametrize(
    "ts",
    [
        "2026-05-03T14:30:00.123Z",
        "2026-05-03T14:30:00.000+00:00",
        "2026-05-03T14:30:00Z",
    ],
)
def test_parse_various_forms(ts: str) -> None:
    parse_iso(ts)
