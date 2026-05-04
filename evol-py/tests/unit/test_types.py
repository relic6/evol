"""Unit tests for evol.core.types — schema validation, defaults, edge cases."""

from __future__ import annotations

import pytest

from evol.core.types import (
    Anchor,
    DeferredState,
    Experience,
    Insight,
    MemoryEntry,
    MemoryFile,
    ProposedChange,
    Signal,
)


def test_experience_minimal() -> None:
    exp = Experience(
        id="exp_test_0001",
        status="open",
        started_at="2026-05-03T14:30:00.000Z",
        input="hello",
    )
    assert exp.task_kind == "default"
    assert exp.signals == []
    assert exp.advice_used == []
    assert exp.anchors_applied == []
    assert exp.metadata == {}
    assert exp.redacted is False
    assert exp.ended_at is None
    assert exp.output is None


def test_experience_full_round_trip() -> None:
    payload = {
        "id": "exp_2026-05-03T14-30-00-123_a3f9",
        "task_kind": "summarize",
        "status": "closed",
        "started_at": "2026-05-03T14:30:00.123Z",
        "ended_at": "2026-05-03T14:30:02.456Z",
        "input": "today I did stuff",
        "output": "summary",
        "signals": [
            {
                "type": "kept",
                "ts": "2026-05-03T14:35:00.000Z",
                "source": "explicit",
            }
        ],
        "advice_used": ["mem_user_profile_v7#summary_length"],
        "anchors_applied": ["anchors[0]"],
        "metadata": {"sdk": "evol-py", "sdk_version": "0.1.0"},
        "redacted": False,
    }
    exp = Experience.model_validate(payload)
    assert exp.id == payload["id"]
    assert len(exp.signals) == 1
    assert exp.signals[0].type == "kept"


def test_signal_default_source_explicit() -> None:
    s = Signal(type="kept", ts="2026-05-03T14:35:00.000Z")
    assert s.source == "explicit"
    assert s.value is None


def test_signal_namespaced_extension_type() -> None:
    s = Signal(
        type="myorg:click_through", ts="2026-05-03T14:35:00.000Z", value=3, source="implicit"
    )
    assert s.type == "myorg:click_through"
    assert s.source == "implicit"


def test_insight_minimal() -> None:
    ins = Insight(
        id="ins_2026-05-03_001",
        reflection_id="ref_2026-05-03_a3f9",
        created_at="2026-05-03T20:00:00.000Z",
        scope="user_profile",
        key="summary_length",
        claim="prefers shorter summaries",
        proposed_change=ProposedChange(op="set", value="60-80 字"),
        confidence=0.85,
        evidence_ids=["exp_001", "exp_007"],
    )
    assert ins.status == "pending"
    assert ins.rejection is None


def test_memory_entry_round_trip() -> None:
    entry = MemoryEntry(
        key="summary_length",
        value="60-80 字",
        confidence=0.85,
        evidence_ids=["exp_001", "exp_007"],
        rationale="user repeatedly shortens output",
        created_at="2026-04-15T19:00:00.000Z",
        last_validated_at="2026-05-03T20:05:30.000Z",
        last_revision_id="ins_2026-05-03_001",
        revision_count=3,
    )
    assert entry.status == "active"
    dump = entry.model_dump()
    rehydrated = MemoryEntry.model_validate(dump)
    assert rehydrated == entry


def test_memory_file_default_entries_empty() -> None:
    mf = MemoryFile(
        memory_kind="user_profile",
        version=1,
        last_updated="2026-05-03T20:00:00.000Z",
    )
    assert mf.schema_version == 1
    assert mf.checksum is None
    assert mf.entries == []


def test_anchor_round_trip() -> None:
    a = Anchor(
        index=0,
        description="be honest",
        kind="text",
        rule="do not invent facts",
        rule_hash="sha256:abc",
        activated_at="2026-04-01T00:00:00.000Z",
    )
    assert a.deactivated_at is None


def test_deferred_state_default_pending() -> None:
    d = DeferredState(
        request_id="req_test_001",
        purpose="reflection",
        pending_path=".evol/pending_requests/req_test_001.md",
        expected_response_path=".evol/completed_responses/req_test_001.json",
        created_at="2026-05-03T20:00:00.000Z",
    )
    assert d.status == "pending"
    assert d.consumed_at is None


@pytest.mark.parametrize("op", ["set", "merge", "strengthen", "weaken", "retire"])
def test_proposed_change_all_ops(op: str) -> None:
    pc = ProposedChange(op=op, value=None)  # type: ignore[arg-type]
    assert pc.op == op
