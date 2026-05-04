"""Memory snapshots: create / list / rollback / prune.

CONTRACT §9 + §10.5 require:
- Snapshots are stored in ``versions/memory-v{N}.snapshot``
- They are tar archives of the ``memory/`` directory
- ``manifest.yaml.memory.current_version`` points at the active version
- Rollback switches the pointer; it does **not** delete history
- Snapshots are **append-only** with respect to creation: once written, a
  snapshot file is never modified
"""

from __future__ import annotations

import re
from pathlib import Path

from evol.concurrency import (
    extract_snapshot_tar,
    make_snapshot_tar,
)
from evol.errors import EvolStorageError

_SNAPSHOT_PATTERN = re.compile(r"^memory-v(\d+)\.snapshot$")


def snapshot_filename(version: int) -> str:
    if version < 0:
        raise EvolStorageError(f"snapshot version must be ≥ 0, got {version}")
    return f"memory-v{version}.snapshot"


class SnapshotManager:
    """Manages the ``versions/`` directory under ``.evol/``."""

    def __init__(self, evol_root: str | Path) -> None:
        self.evol_root = Path(evol_root)
        self.versions_dir = self.evol_root / "versions"
        self.memory_dir = self.evol_root / "memory"

    # ─── lifecycle ───

    def ensure_initialized(self) -> None:
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    # ─── create ───

    def create(self, version: int) -> Path:
        """Snapshot the current ``memory/`` directory as ``memory-v{N}.snapshot``.

        Refuses to overwrite existing snapshots — version files are immutable
        once written. To replace a snapshot, prune-and-recreate explicitly.
        """
        self.ensure_initialized()
        if not self.memory_dir.is_dir():
            raise EvolStorageError(
                f"cannot snapshot: memory dir missing: {self.memory_dir}"
            )
        target = self.versions_dir / snapshot_filename(version)
        if target.exists():
            raise EvolStorageError(
                f"snapshot already exists: {target}; "
                "snapshots are immutable, use a higher version"
            )
        return make_snapshot_tar(self.memory_dir, target)

    # ─── list ───

    def list_versions(self) -> list[int]:
        """Return all available snapshot versions in ascending order."""
        if not self.versions_dir.is_dir():
            return []
        versions: list[int] = []
        for entry in self.versions_dir.iterdir():
            m = _SNAPSHOT_PATTERN.match(entry.name)
            if m:
                versions.append(int(m.group(1)))
        return sorted(versions)

    def latest_version(self) -> int | None:
        versions = self.list_versions()
        return versions[-1] if versions else None

    def has_version(self, version: int) -> bool:
        return (self.versions_dir / snapshot_filename(version)).is_file()

    # ─── rollback ───

    def rollback_to(self, version: int) -> Path:
        """Restore ``memory/`` from snapshot ``version``.

        Pre-existing files in ``memory/`` are removed first. The original
        snapshot file is left untouched; rollback is just a pointer change
        plus an extraction.
        """
        target = self.versions_dir / snapshot_filename(version)
        if not target.is_file():
            raise EvolStorageError(f"snapshot not found: {target}")

        # Clear current memory dir contents (but keep the dir itself).
        if self.memory_dir.is_dir():
            for child in self.memory_dir.iterdir():
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    _rmtree(child)
        else:
            self.memory_dir.mkdir(parents=True, exist_ok=True)

        extract_snapshot_tar(target, self.memory_dir)
        return self.memory_dir

    # ─── prune ───

    def prune(self, *, keep: int) -> list[int]:
        """Delete oldest snapshots, keeping at most ``keep`` versions.

        Returns the list of versions removed (sorted).
        """
        if keep < 1:
            raise EvolStorageError(f"prune keep must be ≥ 1, got {keep}")
        versions = self.list_versions()
        if len(versions) <= keep:
            return []
        to_remove = versions[: len(versions) - keep]
        removed: list[int] = []
        for v in to_remove:
            p = self.versions_dir / snapshot_filename(v)
            try:
                p.unlink()
                removed.append(v)
            except OSError as e:
                raise EvolStorageError(f"failed to prune {p}: {e}") from e
        return removed


def _rmtree(path: Path) -> None:
    """Recursively delete a directory (cross-platform).

    Used during rollback to clean ``memory/`` before extraction. Uses
    ``shutil.rmtree`` rather than walking ourselves to handle symlinks
    correctly across platforms.
    """
    import shutil  # noqa: PLC0415

    shutil.rmtree(path)


__all__ = ["SnapshotManager", "snapshot_filename"]
