"""Protocol-level data types.

These pydantic models are the **on-the-wire** representation of every entity
EVOL persists. Their field names, ordering, and JSON encoding form part of
the EVOL Disk Protocol — any change here is a protocol change.

See DATA-MODEL.md for field-level specification.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ───────────────────────── primitive aliases ─────────────────────────

ISO8601 = str
"""ISO 8601 timestamp string in UTC, with millisecond precision and ``Z`` suffix.

Example: ``"2026-05-03T14:30:00.123Z"``."""


# ───────────────────────── Signal ─────────────────────────

SignalType = Literal["kept", "edited", "discarded", "rated", "dwell", "comment"]


class Signal(BaseModel):
    """User feedback attached to a single Experience.

    ``type`` is open-ended (custom values must use a namespace prefix like
    ``"myorg:click_through"``). ``value`` is type-specific (e.g. ``int 1..5``
    for ``rated``, ``int ms`` for ``dwell``, ``str`` for ``comment``).
    """

    model_config = ConfigDict(extra="allow")

    type: str
    ts: ISO8601
    value: Any | None = None
    source: Literal["explicit", "implicit"] = "explicit"
    weight: float | None = None


# ───────────────────────── Experience ─────────────────────────

ExperienceStatus = Literal["open", "closed", "orphaned", "redacted"]


class Experience(BaseModel):
    """A single recorded task interaction. Append-only; never mutated in place.

    Field order MUST match DATA-MODEL §11 canonicalization rules so cross-SDK
    checksums agree.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    task_kind: str = "default"
    status: ExperienceStatus
    started_at: ISO8601
    ended_at: ISO8601 | None = None
    input: Any
    output: Any | None = None
    signals: list[Signal] = Field(default_factory=list)
    advice_used: list[str] = Field(default_factory=list)
    anchors_applied: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    redacted: bool = False


# ───────────────────────── Insight ─────────────────────────

InsightScope = Literal["user_profile", "domain_knowledge", "self_awareness", "meta"]
InsightStatus = Literal["pending", "applied", "rejected", "superseded"]
InsightOp = Literal["set", "merge", "strengthen", "weaken", "retire"]


class ProposedChange(BaseModel):
    """The structured operation a passing Insight applies to Memory."""

    model_config = ConfigDict(extra="allow")

    op: InsightOp
    value: Any | None = None


class Rejection(BaseModel):
    """Set on Insights filtered out by an Anchor.

    The ``by_anchor`` index refers to ``anchors[i]`` in evol.config.yaml so
    audit trails remain intelligible even if an anchor's text changes.
    """

    by_anchor: int
    rule: str
    reason: str


class Insight(BaseModel):
    """An LLM-produced structured claim derived from a batch of Experiences.

    Insights themselves are **immutable** once written. Updates to the same
    Memory key produce *new* Insights, while older ones are marked
    ``status: superseded``.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    reflection_id: str
    created_at: ISO8601
    scope: InsightScope
    key: str
    claim: str
    proposed_change: ProposedChange
    confidence: float
    evidence_ids: list[str]
    status: InsightStatus = "pending"
    rejection: Rejection | None = None
    applied_to: str | None = None
    notes: str | None = None


# ───────────────────────── Memory ─────────────────────────

MemoryKind = Literal["user_profile", "domain_knowledge", "self_awareness"]
MemoryEntryStatus = Literal["active", "retired", "superseded"]


class MemoryEntry(BaseModel):
    """A single fact / preference / heuristic the system has learned."""

    model_config = ConfigDict(extra="allow")

    key: str
    value: Any
    confidence: float
    evidence_ids: list[str]
    rationale: str
    created_at: ISO8601
    last_validated_at: ISO8601
    last_revision_id: str
    revision_count: int = 0
    status: MemoryEntryStatus = "active"


class MemoryFile(BaseModel):
    """Outer wrapper for a single ``memory/<kind>.yaml`` file.

    The ``checksum`` is filled only after canonical serialization; in-memory
    instances may carry ``None`` until they are written.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    memory_kind: MemoryKind
    version: int
    last_updated: ISO8601
    checksum: str | None = None
    entries: list[MemoryEntry] = Field(default_factory=list)


# ───────────────────────── Anchor (runtime) ─────────────────────────

AnchorKind = Literal["text", "regex", "semantic"]


class Anchor(BaseModel):
    """Runtime view of an Anchor — config form + provenance metadata.

    The ``rule_hash`` is sha256 of the rule body; on each startup this hash
    is recomputed and compared against the manifest's record. A mismatch
    indicates the anchor was edited and SDK MUST force a Memory snapshot
    before continuing.
    """

    model_config = ConfigDict(extra="allow")

    index: int
    description: str
    kind: AnchorKind
    rule: str
    rule_hash: str
    activated_at: ISO8601
    deactivated_at: ISO8601 | None = None


# ───────────────────────── Manifest ─────────────────────────


class Manifest(BaseModel):
    """The ``manifest.yaml`` file at the root of ``.evol/``.

    Stores protocol version, current Memory pointer, experience counters,
    anchor history, and free-form metadata.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    protocol_version: str = "0.1"
    product: dict[str, str] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    experiences: dict[str, Any] = Field(default_factory=dict)
    last_reflection: dict[str, Any] | None = None
    anchors: list[Anchor] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ───────────────────────── DeferredState (host backend) ─────────────────────────


class DeferredState(BaseModel):
    """EVOL-internal state for a deferred LLM request (host backend).

    Persisted under ``.evol/deferred/<request_id>.state.json`` so that a
    deferred request can survive process restarts. See LLM-BACKENDS §6.6
    and FLOWS §3.5 / §3.10.
    """

    model_config = ConfigDict(extra="allow")

    request_id: str
    purpose: Literal["reflection", "anchor_check", "inspiration"]
    pending_path: str
    expected_response_path: str
    created_at: ISO8601
    expires_at: ISO8601 | None = None
    status: Literal["pending", "consumed", "expired", "parse_failed"] = "pending"
    consumed_at: ISO8601 | None = None
    reflection_id: str | None = None


__all__ = [
    "ISO8601",
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
]
