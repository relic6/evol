"""Reflector — main orchestration of the reflection state machine.

Implements FLOWS §3.10. Two entrypoints:

  - :meth:`Reflector.reflect`         — run a fresh reflection cycle
  - :meth:`Reflector.resume_pending`  — resume host-deferred reflections that
                                        the host agent has now answered

Both produce :class:`ReflectionResult` objects which double as both
return values and the metadata written into ``insights/<date>-reflection.md``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from evol._version import PROTOCOL_VERSION
from evol.concurrency import atomic_write_text, file_lock
from evol.config.schema import Config
from evol.core.ids import gen_reflection_id
from evol.core.time_utils import utc_now_iso
from evol.core.types import Anchor, Experience, Insight, Manifest, MemoryFile, MemoryKind
from evol.errors import EvolError, EvolLockError, EvolParseError
from evol.llm.base import (
    DeferredLLMResponse,
    LLMClient,
)
from evol.logging import get_logger
from evol.memory import (
    Consolidator,
    ManifestStore,
    MemoryStore,
    SnapshotManager,
    compute_checksum_from_memory,
)
from evol.recorder import Recorder
from evol.reflector.batcher import Batcher
from evol.reflector.filter import AnchorFilter, HostTextStrategy
from evol.reflector.parser import parse_insights
from evol.reflector.prompt import PromptBuilder
from evol.reflector.trigger import build_trigger

_log = get_logger("evol.reflector")

DEFERRED_FILENAME_SUFFIX = ".state.json"


# ───────────────────────── result type ─────────────────────────


ReflectionStatus = Literal[
    "completed",
    "skipped",
    "preflight_failed",
    "no_op",
    "llm_failed",
    "parse_failed",
    "consolidate_failed",
    "timeout",
    "pending_host",
    "resumed_host",
]


class ReflectionResult(BaseModel):
    """Outcome of a single ``reflect()`` or ``resume_pending()`` invocation."""

    model_config = ConfigDict(extra="allow")

    reflection_id: str
    status: ReflectionStatus
    insights_total: int = 0
    insights_applied: int = 0
    insights_rejected: int = 0
    memory_version_before: int | None = None
    memory_version_after: int | None = None
    deferred_id: str | None = None
    notes: str | None = None
    completed_at: str | None = None


# ───────────────────────── helpers ─────────────────────────


@dataclass
class _DeferredState:
    request_id: str
    purpose: str
    pending_path: str
    expected_response_path: str
    created_at: str
    expires_at: str | None
    reflection_id: str
    status: str = "pending"
    consumed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "purpose": self.purpose,
            "pending_path": self.pending_path,
            "expected_response_path": self.expected_response_path,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "reflection_id": self.reflection_id,
            "status": self.status,
            "consumed_at": self.consumed_at,
        }


# ───────────────────────── Reflector ─────────────────────────


class Reflector:
    """Orchestrate reflection cycles end-to-end.

    Wired with: LLMClient, Recorder, MemoryStore, ManifestStore,
    SnapshotManager, Consolidator, AnchorFilter, PromptBuilder, Batcher.
    """

    LOCK_FILENAME = "locks/reflection.lock"
    DEFERRED_DIRNAME = "deferred"
    INSIGHTS_DIRNAME = "insights"

    def __init__(
        self,
        *,
        config: Config,
        evol_root: str | Path,
        llm: LLMClient,
        anchors: list[Anchor],
        recorder: Recorder,
        memory_store: MemoryStore,
        manifest_store: ManifestStore,
        snapshot_manager: SnapshotManager,
        paused_marker: str | Path | None = None,
        host_text_strategy: HostTextStrategy = "fail_safe",
    ) -> None:
        self.config = config
        self.evol_root = Path(evol_root)
        self.llm = llm
        self.anchors = anchors
        self.recorder = recorder
        self.memory_store = memory_store
        self.manifest_store = manifest_store
        self.snapshot_manager = snapshot_manager
        self.paused_marker = Path(paused_marker) if paused_marker is not None else None

        self.consolidator = Consolidator()
        self.anchor_filter = AnchorFilter(
            anchors=anchors,
            llm=llm,
            host_text_strategy=host_text_strategy,
        )
        self.prompt_builder = PromptBuilder()
        self.batcher = Batcher(
            max_experiences_per_run=config.reflection.max_experiences_per_run
        )
        self.trigger = build_trigger(config.reflection)

        self.deferred_dir = self.evol_root / self.DEFERRED_DIRNAME
        self.insights_dir = self.evol_root / self.INSIGHTS_DIRNAME
        self.deferred_dir.mkdir(parents=True, exist_ok=True)
        self.insights_dir.mkdir(parents=True, exist_ok=True)

    def _is_paused(self) -> bool:
        return self.paused_marker is not None and self.paused_marker.exists()

    # ───────────── public API ─────────────

    def should_fire(self, *, manifest: Manifest | None = None) -> bool:
        if self._is_paused():
            return False
        manifest = manifest or self.manifest_store.read()
        last_at = (manifest.last_reflection or {}).get("performed_at") if manifest.last_reflection else None
        # Count experiences since the last reflection. v0.1: simple total count.
        # For threshold trigger this is approximated by current count - last_count.
        total = self.recorder.count()
        last_count = int(
            manifest.experiences.get("reflected_count", manifest.experiences.get("count", 0))
        ) if manifest.experiences else 0
        new_since = max(0, total - last_count)
        return self.trigger.should_fire(
            new_experiences_since_last=new_since,
            last_reflection_at=last_at,
        )

    def reflect(self) -> ReflectionResult:
        """Run a complete reflection cycle.

        Returns the resulting :class:`ReflectionResult`. Never raises;
        all failure modes surface as a non-completed status field.
        """
        reflection_id = gen_reflection_id()
        if self._is_paused():
            return ReflectionResult(
                reflection_id=reflection_id,
                status="skipped",
                notes="EVOL is paused",
                completed_at=utc_now_iso(),
            )
        try:
            with file_lock(self.evol_root / self.LOCK_FILENAME, timeout=2.0):
                return self._reflect_inside_lock(reflection_id)
        except EvolLockError:
            _log.info("reflection lock busy — skipping", extra={"reflection_id": reflection_id})
            return ReflectionResult(
                reflection_id=reflection_id,
                status="skipped",
                notes="another reflection in progress",
                completed_at=utc_now_iso(),
            )

    def resume_pending(self) -> list[ReflectionResult]:
        """Scan ``.evol/deferred/`` for outstanding deferred requests; for each
        one whose completed response has arrived, run the consolidation tail
        of the reflection flow. Idempotent."""
        results: list[ReflectionResult] = []
        if self._is_paused():
            return results
        if not self.deferred_dir.is_dir():
            return results

        for state_path in sorted(self.deferred_dir.glob(f"*{DEFERRED_FILENAME_SUFFIX}")):
            try:
                state = self._load_deferred(state_path)
            except (EvolError, json.JSONDecodeError) as e:
                _log.warning("malformed deferred state", extra={"path": str(state_path), "err": str(e)})
                continue
            if state.status != "pending":
                continue
            result = self._try_resume_one(state, state_path)
            if result is not None:
                results.append(result)
        return results

    # ───────────── inside-lock implementation ─────────────

    def _reflect_inside_lock(self, reflection_id: str) -> ReflectionResult:
        manifest_before = self.manifest_store.read()
        if not self._preflight(manifest_before):
            return self._finalize(
                reflection_id=reflection_id,
                status="preflight_failed",
                notes="preflight checksum / version mismatch",
                manifest=manifest_before,
            )

        # Build batch
        all_experiences = list(self.recorder.iter_experiences())
        new_experiences = self._slice_since_last(all_experiences, manifest_before)
        batch = self.batcher.select(new_experiences)
        if not batch:
            return self._finalize(
                reflection_id=reflection_id,
                status="no_op",
                notes="no new experiences to reflect on",
                manifest=manifest_before,
            )

        # Build prompt
        memory_files = self.memory_store.load_all()
        messages = self.prompt_builder.build(
            domain=self.config.product.domain,
            anchors=self.anchors,
            memory=memory_files,
            experiences=batch,
        )

        # Call LLM
        try:
            response = self.llm.chat(
                messages,
                purpose="reflection",
                max_tokens=2048,
                temperature=0.4,
                timeout=120.0,
            )
        except EvolError as e:
            _log.warning(
                "reflection LLM call failed",
                extra={"reflection_id": reflection_id, "err": str(e)},
            )
            return self._finalize(
                reflection_id=reflection_id,
                status="llm_failed",
                notes=f"llm call failed: {e}",
                manifest=manifest_before,
            )

        # Async path: persist deferred state and short-circuit.
        if isinstance(response, DeferredLLMResponse):
            self._persist_deferred_state(response, reflection_id)
            self._write_pending_insights_md(
                reflection_id=reflection_id,
                deferred=response,
                experiences=batch,
            )
            return ReflectionResult(
                reflection_id=reflection_id,
                status="pending_host",
                deferred_id=response.request_id,
                notes=(
                    f"deferred to host backend; pending request at "
                    f"{response.pending_path}"
                ),
                completed_at=utc_now_iso(),
            )

        # Sync path: parse → filter → consolidate → snapshot → write.
        return self._consolidate_response(
            reflection_id=reflection_id,
            llm_text=response.text,
            experiences=batch,
            manifest_before=manifest_before,
            kind="reflect",
        )

    # ───────────── consolidation tail (shared by reflect & resume) ─────────────

    def _consolidate_response(
        self,
        *,
        reflection_id: str,
        llm_text: str,
        experiences: list[Experience],
        manifest_before: Manifest,
        kind: Literal["reflect", "resume"],
    ) -> ReflectionResult:
        # Parse with one retry on failure (FLOWS §3.5).
        try:
            insights = parse_insights(llm_text, reflection_id=reflection_id)
        except EvolParseError as e:
            _log.warning(
                "first parse failed — would normally retry; v0.1 marks parse_failed",
                extra={"reflection_id": reflection_id, "err": str(e)},
            )
            return self._finalize(
                reflection_id=reflection_id,
                status="parse_failed",
                notes=str(e),
                manifest=manifest_before,
            )

        # Anchor post-filter
        outcome = self.anchor_filter.filter(insights)
        approved, rejected = outcome.approved, outcome.rejected

        # Consolidate
        memory_before = self.memory_store.load_all()
        try:
            cons = self.consolidator.apply(approved, memory_before)
        except EvolError as e:
            _log.exception(
                "consolidate failed",
                extra={"reflection_id": reflection_id, "err": str(e)},
            )
            return self._finalize(
                reflection_id=reflection_id,
                status="consolidate_failed",
                notes=str(e),
                manifest=manifest_before,
            )

        # Persist memory + snapshot + manifest update
        new_version, new_checksum = self._persist_memory(
            files=cons.files,
            current_version=int(manifest_before.memory.get("current_version", 0)),
        )

        self.manifest_store.update_memory_pointer(
            version=new_version,
            checksum=new_checksum,
        )
        self.manifest_store.update_last_reflection(reflection_id=reflection_id)
        self.manifest_store.update_experiences_pointer(
            count=self.recorder.count(),
            last_id=experiences[-1].id if experiences else None,
        )

        result = ReflectionResult(
            reflection_id=reflection_id,
            status="resumed_host" if kind == "resume" else "completed",
            insights_total=len(insights),
            insights_applied=len(cons.applied),
            insights_rejected=len(rejected),
            memory_version_before=int(manifest_before.memory.get("current_version", 0)),
            memory_version_after=new_version,
            completed_at=utc_now_iso(),
        )
        self._write_insights_md(
            reflection_id=reflection_id,
            result=result,
            applied=cons.applied,
            rejected=rejected,
            superseded=cons.superseded,
        )
        # Refresh anchors snapshot in manifest (post-consolidate is the right
        # moment — anchors are stable across the whole cycle). Re-read first
        # so we don't clobber the last_reflection / experiences pointer
        # updates we just wrote.
        latest = self.manifest_store.read()
        latest.anchors = list(self.anchors)
        self.manifest_store.write(latest)
        return result

    # ───────────── deferred state ─────────────

    def _persist_deferred_state(
        self, deferred: DeferredLLMResponse, reflection_id: str
    ) -> None:
        state = _DeferredState(
            request_id=deferred.request_id,
            purpose=deferred.purpose,
            pending_path=str(deferred.pending_path),
            expected_response_path=str(deferred.expected_response_path),
            created_at=deferred.created_at,
            expires_at=deferred.expires_at,
            reflection_id=reflection_id,
        )
        path = self.deferred_dir / f"{deferred.request_id}{DEFERRED_FILENAME_SUFFIX}"
        atomic_write_text(path, json.dumps(state.to_dict(), ensure_ascii=False, indent=2))

    def _load_deferred(self, path: Path) -> _DeferredState:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _DeferredState(
            request_id=data["request_id"],
            purpose=data["purpose"],
            pending_path=data["pending_path"],
            expected_response_path=data["expected_response_path"],
            created_at=data["created_at"],
            expires_at=data.get("expires_at"),
            reflection_id=data["reflection_id"],
            status=data.get("status", "pending"),
            consumed_at=data.get("consumed_at"),
        )

    def _try_resume_one(
        self, state: _DeferredState, state_path: Path
    ) -> ReflectionResult | None:
        deferred = DeferredLLMResponse(
            request_id=state.request_id,
            backend=self.llm.backend_kind,
            pending_path=Path(state.pending_path),
            expected_response_path=Path(state.expected_response_path),
            created_at=state.created_at,
            expires_at=state.expires_at,
            purpose=state.purpose,  # type: ignore[arg-type]
        )

        try:
            response = self.llm.poll(deferred)
        except EvolParseError as e:
            self._mark_deferred(state, state_path, status="parse_failed")
            _log.warning(
                "deferred response parse failed",
                extra={"request_id": state.request_id, "err": str(e)},
            )
            return None

        if response is None:
            return None  # still waiting

        # Take lock for the consolidation tail (mirrors reflect()).
        try:
            with file_lock(self.evol_root / self.LOCK_FILENAME, timeout=2.0):
                manifest_before = self.manifest_store.read()
                # We don't have the experiences batch; load all and treat the
                # full set as context (deferred resumes are rare; a future
                # version may snapshot the batch alongside the deferred state).
                all_experiences = list(self.recorder.iter_experiences())
                result = self._consolidate_response(
                    reflection_id=state.reflection_id,
                    llm_text=response.text,
                    experiences=all_experiences,
                    manifest_before=manifest_before,
                    kind="resume",
                )
        except EvolLockError:
            _log.info(
                "resume_pending: lock busy — will retry next time",
                extra={"request_id": state.request_id},
            )
            return None

        self._mark_deferred(state, state_path, status="consumed")
        return result

    def _mark_deferred(
        self, state: _DeferredState, state_path: Path, *, status: str
    ) -> None:
        state.status = status
        state.consumed_at = utc_now_iso() if status == "consumed" else state.consumed_at
        atomic_write_text(state_path, json.dumps(state.to_dict(), ensure_ascii=False, indent=2))

    # ───────────── persistence helpers ─────────────

    def _persist_memory(
        self,
        *,
        files: dict[MemoryKind, MemoryFile],
        current_version: int,
    ) -> tuple[int, str]:
        for kind, mf in files.items():
            self.memory_store.save(kind, mf)
        new_version = current_version + 1
        try:
            self.snapshot_manager.create(new_version)
        except EvolError:
            # If snapshot exists already (very rare race), increment further.
            existing = self.snapshot_manager.list_versions()
            new_version = (existing[-1] if existing else current_version) + 1
            self.snapshot_manager.create(new_version)
        # Recompute checksum from disk so it matches what was persisted.
        files_on_disk = self.memory_store.load_all()
        checksum = compute_checksum_from_memory(files_on_disk)
        return new_version, checksum

    def _preflight(self, manifest: Manifest) -> bool:
        if manifest.protocol_version != PROTOCOL_VERSION:
            _log.warning(
                "preflight: protocol version mismatch",
                extra={"on_disk": manifest.protocol_version, "sdk": PROTOCOL_VERSION},
            )
            return False
        files = self.memory_store.load_all()
        actual = compute_checksum_from_memory(files)
        recorded = str(manifest.memory.get("checksum") or "")
        if recorded and actual != recorded:
            _log.warning(
                "preflight: checksum mismatch",
                extra={"actual": actual, "recorded": recorded},
            )
            return False
        return True

    def _slice_since_last(
        self,
        all_exps: list[Experience],
        manifest: Manifest,
    ) -> list[Experience]:
        last_id = (manifest.experiences or {}).get("reflected_last_id") or (
            manifest.experiences or {}
        ).get("last_id")
        if not last_id:
            return all_exps
        # Take everything strictly *after* last_id (if present in list).
        ids = [e.id for e in all_exps]
        if last_id not in ids:
            return all_exps
        idx = ids.index(last_id)
        return all_exps[idx + 1 :]

    # ───────────── insights/*.md writer ─────────────

    def _write_insights_md(
        self,
        *,
        reflection_id: str,
        result: ReflectionResult,
        applied: list[Insight],
        rejected: list[Insight],
        superseded: list[Insight],
    ) -> Path:
        date = result.completed_at.split("T", 1)[0] if result.completed_at else utc_now_iso().split("T", 1)[0]
        path = self.insights_dir / f"{date}-{reflection_id}.md"
        front = {
            "reflection_id": reflection_id,
            "status": result.status,
            "performed_at": result.completed_at,
            "memory_versions": {
                "before": result.memory_version_before,
                "after": result.memory_version_after,
            },
            "counts": {
                "total": result.insights_total,
                "applied": result.insights_applied,
                "rejected": result.insights_rejected,
            },
        }
        body_parts: list[str] = ["---", yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip(), "---", ""]
        body_parts.append(f"# Reflection {reflection_id}\n")
        body_parts.append("## Applied insights\n")
        body_parts += [self._insight_md(i) for i in applied] or ["(none)"]
        body_parts.append("\n## Rejected insights\n")
        body_parts += [self._rejected_md(i) for i in rejected] or ["(none)"]
        if superseded:
            body_parts.append("\n## Superseded insights\n")
            body_parts += [self._insight_md(i) for i in superseded]
        atomic_write_text(path, "\n".join(body_parts) + "\n")
        return path

    def _write_pending_insights_md(
        self,
        *,
        reflection_id: str,
        deferred: DeferredLLMResponse,
        experiences: list[Experience],
    ) -> Path:
        date = utc_now_iso().split("T", 1)[0]
        path = self.insights_dir / f"{date}-{reflection_id}-pending.md"
        front = {
            "reflection_id": reflection_id,
            "status": "pending_host",
            "performed_at": utc_now_iso(),
            "deferred_id": deferred.request_id,
            "deferred_pending_path": str(deferred.pending_path),
            "deferred_response_path": str(deferred.expected_response_path),
            "expires_at": deferred.expires_at,
            "experiences_in_batch": len(experiences),
        }
        body = (
            "---\n"
            + yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
            + "\n---\n\n"
            f"# Reflection {reflection_id} (pending host completion)\n\n"
            f"This reflection was deferred to the host agent. The pending request "
            f"is at:\n\n  `{deferred.pending_path}`\n\n"
            f"Once the host writes a JSON response to "
            f"`{deferred.expected_response_path}`, run `evol reflect` (or call "
            f"`evol.reflector.resume_pending()`) to consolidate the result.\n"
        )
        atomic_write_text(path, body)
        return path

    @staticmethod
    def _insight_md(ins: Insight) -> str:
        return (
            f"### {ins.id} · `{ins.scope}/{ins.key}`\n"
            f"- **claim**: {ins.claim}\n"
            f"- **op**: `{ins.proposed_change.op}`\n"
            f"- **confidence**: {ins.confidence:.2f}\n"
            f"- **evidence**: {', '.join(ins.evidence_ids) or '—'}\n"
        )

    @staticmethod
    def _rejected_md(ins: Insight) -> str:
        rej = ins.rejection
        if rej is None:
            return Reflector._insight_md(ins)
        return (
            f"### {ins.id} · `{ins.scope}/{ins.key}`\n"
            f"- **claim**: {ins.claim}\n"
            f"- **rejected by anchor**: [{rej.by_anchor}] {rej.rule}\n"
            f"- **reason**: {rej.reason}\n"
        )

    # ───────────── shared finalize for early returns ─────────────

    def _finalize(
        self,
        *,
        reflection_id: str,
        status: ReflectionStatus,
        notes: str,
        manifest: Manifest,
    ) -> ReflectionResult:
        result = ReflectionResult(
            reflection_id=reflection_id,
            status=status,
            insights_total=0,
            insights_applied=0,
            insights_rejected=0,
            memory_version_before=int(manifest.memory.get("current_version", 0)),
            memory_version_after=int(manifest.memory.get("current_version", 0)),
            notes=notes,
            completed_at=utc_now_iso(),
        )
        # Write a minimal insights file so failed runs are still auditable.
        with suppress(EvolError):
            self._write_insights_md(
                reflection_id=reflection_id,
                result=result,
                applied=[],
                rejected=[],
                superseded=[],
            )
        return result

    # ───────────── iter helpers (used by tests) ─────────────

    def iter_pending_deferred(self) -> Iterator[Path]:
        if not self.deferred_dir.is_dir():
            return
        yield from sorted(self.deferred_dir.glob(f"*{DEFERRED_FILENAME_SUFFIX}"))


__all__ = ["DEFERRED_FILENAME_SUFFIX", "ReflectionResult", "Reflector"]
