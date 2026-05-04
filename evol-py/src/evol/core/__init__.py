"""Core data types and protocol-level utilities.

This module is **language-agnostic**: every field, format, and computation here
must produce results that any conforming SDK (evol-ts, evol-java, ...) would
also produce.
"""

from evol.core.canonical import (
    canonical_jsonl_dump,
    canonical_yaml_dump,
    compute_memory_checksum,
)
from evol.core.ids import gen_experience_id, gen_insight_id, gen_reflection_id
from evol.core.time_utils import (
    is_after,
    parse_iso,
    utc_now,
    utc_now_iso,
)
from evol.core.types import (
    Anchor,
    AnchorKind,
    DeferredState,
    Experience,
    ExperienceStatus,
    Insight,
    InsightOp,
    InsightScope,
    InsightStatus,
    Manifest,
    MemoryEntry,
    MemoryEntryStatus,
    MemoryFile,
    MemoryKind,
    ProposedChange,
    Rejection,
    Signal,
    SignalType,
)

__all__ = [
    "Anchor",
    "AnchorKind",
    "DeferredState",
    "Experience",
    "ExperienceStatus",
    "Insight",
    "InsightOp",
    "InsightScope",
    "InsightStatus",
    "Manifest",
    "MemoryEntry",
    "MemoryEntryStatus",
    "MemoryFile",
    "MemoryKind",
    "ProposedChange",
    "Rejection",
    "Signal",
    "SignalType",
    "canonical_jsonl_dump",
    "canonical_yaml_dump",
    "compute_memory_checksum",
    "gen_experience_id",
    "gen_insight_id",
    "gen_reflection_id",
    "is_after",
    "parse_iso",
    "utc_now",
    "utc_now_iso",
]
