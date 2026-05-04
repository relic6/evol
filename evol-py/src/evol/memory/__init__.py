"""Memory store, manifest, and snapshot management."""

from evol.memory.checksum import compute_checksum_from_files, compute_checksum_from_memory
from evol.memory.consolidator import (
    ConsolidationResult,
    Consolidator,
    confidence_cap_for_evidence_count,
)
from evol.memory.manifest import ManifestStore, build_initial_manifest
from evol.memory.snapshot import SnapshotManager
from evol.memory.store import MemoryStore

__all__ = [
    "ConsolidationResult",
    "Consolidator",
    "ManifestStore",
    "MemoryStore",
    "SnapshotManager",
    "build_initial_manifest",
    "compute_checksum_from_files",
    "compute_checksum_from_memory",
    "confidence_cap_for_evidence_count",
]
