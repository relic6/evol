"""Track inspirations emitted, for cooldown + daily-quota gating.

Persisted to ``.evol/insights/inspiration_history.jsonl`` (append-only).
Each line is a small JSON record:

    {"id": "ins_emit_<ts>_<rand>", "ts": "...", "kind": "...",
     "evidence_ids": [...]}

This file is technically EVOL-internal bookkeeping — not a protocol-level
artifact — but stays human-readable for the same reason everything else does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from evol.concurrency import file_lock
from evol.core.time_utils import parse_iso, utc_now, utc_now_iso
from evol.errors import EvolStorageError
from evol.logging import get_logger

_log = get_logger("evol.advisor.history")


@dataclass
class InspirationRecord:
    id: str
    ts: str
    kind: str
    evidence_ids: list[str]
    text_preview: str | None = None


class InspirationHistory:
    """Append-only inspiration emit log + lightweight read API."""

    FILENAME = "inspiration_history.jsonl"

    def __init__(self, evol_root: str | Path) -> None:
        self.evol_root = Path(evol_root)
        self.path = self.evol_root / "insights" / self.FILENAME

    # ─── lifecycle ───

    def ensure_initialized(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    # ─── write ───

    def record(self, record: InspirationRecord) -> None:
        self.ensure_initialized()
        line = json.dumps(
            {
                "id": record.id,
                "ts": record.ts,
                "kind": record.kind,
                "evidence_ids": list(record.evidence_ids),
                "text_preview": record.text_preview,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ) + "\n"
        try:
            with (
                file_lock(self.path.with_suffix(self.path.suffix + ".lock"), timeout=5.0),
                self.path.open("a", encoding="utf-8") as f,
            ):
                f.write(line)
                f.flush()
        except OSError as e:
            raise EvolStorageError(f"inspiration history append failed: {e}") from e

    # ─── read ───

    def iter_all(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        out: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    out.append(json.loads(stripped))
                except json.JSONDecodeError:
                    _log.warning("skipping malformed inspiration history line")
                    continue
        return out

    # ─── queries ───

    def last_emitted_at(self) -> str | None:
        records = self.iter_all()
        return records[-1]["ts"] if records else None

    def count_today(self) -> int:
        today = utc_now_iso().split("T", 1)[0]
        return sum(1 for r in self.iter_all() if r.get("ts", "").startswith(today))

    def in_cooldown(self, *, hours: int) -> bool:
        last = self.last_emitted_at()
        if last is None:
            return False
        try:
            last_dt = parse_iso(last)
        except Exception:
            return False
        return (utc_now() - last_dt) < timedelta(hours=hours)


__all__ = ["InspirationHistory", "InspirationRecord"]
