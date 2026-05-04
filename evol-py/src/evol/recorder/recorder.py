"""Recorder: the product-facing API for capturing Experiences.

The 5 product-facing APIs from CONTRACT §7 split as:
  - Recorder owns: ``start_task``, ``end_task``, ``feedback``
  - Advisor owns:  ``enhance``, ``inspire``  (Phase 4)

Two on-disk files back this module:
  - ``experiences.jsonl``           — main append-only log
  - ``experiences.feedback.jsonl``  — overlay with per-experience updates
                                      (signals, status overrides for orphaned)

Reads merge the overlay into the main log to produce the "current view" of
each Experience, while preserving the immutability of the main log itself.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from evol.core.canonical import canonical_jsonl_dump
from evol.core.ids import gen_experience_id
from evol.core.time_utils import utc_now_iso
from evol.core.types import Experience, Signal
from evol.errors import EvolError
from evol.logging import get_logger
from evol.recorder.jsonl_store import JsonlStore

_log = get_logger("evol.recorder")

_OVERLAY_TYPE_SIGNAL = "signal"
_OVERLAY_TYPE_ORPHAN = "orphan_mark"


class TaskHandle(BaseModel):
    """Opaque handle returned by ``start_task`` and consumed by ``end_task``.

    Carries just enough state for ``end_task`` to locate the originating
    Experience and append a properly-formed ``closed`` line to the log
    (the ``open`` line is already on disk).
    """

    experience_id: str
    task_kind: str
    started_at: str
    input: Any


class Recorder:
    """Records Experiences to disk. **Never raises in start/end/feedback.**

    Per CONTRACT §14, recorder methods MUST not throw to product code; on
    failure they log a warning and continue. This is what makes EVOL a
    "decorative" layer — products don't get destabilized by it.
    """

    EXPERIENCES_FILENAME = "experiences.jsonl"
    OVERLAY_FILENAME = "experiences.feedback.jsonl"

    def __init__(self, evol_root: str | Path) -> None:
        self.evol_root = Path(evol_root)
        self.main = JsonlStore(self.evol_root / self.EXPERIENCES_FILENAME)
        self.overlay = JsonlStore(self.evol_root / self.OVERLAY_FILENAME)

    # ─── lifecycle ───

    def ensure_initialized(self) -> None:
        self.main.ensure_initialized()
        self.overlay.ensure_initialized()

    def detect_orphans(self) -> list[str]:
        """Scan main log for ``status: open`` Experiences with no matching
        ``end_task`` line later in the same file. Append an ``orphan_mark``
        overlay record for each. Returns the list of orphaned experience IDs.

        This is intended to be called once at SDK startup (CONTRACT §11
        crash recovery).
        """
        end_seen: set[str] = set()
        opens: list[tuple[int, str]] = []  # (lineno, exp_id)

        for lineno, rec in enumerate(self.main.iter_all(), start=1):
            status = rec.get("status")
            exp_id = rec.get("id")
            if not exp_id:
                continue
            if status == "open":
                opens.append((lineno, exp_id))
            elif status in {"closed", "redacted"}:
                end_seen.add(exp_id)

        # Existing overlay marks shouldn't be reapplied
        existing_orphans = {
            r["experience_id"]
            for r in self.overlay.iter_all()
            if r.get("type") == _OVERLAY_TYPE_ORPHAN
        }

        orphaned: list[str] = []
        for _, exp_id in opens:
            if exp_id in end_seen or exp_id in existing_orphans:
                continue
            self.overlay.append(
                {
                    "type": _OVERLAY_TYPE_ORPHAN,
                    "experience_id": exp_id,
                    "ts": utc_now_iso(),
                }
            )
            orphaned.append(exp_id)
            _log.warning(
                "marked orphaned experience",
                extra={"experience_id": exp_id},
            )
        return orphaned

    # ─── start / end ───

    def start_task(
        self,
        input: Any,
        *,
        task_kind: str = "default",
        ctx: dict[str, Any] | None = None,
    ) -> TaskHandle:
        """Open a new Experience. Synchronous, < 50 ms target."""
        exp_id = gen_experience_id()
        started_at = utc_now_iso()
        metadata: dict[str, Any] = {}
        if ctx:
            metadata.update({k: v for k, v in ctx.items() if k != "task_kind"})

        record = {
            "id": exp_id,
            "task_kind": task_kind,
            "status": "open",
            "started_at": started_at,
            "ended_at": None,
            "input": input,
            "output": None,
            "signals": [],
            "advice_used": [],
            "anchors_applied": [],
            "metadata": metadata,
            "redacted": False,
        }
        try:
            self.main.append(record, line=canonical_jsonl_dump(record))
        except EvolError as e:
            _log.warning("start_task append failed", extra={"err": str(e)})
        return TaskHandle(
            experience_id=exp_id,
            task_kind=task_kind,
            started_at=started_at,
            input=input,
        )

    def end_task(
        self,
        handle: TaskHandle,
        output: Any,
        *,
        advice_used: list[str] | None = None,
        anchors_applied: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Close the Experience by appending a ``closed`` record.

        Returns the experience_id. Note that the ``open`` line is preserved
        in the main log; the closed line carries the same id and overrides
        the view at read time. This keeps the file strictly append-only.
        """
        ended_at = utc_now_iso()
        record = {
            "id": handle.experience_id,
            "task_kind": handle.task_kind,
            "status": "closed",
            "started_at": handle.started_at,
            "ended_at": ended_at,
            "input": handle.input,
            "output": output,
            "signals": [],
            "advice_used": list(advice_used or []),
            "anchors_applied": list(anchors_applied or []),
            "metadata": dict(metadata or {}),
            "redacted": False,
        }
        try:
            self.main.append(record, line=canonical_jsonl_dump(record))
        except EvolError as e:
            _log.warning(
                "end_task append failed",
                extra={"experience_id": handle.experience_id, "err": str(e)},
            )
        return handle.experience_id

    # ─── feedback (overlay) ───

    def feedback(self, experience_id: str, signal: Signal | dict[str, Any]) -> None:
        """Attach a Signal to a previously-recorded Experience.

        Implementation: appends a ``signal`` record to the feedback overlay.
        The main log remains untouched.
        """
        if isinstance(signal, dict):
            signal = Signal.model_validate(signal)
        record = {
            "type": _OVERLAY_TYPE_SIGNAL,
            "experience_id": experience_id,
            "signal": signal.model_dump(exclude_none=False),
            "ts": utc_now_iso(),
        }
        try:
            self.overlay.append(record)
        except EvolError as e:
            _log.warning(
                "feedback append failed",
                extra={"experience_id": experience_id, "err": str(e)},
            )

    # ─── reads (merged view) ───

    def iter_experiences(self) -> Iterator[Experience]:
        """Yield Experiences in chronological order with overlays merged.

        Merge rules:
          - Multiple records with the same id: the **last** one in main log
            wins for the base fields (so closed > open).
          - Overlay ``signal`` records append to ``signals``.
          - Overlay ``orphan_mark`` records override ``status`` to ``orphaned``
            iff status is still ``open``.
        """
        base: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for rec in self.main.iter_all():
            exp_id = rec.get("id")
            if not exp_id:
                continue
            if exp_id not in base:
                order.append(exp_id)
            base[exp_id] = rec  # last write wins

        # Apply overlay
        for ovl in self.overlay.iter_all():
            exp_id = ovl.get("experience_id")
            if not exp_id or exp_id not in base:
                continue
            otype = ovl.get("type")
            if otype == _OVERLAY_TYPE_SIGNAL:
                signals = base[exp_id].setdefault("signals", [])
                signals.append(ovl["signal"])
            elif otype == _OVERLAY_TYPE_ORPHAN:
                if base[exp_id].get("status") == "open":
                    base[exp_id]["status"] = "orphaned"

        for exp_id in order:
            try:
                yield Experience.model_validate(base[exp_id])
            except Exception as e:  # noqa: BLE001
                _log.warning(
                    "skipping invalid merged experience",
                    extra={"experience_id": exp_id, "err": str(e)},
                )
                continue

    def find(self, experience_id: str) -> Experience | None:
        for exp in self.iter_experiences():
            if exp.id == experience_id:
                return exp
        return None

    def count(self) -> int:
        return sum(1 for _ in self.iter_experiences())


__all__ = ["Recorder", "TaskHandle"]
