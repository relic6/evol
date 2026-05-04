"""Memory checksum helpers — thin wrappers around ``core.canonical``.

These helpers exist so the rest of the memory module can call
``compute_checksum_from_memory(memory_files)`` without going through the
core layer's dict-of-dicts API.
"""

from __future__ import annotations

from typing import Any

from evol.core.canonical import compute_memory_checksum
from evol.core.types import MemoryFile, MemoryKind

_KINDS: tuple[MemoryKind, ...] = ("user_profile", "domain_knowledge", "self_awareness")


def compute_checksum_from_memory(
    memory_files: dict[MemoryKind, MemoryFile],
) -> str:
    """Compute the canonical sha256 over a mapping of in-memory MemoryFiles."""
    raw: dict[str, dict[str, Any]] = {
        k: v.model_dump(exclude_none=False) for k, v in memory_files.items()
    }
    return compute_memory_checksum(raw)


def compute_checksum_from_files(
    memory_dicts: dict[str, dict[str, object]],
) -> str:
    """Direct passthrough for callers that already have plain dicts."""
    return compute_memory_checksum(memory_dicts)


__all__ = [
    "_KINDS",
    "compute_checksum_from_files",
    "compute_checksum_from_memory",
]
