"""Append-only JSONL store with cross-process file locking.

This is the low-level persistence primitive used by both the main experiences
log (``experiences.jsonl``) and the feedback overlay (``experiences.feedback.jsonl``).
Both are append-only — historical lines are **never** mutated.

CONTRACT §9 / §12 require:
- OS-level advisory file lock around writes
- write-then-fsync semantics (best-effort) to avoid torn lines on crash
- canonical JSONL form (one JSON object per line, no whitespace, trailing LF)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from evol.concurrency import file_lock
from evol.errors import EvolStorageError


class JsonlStore:
    """Append-only JSONL file with advisory file lock around writes.

    The store is **stateless** — every operation hits disk. There is no
    in-memory cache; callers that need one should keep their own.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    # ─── lifecycle ───

    def ensure_initialized(self) -> None:
        """Create parent directory and an empty file if missing.

        Idempotent — existing content is left intact.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def exists(self) -> bool:
        return self.path.is_file()

    # ─── write ───

    def append(self, record: dict[str, Any], *, line: str | None = None) -> None:
        """Append a record (or pre-rendered line) to the store.

        Args:
            record: dict to be JSON-serialized if ``line`` is None.
            line: optional pre-rendered canonical line (used by callers that
                want to enforce a specific field order via canonicalization).
                MUST end with ``\\n`` if provided.
        """
        self.ensure_initialized()
        if line is None:
            payload = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        else:
            if not line.endswith("\n"):
                raise EvolStorageError("JsonlStore.append: pre-rendered line must end with \\n")
            payload = line

        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        try:
            with file_lock(lock_path, exclusive=True, timeout=10.0):
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(payload)
                    f.flush()
                    try:
                        import os  # noqa: PLC0415

                        os.fsync(f.fileno())
                    except OSError:
                        # fsync may not be supported on some FS; tolerable.
                        pass
        except OSError as e:
            raise EvolStorageError(f"append failed for {self.path}: {e}") from e

    # ─── read ───

    def iter_all(self) -> Iterator[dict[str, Any]]:
        """Yield every record in chronological (file) order.

        Skips blank lines and lines that fail to parse, logging a warning for
        the latter — torn lines from a crashed write are recoverable in this way.
        """
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, start=1):
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    yield json.loads(stripped)
                except json.JSONDecodeError:
                    from evol.logging import get_logger  # noqa: PLC0415

                    get_logger("evol.recorder").warning(
                        "skipping malformed jsonl line",
                        extra={"path": str(self.path), "line_no": lineno},
                    )
                    continue

    def find_by_id(self, record_id: str, *, id_field: str = "id") -> dict[str, Any] | None:
        for rec in self.iter_all():
            if rec.get(id_field) == record_id:
                return rec
        return None

    def count(self) -> int:
        if not self.path.is_file():
            return 0
        n = 0
        with self.path.open("r", encoding="utf-8") as f:
            for raw in f:
                if raw.strip():
                    n += 1
        return n


__all__ = ["JsonlStore"]
