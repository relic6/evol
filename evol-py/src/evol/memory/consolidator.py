"""Apply approved Insights to Memory.

Implements FLOWS §3.7's five operations:

  - ``set``        — replace value (creates entry if missing)
  - ``merge``      — union evidence_ids, recompute confidence, update value
  - ``strengthen`` — bump confidence (capped); union evidence_ids
  - ``weaken``     — lower confidence; retire if below threshold
  - ``retire``     — mark entry ``retired`` (kept for history)

Confidence is hard-capped by evidence count per DATA-MODEL §9.3:

    1     ≤ 0.30
    2-3   ≤ 0.60
    4-7   ≤ 0.85
    ≥ 8   ≤ 0.95
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from evol.core.time_utils import utc_now_iso
from evol.core.types import (
    Insight,
    InsightOp,
    MemoryEntry,
    MemoryEntryStatus,
    MemoryFile,
    MemoryKind,
)
from evol.errors import EvolError
from evol.logging import get_logger

_log = get_logger("evol.memory.consolidator")

_RETIRE_THRESHOLD = 0.10
_MEMORY_KINDS: tuple[MemoryKind, ...] = (
    "user_profile",
    "domain_knowledge",
    "self_awareness",
)


def confidence_cap_for_evidence_count(n: int) -> float:
    """Confidence ceiling based on supporting evidence count."""
    if n <= 0:
        return 0.0
    if n == 1:
        return 0.30
    if n <= 3:
        return 0.60
    if n <= 7:
        return 0.85
    return 0.95


def _capped(confidence: float, evidence_count: int) -> float:
    return max(0.0, min(confidence, confidence_cap_for_evidence_count(evidence_count)))


@dataclass
class ConsolidationResult:
    files: dict[MemoryKind, MemoryFile]
    applied: list[Insight]
    superseded: list[Insight]


class Consolidator:
    """Apply a batch of approved Insights to current Memory state.

    Stateless — pass the current ``MemoryFile`` set in, get an updated set
    out. The caller is responsible for persisting + versioning.
    """

    def apply(
        self,
        insights: Iterable[Insight],
        memory: dict[MemoryKind, MemoryFile],
    ) -> ConsolidationResult:
        # Group insights by (scope, key); resolve conflicts within a batch.
        grouped: dict[tuple[str, str], list[Insight]] = {}
        for ins in insights:
            grouped.setdefault((ins.scope, ins.key), []).append(ins)

        applied: list[Insight] = []
        superseded: list[Insight] = []
        # Mutate copies so the caller's input dict is left intact.
        files = {k: v.model_copy(deep=True) for k, v in memory.items()}

        for (scope, key), bucket in grouped.items():
            top, *others = sorted(bucket, key=lambda i: i.confidence, reverse=True)
            if scope not in files:
                # ``meta`` scope or future kinds — skip in v0.1.
                _log.warning(
                    "skipping insight with unknown scope",
                    extra={"scope": scope, "key": key},
                )
                continue
            memory_scope = scope
            try:
                self._apply_one(top, files[memory_scope], extra_evidence=_collect_evidence(others))
                applied.append(top.model_copy(update={"status": "applied",
                                                        "applied_to": f"mem_{scope}#{key}"}))
            except EvolError as e:
                _log.warning(
                    "consolidator failed to apply insight",
                    extra={"insight_id": top.id, "err": str(e)},
                )
                continue

            for sup in others:
                superseded.append(sup.model_copy(update={"status": "superseded"}))

        # Bump version + last_updated on touched files.
        touched = {ins.scope for ins in applied if ins.scope in _MEMORY_KINDS}
        now = utc_now_iso()
        for scope in touched:
            mf = files[scope]
            files[scope] = mf.model_copy(
                update={
                    "version": mf.version + 1,
                    "last_updated": now,
                }
            )

        return ConsolidationResult(files=files, applied=applied, superseded=superseded)

    # ─── per-insight application ───

    def _apply_one(
        self,
        ins: Insight,
        memfile: MemoryFile,
        *,
        extra_evidence: list[str],
    ) -> None:
        op: InsightOp = ins.proposed_change.op
        target = self._find_entry(memfile, ins.key)

        if op == "set":
            self._op_set(memfile, ins, extra_evidence)
        elif op == "merge":
            if target is None:
                self._op_set(memfile, ins, extra_evidence)
            else:
                self._op_merge(target, ins, extra_evidence)
        elif op == "strengthen":
            if target is None:
                self._op_set(memfile, ins, extra_evidence)
            else:
                self._op_strengthen(target, ins, extra_evidence)
        elif op == "weaken":
            if target is not None:
                self._op_weaken(target, ins, extra_evidence)
        elif op == "retire":
            if target is not None:
                target.status = "retired"
                target.last_validated_at = utc_now_iso()
                target.last_revision_id = ins.id
                target.revision_count += 1
        else:
            raise EvolError(f"unknown op {op!r} on insight {ins.id}")

    @staticmethod
    def _find_entry(memfile: MemoryFile, key: str) -> MemoryEntry | None:
        for e in memfile.entries:
            if e.key == key and e.status != "retired":
                return e
        return None

    # ─── ops ───

    def _op_set(
        self,
        memfile: MemoryFile,
        ins: Insight,
        extra_evidence: list[str],
    ) -> None:
        evidence = _dedupe(list(ins.evidence_ids) + extra_evidence)
        now = utc_now_iso()
        target = self._find_entry(memfile, ins.key)
        if target is None:
            new_entry = MemoryEntry(
                key=ins.key,
                value=ins.proposed_change.value,
                confidence=_capped(ins.confidence, len(evidence)),
                evidence_ids=evidence,
                rationale=ins.claim,
                created_at=now,
                last_validated_at=now,
                last_revision_id=ins.id,
                revision_count=0,
                status="active",
            )
            memfile.entries.append(new_entry)
        else:
            target.value = ins.proposed_change.value
            target.evidence_ids = evidence
            target.confidence = _capped(ins.confidence, len(evidence))
            target.rationale = ins.claim
            target.last_validated_at = now
            target.last_revision_id = ins.id
            target.revision_count += 1
            target.status = "active"

    def _op_merge(
        self,
        target: MemoryEntry,
        ins: Insight,
        extra_evidence: list[str],
    ) -> None:
        merged_evidence = _dedupe(
            list(target.evidence_ids) + list(ins.evidence_ids) + extra_evidence
        )
        # When LLM supplied a new value, prefer it; otherwise keep existing.
        new_value = ins.proposed_change.value if ins.proposed_change.value is not None else target.value
        target.value = new_value
        target.evidence_ids = merged_evidence
        target.confidence = _capped(
            max(target.confidence, ins.confidence), len(merged_evidence)
        )
        target.rationale = ins.claim
        target.last_validated_at = utc_now_iso()
        target.last_revision_id = ins.id
        target.revision_count += 1
        target.status = "active"

    def _op_strengthen(
        self,
        target: MemoryEntry,
        ins: Insight,
        extra_evidence: list[str],
    ) -> None:
        evidence = _dedupe(
            list(target.evidence_ids) + list(ins.evidence_ids) + extra_evidence
        )
        delta = float(ins.proposed_change.value or 0.05)
        target.confidence = _capped(target.confidence + delta, len(evidence))
        target.evidence_ids = evidence
        target.last_validated_at = utc_now_iso()
        target.last_revision_id = ins.id
        target.revision_count += 1

    def _op_weaken(
        self,
        target: MemoryEntry,
        ins: Insight,
        extra_evidence: list[str],
    ) -> None:
        evidence = _dedupe(
            list(target.evidence_ids) + list(ins.evidence_ids) + extra_evidence
        )
        delta = float(ins.proposed_change.value or 0.10)
        target.confidence = max(0.0, target.confidence - delta)
        target.evidence_ids = evidence
        target.last_validated_at = utc_now_iso()
        target.last_revision_id = ins.id
        target.revision_count += 1
        if target.confidence < _RETIRE_THRESHOLD:
            target.status = _retired_status()


def _retired_status() -> MemoryEntryStatus:
    return "retired"


def _collect_evidence(insights: list[Insight]) -> list[str]:
    out: list[str] = []
    for ins in insights:
        out.extend(ins.evidence_ids)
    return out


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            result.append(it)
    return result


__all__ = ["ConsolidationResult", "Consolidator", "confidence_cap_for_evidence_count"]
