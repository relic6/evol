"""Unit tests for advisor: retrieval / budget / inspiration_history / advisor facade."""

from __future__ import annotations

from pathlib import Path

import pytest

from evol.advisor import (
    BudgetManager,
    Inspiration,
    InspirationHistory,
    InspirationRecord,
    Retrieval,
    derive_keys,
    parse_inspiration,
)
from evol.advisor.advisor import (
    advice_ref,
    render_advice_block,
    render_candidate_line,
)
from evol.advisor.retrieval import Candidate
from evol.core.types import MemoryEntry, MemoryFile
from evol.errors import EvolParseError
from evol.llm import MockLLMClient


# ─── derive_keys ───


def test_derive_keys_includes_task_kind_and_tags() -> None:
    keys = derive_keys(
        "please summarize this article carefully",
        {"task_kind": "summarize", "tags": ["news", "短"]},
    )
    assert "summarize" in keys
    assert "news" in keys
    assert "短" in keys


def test_derive_keys_dedupes_and_lowercases() -> None:
    keys = derive_keys(
        "Summarize Summarize SUMMARIZE",
        {"task_kind": "summarize"},
    )
    assert keys.count("summarize") == 1


def test_derive_keys_empty_prompt() -> None:
    keys = derive_keys("", {"task_kind": "x"})
    assert keys == ["x"]


# ─── retrieval ───


def _entry(
    key: str,
    *,
    value: str = "v",
    confidence: float = 0.85,
    last_validated_at: str = "2026-05-01T00:00:00.000Z",
) -> MemoryEntry:
    return MemoryEntry(
        key=key,
        value=value,
        confidence=confidence,
        evidence_ids=["exp_1"],
        rationale="r",
        created_at="2026-04-01T00:00:00.000Z",
        last_validated_at=last_validated_at,
        last_revision_id="ins_x",
    )


def _empty_mem(kind: str) -> MemoryFile:
    return MemoryFile(
        memory_kind=kind,  # type: ignore[arg-type]
        version=0,
        last_updated="2026-05-03T20:00:00.000Z",
        entries=[],
    )


def _mem_with(kind: str, entries: list[MemoryEntry]) -> dict:
    out = {k: _empty_mem(k) for k in ("user_profile", "domain_knowledge", "self_awareness")}
    out[kind].entries = entries
    return out


def test_retrieval_keyword_hit_in_key() -> None:
    r = Retrieval()
    mem = _mem_with("user_profile", [_entry("summary_length"), _entry("tone")])
    out = r.relevant_entries(mem, ["summary"], {"task_kind": "summarize"})
    assert len(out) == 1
    assert out[0].entry.key == "summary_length"


def test_retrieval_filters_below_min_confidence() -> None:
    r = Retrieval()
    mem = _mem_with(
        "user_profile",
        [
            _entry("summary_length", confidence=0.85),
            _entry("summary_format", confidence=0.10),
        ],
    )
    out = r.relevant_entries(mem, ["summary"], min_confidence=0.30)
    assert {c.entry.key for c in out} == {"summary_length"}


def test_retrieval_skips_retired_entries() -> None:
    r = Retrieval()
    e_active = _entry("k_active")
    e_retired = _entry("k_retired")
    e_retired.status = "retired"
    mem = _mem_with("user_profile", [e_active, e_retired])
    out = r.relevant_entries(mem, ["k"])
    assert {c.entry.key for c in out} == {"k_active"}


def test_retrieval_orders_by_score_desc() -> None:
    r = Retrieval()
    mem = _mem_with(
        "user_profile",
        [
            _entry("foo", confidence=0.30),
            _entry("foobar", value="foo and more", confidence=0.85),
        ],
    )
    out = r.relevant_entries(mem, ["foo"], min_confidence=0.30)
    assert out[0].entry.key == "foobar"
    assert out[0].score >= out[1].score


# ─── budget ───


def _candidate(key: str, value: str = "v", confidence: float = 0.85) -> Candidate:
    e = _entry(key, value=value, confidence=confidence)
    return Candidate(score=1.0, entry=e, kind="user_profile")


def test_budget_fits_all_when_room() -> None:
    mock = MockLLMClient([])
    bm = BudgetManager(mock, max_advice_tokens=1000, ratio=1.0)
    plan = bm.fit("a long prompt " * 50, [_candidate("a"), _candidate("b")])
    assert len(plan.selected) == 2


def test_budget_drops_overflow() -> None:
    mock = MockLLMClient([])
    bm = BudgetManager(mock, max_advice_tokens=20, ratio=0.001)
    very_long = _candidate("k", value="x" * 1000)
    plan = bm.fit("tiny", [very_long])
    assert plan.selected == []


def test_budget_min_floor_allows_small_advice_block() -> None:
    """Even on tiny prompts, we get at least the minimum budget."""
    mock = MockLLMClient([])
    bm = BudgetManager(mock, max_advice_tokens=1000, ratio=0.30)
    plan = bm.fit("hi", [_candidate("k", value="short")])
    assert plan.budget_tokens >= 60


# ─── advice rendering ───


def test_render_candidate_line_format() -> None:
    line = render_candidate_line(_candidate("tone", value="concise", confidence=0.85))
    assert "[user_profile / tone, conf 0.85]" in line
    assert "concise" in line


def test_render_advice_block_includes_trace_comments() -> None:
    block = render_advice_block(
        [_candidate("k1", value="v1"), _candidate("k2", value="v2")]
    )
    assert "[Advice from EVOL" in block
    assert "[End advice]" in block
    assert "<!-- evol:advice ref=\"mem_user_profile#k1\"" in block
    assert "<!-- evol:advice ref=\"mem_user_profile#k2\"" in block


def test_render_advice_block_empty_returns_empty() -> None:
    assert render_advice_block([]) == ""


def test_advice_ref_format() -> None:
    assert advice_ref(_candidate("tone")) == "mem_user_profile#tone"


# ─── inspiration parsing ───


def test_parse_inspiration_basic() -> None:
    raw = '{"kind": "suggestion", "text": "try short summaries", "evidence_ids": ["exp_1"]}'
    out = parse_inspiration(raw)
    assert out is not None
    assert out.kind == "suggestion"
    assert out.text == "try short summaries"


def test_parse_inspiration_none_returns_none() -> None:
    raw = '{"kind": "none", "text": null, "evidence_ids": []}'
    assert parse_inspiration(raw) is None


def test_parse_inspiration_strips_code_fence() -> None:
    raw = '```json\n{"kind": "pattern", "text": "x", "evidence_ids": ["e1"]}\n```'
    out = parse_inspiration(raw)
    assert out is not None
    assert out.kind == "pattern"


def test_parse_inspiration_recovers_from_prose() -> None:
    raw = 'sure!\n{"kind": "question", "text": "?", "evidence_ids": ["e1"]}\nthanks'
    out = parse_inspiration(raw)
    assert out is not None
    assert out.kind == "question"


def test_parse_inspiration_empty_raises() -> None:
    with pytest.raises(EvolParseError):
        parse_inspiration("")


def test_parse_inspiration_invalid_kind_raises() -> None:
    raw = '{"kind": "bogus", "text": "x", "evidence_ids": ["e1"]}'
    with pytest.raises(EvolParseError):
        parse_inspiration(raw)


# ─── inspiration history ───


def test_inspiration_history_round_trip(tmp_path: Path) -> None:
    h = InspirationHistory(tmp_path)
    h.ensure_initialized()
    h.record(
        InspirationRecord(
            id="ins_emit_1",
            ts="2026-05-03T20:00:00.000Z",
            kind="suggestion",
            evidence_ids=["e1", "e2"],
            text_preview="short text",
        )
    )
    records = h.iter_all()
    assert len(records) == 1
    assert records[0]["kind"] == "suggestion"


def test_inspiration_history_count_today(tmp_path: Path, monkeypatch) -> None:
    h = InspirationHistory(tmp_path)
    h.ensure_initialized()

    today = "2026-05-03"
    monkeypatch.setattr("evol.advisor.inspiration_history.utc_now_iso", lambda: f"{today}T20:00:00.000Z")
    for i in range(3):
        h.record(
            InspirationRecord(
                id=f"ins_{i}",
                ts=f"{today}T1{i}:00:00.000Z",
                kind="pattern",
                evidence_ids=["e"],
            )
        )
    h.record(
        InspirationRecord(
            id="ins_yesterday",
            ts="2026-05-02T20:00:00.000Z",
            kind="pattern",
            evidence_ids=["e"],
        )
    )
    assert h.count_today() == 3


def test_inspiration_history_in_cooldown_no_records(tmp_path: Path) -> None:
    h = InspirationHistory(tmp_path)
    h.ensure_initialized()
    assert h.in_cooldown(hours=1) is False


def test_inspiration_history_in_cooldown_after_record(tmp_path: Path) -> None:
    from evol.core.time_utils import utc_now_iso  # noqa: PLC0415

    h = InspirationHistory(tmp_path)
    h.ensure_initialized()
    h.record(
        InspirationRecord(
            id="ins_1",
            ts=utc_now_iso(),
            kind="pattern",
            evidence_ids=["e1"],
        )
    )
    assert h.in_cooldown(hours=24) is True
