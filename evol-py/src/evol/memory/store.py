"""``memory/`` directory read / write / query.

CONTRACT §9 mandates atomic write-then-rename for memory mutations and
canonical YAML serialization for cross-SDK consistency. CONTRACT §10.3
specifies the file-level schema.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from evol.concurrency import atomic_write_text
from evol.core.canonical import canonical_yaml_dump
from evol.core.time_utils import utc_now_iso
from evol.core.types import MemoryEntry, MemoryFile, MemoryKind
from evol.errors import EvolStorageError
from evol.memory.checksum import _KINDS

_KIND_FILENAMES: dict[MemoryKind, str] = {
    "user_profile": "user_profile.yaml",
    "domain_knowledge": "domain_knowledge.yaml",
    "self_awareness": "self_awareness.yaml",
}


class MemoryStore:
    """Reads / writes ``.evol/memory/<kind>.yaml`` files.

    The store is **stateless** — every call hits the disk. Higher-level
    callers (``Consolidator``, ``Advisor``) hold their own caches if needed.
    """

    def __init__(self, memory_dir: str | Path) -> None:
        self.memory_dir = Path(memory_dir)

    # ─── lifecycle ───

    def ensure_initialized(self) -> None:
        """Create the memory dir and three empty ``MemoryFile``s if missing.

        Idempotent — existing files are left untouched.
        """
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        for kind in _KINDS:
            path = self._path(kind)
            if not path.is_file():
                empty = MemoryFile(
                    memory_kind=kind,
                    version=0,
                    last_updated=utc_now_iso(),
                    entries=[],
                )
                self.save(kind, empty)

    # ─── read ───

    def load(self, kind: MemoryKind) -> MemoryFile:
        path = self._path(kind)
        if not path.is_file():
            raise EvolStorageError(f"memory file missing: {path}")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise EvolStorageError(f"memory yaml invalid {path}: {e}") from e
        if not isinstance(raw, dict):
            raise EvolStorageError(f"memory file must be a mapping: {path}")
        try:
            return MemoryFile.model_validate(raw)
        except ValidationError as e:
            raise EvolStorageError(f"memory file schema invalid {path}: {e}") from e

    def load_all(self) -> dict[MemoryKind, MemoryFile]:
        return {k: self.load(k) for k in _KINDS}

    def query(self, kind: MemoryKind, key: str) -> MemoryEntry | None:
        memfile = self.load(kind)
        for entry in memfile.entries:
            if entry.key == key:
                return entry
        return None

    # ─── write ───

    def save(self, kind: MemoryKind, memfile: MemoryFile) -> None:
        if memfile.memory_kind != kind:
            raise EvolStorageError(
                f"kind mismatch: trying to save '{memfile.memory_kind}' as '{kind}'"
            )
        path = self._path(kind)
        # Drop any in-memory checksum field; checksum is recomputed by
        # higher-level consolidator and stored in manifest.
        payload = memfile.model_dump(exclude_none=False)
        payload.pop("checksum", None)
        text = canonical_yaml_dump(payload)
        atomic_write_text(path, text)

    def save_all(self, files: dict[MemoryKind, MemoryFile]) -> None:
        for kind, mf in files.items():
            self.save(kind, mf)

    # ─── helpers ───

    def _path(self, kind: MemoryKind) -> Path:
        return self.memory_dir / _KIND_FILENAMES[kind]

    def all_paths(self) -> list[Path]:
        return [self._path(k) for k in _KINDS]


__all__ = ["MemoryStore"]
