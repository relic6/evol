"""Canonical serialization for cross-SDK consistency.

DATA-MODEL §11 specifies the exact form every conforming SDK MUST produce so
that a sha256 over a Memory directory is identical between Python, TypeScript,
and Java implementations. The rules:

1. UTF-8, LF line endings, 2-space indent for YAML.
2. Field order is fixed (not alphabetical).
3. Floats are serialized with **two decimal places** as a string-tagged scalar
   so equivalence holds across language float-formatting differences.
4. Timestamps are already canonical strings (handled by ``time_utils._to_iso``).
5. Memory checksum: serialize the three kinds in a fixed order, join with the
   sentinel ``"\\n---\\n"``, sha256 the resulting bytes.

This module is intentionally conservative — any divergence here breaks
cross-SDK interoperability.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import yaml

# ─── field ordering rules ───

_MEMORY_FILE_FIELD_ORDER: tuple[str, ...] = (
    "schema_version",
    "memory_kind",
    "version",
    "last_updated",
    "checksum",
    "entries",
)
_MEMORY_ENTRY_FIELD_ORDER: tuple[str, ...] = (
    "key",
    "value",
    "confidence",
    "evidence_ids",
    "rationale",
    "created_at",
    "last_validated_at",
    "last_revision_id",
    "revision_count",
    "status",
)
_EXPERIENCE_FIELD_ORDER: tuple[str, ...] = (
    "id",
    "task_kind",
    "status",
    "started_at",
    "ended_at",
    "input",
    "output",
    "signals",
    "advice_used",
    "anchors_applied",
    "metadata",
    "redacted",
)
_MEMORY_KIND_ORDER: tuple[str, ...] = (
    "user_profile",
    "domain_knowledge",
    "self_awareness",
)
_CHECKSUM_SEPARATOR = "\n---\n"
_FLOAT_NDIGITS = 2


# ─── helpers ───


def _reorder(d: dict[str, Any], order: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """Return a new dict whose keys appear in ``order`` first (when present),
    followed by any extra keys in their original insertion order."""
    out: dict[str, Any] = {}
    for k in order:
        if k in d:
            out[k] = d[k]
    for k, v in d.items():
        if k not in out:
            out[k] = v
    return out


def _normalize_floats(obj: Any, ndigits: int = _FLOAT_NDIGITS) -> Any:
    """Recursively round any float to ``ndigits`` decimal places.

    This is applied just before serialization so the on-disk text is bit-stable
    across runtimes that print floats slightly differently (Python, Java, JS).
    """
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _normalize_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_floats(v, ndigits) for v in obj]
    return obj


# ─── public API ───


def canonical_yaml_dump(memory_file_dict: dict[str, Any]) -> str:
    """Serialize a Memory file dict (i.e. a :class:`MemoryFile.model_dump()`)
    to canonical YAML.

    Rules: fixed top-level field order, fixed entry field order, float
    rounding to 2 decimals, UTF-8, no flow style, ``allow_unicode=True``.
    """
    ordered = _reorder(memory_file_dict, _MEMORY_FILE_FIELD_ORDER)
    if isinstance(ordered.get("entries"), list):
        ordered["entries"] = [
            _reorder(entry, _MEMORY_ENTRY_FIELD_ORDER) if isinstance(entry, dict) else entry
            for entry in ordered["entries"]
        ]
    ordered = _normalize_floats(ordered)
    return yaml.safe_dump(
        ordered,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=80,
        indent=2,
    )


def canonical_jsonl_dump(experience_dict: dict[str, Any]) -> str:
    """Serialize one Experience dict to a single JSONL line.

    Rules: fixed field order, UTF-8, no whitespace between separators, trailing
    LF. The trailing newline is **part of** the canonical form so writers can
    simply ``f.write(canonical_jsonl_dump(d))``.
    """
    ordered = _reorder(experience_dict, _EXPERIENCE_FIELD_ORDER)
    ordered = _normalize_floats(ordered)
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":")) + "\n"


def compute_memory_checksum(memory_files: dict[str, dict[str, Any]]) -> str:
    """Compute the canonical checksum over all three Memory files.

    Args:
        memory_files: mapping ``{"user_profile": {...}, "domain_knowledge": {...},
            "self_awareness": {...}}``. Missing kinds are treated as empty
            (``{}``) — the canonical form must be deterministic regardless.

    Returns:
        A string ``"sha256:<hexdigest>"``.
    """
    parts: list[str] = []
    for kind in _MEMORY_KIND_ORDER:
        # Strip any pre-existing checksum field; checksum is computed *over*
        # the rest of the file and stored alongside it.
        body = dict(memory_files.get(kind, {}))
        body.pop("checksum", None)
        parts.append(canonical_yaml_dump(body))
    blob = _CHECKSUM_SEPARATOR.join(parts).encode("utf-8")
    return f"sha256:{hashlib.sha256(blob).hexdigest()}"


__all__ = [
    "canonical_jsonl_dump",
    "canonical_yaml_dump",
    "compute_memory_checksum",
]
