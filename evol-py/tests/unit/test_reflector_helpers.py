"""Unit tests for reflector helpers: trigger / batcher / parser / filter / consolidator."""

from __future__ import annotations

import json

import pytest

from evol.config.schema import ReflectionConfig
from evol.core.types import (
    Anchor,
    Experience,
    Insight,
    MemoryEntry,
    MemoryFile,
    ProposedChange,
    Signal,
)
from evol.errors import EvolParseError
from evol.llm import LLMBackendKind, MockLLMClient
from evol.memory.consolidator import (
    Consolidator,
    confidence_cap_for_evidence_count,
)
from evol.reflector.batcher import Batcher
from evol.reflector.filter import AnchorFilter
from evol.reflector.parser import parse_insights
from evol.reflector.trigger import (
    ManualTrigger,
    ScheduledTrigger,
    ThresholdTrigger,
    build_trigger,
)

# ───────────────────────── triggers ─────────────────────────


class HostLikeMockLLM(MockLLMClient):
    backend_kind = LLMBackendKind.HOST
    is_synchronous = False


def test_manual_trigger_never_fires() -> None:
    t = ManualTrigger()
    assert t.should_fire(new_experiences_since_last=0, last_reflection_at=None) is False
    assert t.should_fire(new_experiences_since_last=999, last_reflection_at=None) is False


def test_threshold_trigger_fires_above_threshold() -> None:
    t = ThresholdTrigger(threshold=5)
    assert t.should_fire(new_experiences_since_last=4, last_reflection_at=None) is False
    assert t.should_fire(new_experiences_since_last=5, last_reflection_at=None) is True
    assert t.should_fire(new_experiences_since_last=10, last_reflection_at=None) is True


def test_threshold_rejects_zero() -> None:
    from evol.errors import EvolConfigError  # noqa: PLC0415

    with pytest.raises(EvolConfigError):
        ThresholdTrigger(threshold=0)


def test_build_trigger_dispatches() -> None:
    assert isinstance(build_trigger(ReflectionConfig(trigger="manual")), ManualTrigger)
    assert isinstance(
        build_trigger(ReflectionConfig(trigger="threshold", threshold=10)),
        ThresholdTrigger,
    )


def test_build_trigger_scheduled_requires_schedule() -> None:
    from evol.errors import EvolConfigError  # noqa: PLC0415

    with pytest.raises(EvolConfigError):
        build_trigger(ReflectionConfig(trigger="scheduled"))


def test_scheduled_trigger_no_croniter_returns_false() -> None:
    """If croniter isn't installed, should_fire returns False (manual fallback)."""
    t = ScheduledTrigger("0 * * * *")
    if not t._available:
        assert t.should_fire(new_experiences_since_last=999, last_reflection_at=None) is False


# ───────────────────────── batcher ─────────────────────────


def _make_exp(id_: str, signals: list[Signal] | None = None) -> Experience:
    return Experience(
        id=id_,
        status="closed",
        started_at="2026-05-03T14:30:00.000Z",
        input="x",
        output="y",
        signals=signals or [],
    )


def test_batcher_returns_all_when_under_cap() -> None:
    batcher = Batcher(max_experiences_per_run=10)
    exps = [_make_exp(f"exp_{i}") for i in range(5)]
    out = batcher.select(exps)
    assert len(out) == 5
    assert [e.id for e in out] == [e.id for e in exps]


def test_batcher_drops_low_priority_first() -> None:
    """Cap=2; mix of high (edited) and low (kept) signals."""
    batcher = Batcher(max_experiences_per_run=2)
    high1 = _make_exp("hi_1", [Signal(type="edited", ts="2026-05-03T14:30:00.000Z")])
    low1 = _make_exp("lo_1", [Signal(type="kept", ts="2026-05-03T14:30:00.000Z")])
    high2 = _make_exp("hi_2", [Signal(type="edited", ts="2026-05-03T14:30:00.000Z")])
    low2 = _make_exp("lo_2", [Signal(type="kept", ts="2026-05-03T14:30:00.000Z")])
    out = batcher.select([high1, low1, high2, low2])
    assert {e.id for e in out} == {"hi_1", "hi_2"}
    # Chronological order preserved within result
    assert [e.id for e in out] == ["hi_1", "hi_2"]


def test_batcher_preserves_chronological_order() -> None:
    batcher = Batcher(max_experiences_per_run=3)
    exps = [_make_exp(f"e_{i}") for i in range(5)]
    out = batcher.select(exps)
    ids = [e.id for e in out]
    assert ids == sorted(ids)


# ───────────────────────── parser ─────────────────────────


_REFLECTION_ID = "ref_2026-05-03_a3f9"


def _valid_insight_json() -> str:
    return json.dumps(
        [
            {
                "scope": "user_profile",
                "key": "summary_length",
                "claim": "user prefers shorter",
                "proposed_change": {"op": "set", "value": "60-80"},
                "confidence": 0.85,
                "evidence_ids": ["exp_001", "exp_002"],
            }
        ]
    )


def test_parser_basic() -> None:
    insights = parse_insights(_valid_insight_json(), reflection_id=_REFLECTION_ID)
    assert len(insights) == 1
    assert insights[0].scope == "user_profile"
    assert insights[0].id.startswith("ins_")
    assert insights[0].reflection_id == _REFLECTION_ID


def test_parser_strips_code_fence() -> None:
    raw = f"```json\n{_valid_insight_json()}\n```"
    out = parse_insights(raw, reflection_id=_REFLECTION_ID)
    assert len(out) == 1


def test_parser_handles_wrapping_object() -> None:
    raw = json.dumps({"insights": json.loads(_valid_insight_json())})
    out = parse_insights(raw, reflection_id=_REFLECTION_ID)
    assert len(out) == 1


def test_parser_recovers_from_surrounding_prose() -> None:
    raw = "Here is what I think:\n" + _valid_insight_json() + "\nHope that helps."
    out = parse_insights(raw, reflection_id=_REFLECTION_ID)
    assert len(out) == 1


def test_parser_empty_input_raises() -> None:
    with pytest.raises(EvolParseError):
        parse_insights("", reflection_id=_REFLECTION_ID)


def test_parser_no_array_raises() -> None:
    with pytest.raises(EvolParseError):
        parse_insights("just a string", reflection_id=_REFLECTION_ID)


def test_parser_missing_proposed_change_raises() -> None:
    raw = json.dumps(
        [
            {
                "scope": "user_profile",
                "key": "x",
                "claim": "...",
                "confidence": 0.5,
                "evidence_ids": ["exp_1"],
            }
        ]
    )
    with pytest.raises(EvolParseError):
        parse_insights(raw, reflection_id=_REFLECTION_ID)


def test_parser_invalid_op_raises() -> None:
    raw = json.dumps(
        [
            {
                "scope": "user_profile",
                "key": "x",
                "claim": "...",
                "proposed_change": {"op": "bogus", "value": None},
                "confidence": 0.5,
                "evidence_ids": ["exp_1"],
            }
        ]
    )
    with pytest.raises(EvolParseError):
        parse_insights(raw, reflection_id=_REFLECTION_ID)


def test_parser_missing_evidence_raises() -> None:
    raw = json.dumps(
        [
            {
                "scope": "user_profile",
                "key": "x",
                "claim": "...",
                "proposed_change": {"op": "set", "value": "x"},
                "confidence": 0.5,
            }
        ]
    )
    with pytest.raises(EvolParseError):
        parse_insights(raw, reflection_id=_REFLECTION_ID)


# ───────────────────────── filter ─────────────────────────


def _ins(scope: str, key: str, claim: str) -> Insight:
    return Insight(
        id=f"ins_test_{key}",
        reflection_id=_REFLECTION_ID,
        created_at="2026-05-03T20:00:00.000Z",
        scope=scope,  # type: ignore[arg-type]
        key=key,
        claim=claim,
        proposed_change=ProposedChange(op="set", value="v"),
        confidence=0.8,
        evidence_ids=["exp_1"],
    )


def _anchor(idx: int, kind: str, rule: str) -> Anchor:
    return Anchor(
        index=idx,
        description="d",
        kind=kind,  # type: ignore[arg-type]
        rule=rule,
        rule_hash="sha256:0",
        activated_at="2026-04-01T00:00:00.000Z",
    )


def test_anchor_filter_regex_rejects() -> None:
    f = AnchorFilter(anchors=[_anchor(0, "regex", r"swear|curse")])
    out = f.filter(
        [
            _ins("user_profile", "tone", "user likes to curse a lot"),
            _ins("user_profile", "topic", "user writes about AI"),
        ]
    )
    assert len(out.rejected) == 1
    assert out.rejected[0].rejection.by_anchor == 0
    assert len(out.approved) == 1


def test_anchor_filter_regex_invalid_pattern_fail_safe() -> None:
    """A bad regex is treated as a conflict (fail-safe)."""
    f = AnchorFilter(anchors=[_anchor(0, "regex", r"[unclosed")])
    out = f.filter([_ins("user_profile", "x", "anything")])
    assert len(out.rejected) == 1


def test_anchor_filter_text_with_synchronous_llm() -> None:
    llm = MockLLMClient(["PASS", "REJECT"])
    f = AnchorFilter(
        anchors=[_anchor(0, "text", "no political opinions")],
        llm=llm,
    )
    out = f.filter(
        [
            _ins("user_profile", "k1", "user prefers short emails"),
            _ins("user_profile", "k2", "user is a left-leaning voter"),
        ]
    )
    assert len(out.approved) == 1
    assert len(out.rejected) == 1


def test_anchor_filter_unknown_verdict_fail_safe() -> None:
    llm = MockLLMClient(["UNKNOWN"])
    f = AnchorFilter(
        anchors=[_anchor(0, "text", "no x")],
        llm=llm,
    )
    out = f.filter([_ins("user_profile", "k", "claim")])
    assert len(out.rejected) == 1


def test_anchor_filter_text_no_llm_fail_safe() -> None:
    f = AnchorFilter(anchors=[_anchor(0, "text", "no x")], llm=None)
    out = f.filter([_ins("user_profile", "k", "claim")])
    assert len(out.rejected) == 1


def test_anchor_filter_host_text_default_fail_safe() -> None:
    f = AnchorFilter(
        anchors=[_anchor(0, "text", "no x")],
        llm=HostLikeMockLLM([]),
    )
    out = f.filter([_ins("user_profile", "k", "claim")])
    assert len(out.rejected) == 1


def test_anchor_filter_host_text_allow_strategy_approves() -> None:
    f = AnchorFilter(
        anchors=[_anchor(0, "text", "no x")],
        llm=HostLikeMockLLM([]),
        host_text_strategy="allow",
    )
    out = f.filter([_ins("user_profile", "k", "claim")])
    assert len(out.approved) == 1
    assert len(out.rejected) == 0


# ───────────────────────── consolidator ─────────────────────────


def test_confidence_cap_table() -> None:
    assert confidence_cap_for_evidence_count(0) == 0.0
    assert confidence_cap_for_evidence_count(1) == 0.30
    assert confidence_cap_for_evidence_count(3) == 0.60
    assert confidence_cap_for_evidence_count(7) == 0.85
    assert confidence_cap_for_evidence_count(10) == 0.95


def _empty_memory(kind: str) -> MemoryFile:
    return MemoryFile(
        memory_kind=kind,  # type: ignore[arg-type]
        version=0,
        last_updated="2026-05-03T20:00:00.000Z",
        entries=[],
    )


def _all_empty_mem() -> dict:
    return {k: _empty_memory(k) for k in ("user_profile", "domain_knowledge", "self_awareness")}


def _set_insight(scope: str, key: str, value: str, *, confidence: float = 0.85,
                 evidence_count: int = 4) -> Insight:
    return Insight(
        id=f"ins_test_{key}",
        reflection_id=_REFLECTION_ID,
        created_at="2026-05-03T20:00:00.000Z",
        scope=scope,  # type: ignore[arg-type]
        key=key,
        claim=f"prefers {value}",
        proposed_change=ProposedChange(op="set", value=value),
        confidence=confidence,
        evidence_ids=[f"exp_{i:03d}" for i in range(evidence_count)],
    )


def test_consolidator_set_creates_entry() -> None:
    c = Consolidator()
    out = c.apply([_set_insight("user_profile", "tone", "concise")], _all_empty_mem())
    new_user = out.files["user_profile"]
    assert new_user.version == 1
    assert len(new_user.entries) == 1
    assert new_user.entries[0].key == "tone"
    assert new_user.entries[0].value == "concise"
    assert new_user.entries[0].confidence == 0.85   # 4 evidence → cap 0.85
    assert len(out.applied) == 1


def test_consolidator_confidence_capped() -> None:
    """LLM claims confidence=0.99 with only 1 evidence — must be capped at 0.30."""
    c = Consolidator()
    ins = _set_insight("user_profile", "k", "v", confidence=0.99, evidence_count=1)
    out = c.apply([ins], _all_empty_mem())
    assert out.files["user_profile"].entries[0].confidence == 0.30


def test_consolidator_merge_existing_unions_evidence() -> None:
    c = Consolidator()
    mem = _all_empty_mem()
    mem["user_profile"].entries.append(
        MemoryEntry(
            key="tone", value="concise", confidence=0.30,
            evidence_ids=["exp_old_1"], rationale="initial",
            created_at="2026-04-01T00:00:00.000Z",
            last_validated_at="2026-04-01T00:00:00.000Z",
            last_revision_id="ins_old",
        )
    )
    new_ins = Insight(
        id="ins_new", reflection_id=_REFLECTION_ID,
        created_at="2026-05-03T20:00:00.000Z",
        scope="user_profile", key="tone",
        claim="concise confirmed",
        proposed_change=ProposedChange(op="merge", value=None),
        confidence=0.7, evidence_ids=["exp_new_1", "exp_new_2"],
    )
    out = c.apply([new_ins], mem)
    entry = out.files["user_profile"].entries[0]
    assert set(entry.evidence_ids) == {"exp_old_1", "exp_new_1", "exp_new_2"}
    # Confidence = max(0.30, 0.70) capped by 3 evidence → 0.60
    assert entry.confidence == 0.60
    assert entry.revision_count == 1


def test_consolidator_strengthen_increases_confidence() -> None:
    c = Consolidator()
    mem = _all_empty_mem()
    mem["user_profile"].entries.append(
        MemoryEntry(
            key="k", value="v", confidence=0.30,
            evidence_ids=["e1"], rationale="r",
            created_at="2026-04-01T00:00:00.000Z",
            last_validated_at="2026-04-01T00:00:00.000Z",
            last_revision_id="ins_old",
        )
    )
    new_ins = Insight(
        id="ins_new", reflection_id=_REFLECTION_ID,
        created_at="2026-05-03T20:00:00.000Z",
        scope="user_profile", key="k", claim="strengthen",
        proposed_change=ProposedChange(op="strengthen", value=0.20),
        confidence=0.5, evidence_ids=["e2", "e3", "e4"],
    )
    out = c.apply([new_ins], mem)
    entry = out.files["user_profile"].entries[0]
    # 4 evidence → cap 0.85; old 0.30 + 0.20 = 0.50, capped at 0.85
    assert entry.confidence == 0.5


def test_consolidator_weaken_retires_below_threshold() -> None:
    c = Consolidator()
    mem = _all_empty_mem()
    mem["user_profile"].entries.append(
        MemoryEntry(
            key="k", value="v", confidence=0.15,
            evidence_ids=["e1"], rationale="r",
            created_at="2026-04-01T00:00:00.000Z",
            last_validated_at="2026-04-01T00:00:00.000Z",
            last_revision_id="ins_old",
        )
    )
    new_ins = Insight(
        id="ins_new", reflection_id=_REFLECTION_ID,
        created_at="2026-05-03T20:00:00.000Z",
        scope="user_profile", key="k", claim="weaken",
        proposed_change=ProposedChange(op="weaken", value=0.10),
        confidence=0.3, evidence_ids=["e2"],
    )
    out = c.apply([new_ins], mem)
    entry = out.files["user_profile"].entries[0]
    assert entry.status == "retired"


def test_consolidator_retire_marks_retired() -> None:
    c = Consolidator()
    mem = _all_empty_mem()
    mem["user_profile"].entries.append(
        MemoryEntry(
            key="k", value="v", confidence=0.85,
            evidence_ids=["e1"], rationale="r",
            created_at="2026-04-01T00:00:00.000Z",
            last_validated_at="2026-04-01T00:00:00.000Z",
            last_revision_id="ins_old",
        )
    )
    new_ins = Insight(
        id="ins_new", reflection_id=_REFLECTION_ID,
        created_at="2026-05-03T20:00:00.000Z",
        scope="user_profile", key="k", claim="retire",
        proposed_change=ProposedChange(op="retire", value=None),
        confidence=0.6, evidence_ids=["e2"],
    )
    out = c.apply([new_ins], mem)
    assert out.files["user_profile"].entries[0].status == "retired"


def test_consolidator_conflict_keeps_top_confidence() -> None:
    """Two insights for same (scope, key) — top by confidence wins, others superseded."""
    c = Consolidator()
    a = _set_insight("user_profile", "tone", "verbose", confidence=0.40, evidence_count=2)
    b = _set_insight("user_profile", "tone", "concise", confidence=0.85, evidence_count=4)
    out = c.apply([a, b], _all_empty_mem())
    assert out.files["user_profile"].entries[0].value == "concise"
    assert len(out.applied) == 1
    assert len(out.superseded) == 1


def test_consolidator_input_memory_unmutated() -> None:
    """Consolidator must work on copies — caller's input dict stays clean."""
    c = Consolidator()
    mem_in = _all_empty_mem()
    c.apply([_set_insight("user_profile", "k", "v")], mem_in)
    assert mem_in["user_profile"].version == 0
    assert mem_in["user_profile"].entries == []
