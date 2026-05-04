"""ID generation helpers for protocol-level entities.

Format conventions (DATA-MODEL §4.3 / §6.3):
- Experience: ``exp_{ISO8601-no-colons}_{shortrand}``
- Reflection: ``ref_{YYYY-MM-DD}_{shortrand}``
- Insight   : ``ins_{YYYY-MM-DD}_{seq:03d}``  (seq within a single reflection)
- Deferred  : ``req_{ISO8601-no-colons}_{shortrand}_{purpose}``

All IDs are URL-safe (alphanumerics + ``_``) so they can be used as filenames.
"""

from __future__ import annotations

import secrets

from evol.core.time_utils import utc_now_iso

_EXP_PREFIX = "exp"
_REF_PREFIX = "ref"
_INS_PREFIX = "ins"
_REQ_PREFIX = "req"


def _filesystem_safe_ts(ts: str) -> str:
    """Convert an ISO 8601 timestamp into a filesystem-safe form.

    Drops colons and dots, keeps the ``Z`` (without it). Example:
    ``"2026-05-03T14:30:00.123Z"`` → ``"20260503T143000123"``.
    """
    return (
        ts.replace("-", "")
        .replace(":", "")
        .replace(".", "")
        .rstrip("Z")
    )


def _short_rand(nbytes: int = 2) -> str:
    """Hex random of length ``2 * nbytes`` characters."""
    return secrets.token_hex(nbytes)


def gen_experience_id() -> str:
    """Generate a fresh Experience ID."""
    return f"{_EXP_PREFIX}_{_filesystem_safe_ts(utc_now_iso())}_{_short_rand()}"


def gen_reflection_id() -> str:
    """Generate a fresh Reflection batch ID."""
    date = utc_now_iso().split("T", 1)[0]
    return f"{_REF_PREFIX}_{date}_{_short_rand()}"


def gen_insight_id(reflection_id: str, seq: int) -> str:
    """Generate an Insight ID *bound to a specific reflection batch*.

    The reflection date is extracted from ``reflection_id`` so every Insight
    in the same batch shares the same date prefix. ``seq`` is zero-padded to
    3 digits — supports up to 999 insights per reflection (more is a smell).
    """
    if not reflection_id.startswith(f"{_REF_PREFIX}_"):
        raise ValueError(f"invalid reflection_id: {reflection_id!r}")
    # ref_YYYY-MM-DD_xxxx → YYYY-MM-DD
    date = reflection_id.split("_", 2)[1]
    if seq < 0 or seq > 999:
        raise ValueError(f"insight seq out of range: {seq}")
    return f"{_INS_PREFIX}_{date}_{seq:03d}"


def gen_deferred_request_id(purpose: str) -> str:
    """Generate a deferred LLM request ID.

    Includes ``purpose`` as a suffix so a quick ``ls .evol/pending_requests/``
    reveals what's outstanding without opening every file.
    """
    if not purpose or not purpose.replace("_", "").isalnum():
        raise ValueError(f"invalid purpose: {purpose!r}")
    return f"{_REQ_PREFIX}_{_filesystem_safe_ts(utc_now_iso())}_{_short_rand()}_{purpose}"


__all__ = [
    "gen_deferred_request_id",
    "gen_experience_id",
    "gen_insight_id",
    "gen_reflection_id",
]
