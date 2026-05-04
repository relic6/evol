"""End-to-end Phase 4 integration: enhance + inspire + reflect + cli ops."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evol import Evol
from evol.core.types import MemoryEntry, MemoryFile, Signal
from evol.llm import MockLLMClient

# ─── helpers ───


def _write_config(tmp_path: Path, *, anchors=None, llm_block: str = "") -> Path:
    p = tmp_path / "evol.config.yaml"
    body = (
        "schema_version: 1\n"
        "product:\n  name: test-cli\n  version: 0.0.1\n"
        "inspiration:\n  frequency: high\n  cooldown_hours: 0\n  max_per_day: 100\n"
    )
    if anchors:
        body += "anchors:\n"
        for a in anchors:
            body += (
                f"  - description: {a['description']}\n"
                f"    kind: {a['kind']}\n"
                f"    rule: {a['rule']}\n"
            )
    if llm_block:
        body += llm_block
    p.write_text(body, encoding="utf-8")
    return p


def _seed_user_profile_entry(evol: Evol, *, key: str, value: str, confidence: float = 0.85,
                              evidence: int = 4) -> None:
    """Inject a Memory entry directly so retrieval has something to find."""
    mf = MemoryFile(
        memory_kind="user_profile",
        version=1,
        last_updated="2026-05-03T20:00:00.000Z",
        entries=[
            MemoryEntry(
                key=key,
                value=value,
                confidence=confidence,
                evidence_ids=[f"exp_{i:03d}" for i in range(evidence)],
                rationale="seeded",
                created_at="2026-04-01T00:00:00.000Z",
                last_validated_at="2026-05-03T20:00:00.000Z",
                last_revision_id="ins_seed",
            )
        ],
    )
    evol.memory_store.save("user_profile", mf)


# ─── enhance ───


@pytest.mark.integration
def test_enhance_injects_memory_into_prompt(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    evol = Evol.from_config(config_path)
    evol._llm = MockLLMClient([])

    _seed_user_profile_entry(
        evol, key="summary_length", value="60-80 chars (short)"
    )

    out = evol.advisor.enhance(
        "Summarize today's notes in detail.",
        task={"task_kind": "summarize"},
    )
    assert "[Advice from EVOL" in out
    assert "summary_length" in out
    assert "Summarize today's notes" in out
    # Trace markers present
    assert "<!-- evol:advice ref=\"mem_user_profile#summary_length\"" in out


@pytest.mark.integration
def test_enhance_returns_unchanged_when_memory_empty(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    evol = Evol.from_config(config_path)
    evol._llm = MockLLMClient([])
    original = "do something"
    out = evol.advisor.enhance(original, task={"task_kind": "x"})
    assert out == original


@pytest.mark.integration
def test_enhance_never_raises_on_failure(tmp_path: Path) -> None:
    """enhance must always return *something* — original prompt on error."""
    config_path = _write_config(tmp_path)
    evol = Evol.from_config(config_path)
    evol._llm = MockLLMClient([])

    # Wreck the memory dir to force an internal failure.
    import shutil  # noqa: PLC0415

    shutil.rmtree(evol.memory_store.memory_dir)
    out = evol.advisor.enhance("hello", task={"task_kind": "x"})
    assert out == "hello"


# ─── inspire ───


@pytest.mark.integration
def test_inspire_returns_none_before_warmup(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    evol = Evol.from_config(config_path)
    evol._llm = MockLLMClient([])
    # Below warmup threshold (10 experiences)
    for i in range(3):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")
    assert evol.advisor.inspire() is None


@pytest.mark.integration
def test_inspire_returns_inspiration_via_mock_llm(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    evol = Evol.from_config(config_path)

    raw = json.dumps(
        {
            "kind": "suggestion",
            "text": "try shorter summaries",
            "evidence_ids": ["exp_001", "exp_002"],
        }
    )
    evol._llm = MockLLMClient([raw])

    # Push past warmup
    for i in range(12):
        h = evol.recorder.start_task(f"in-{i}")
        evol.recorder.end_task(h, f"out-{i}")

    insp = evol.advisor.inspire(task={"task_kind": "summarize"})
    assert insp is not None
    assert insp.kind == "suggestion"
    assert insp.text == "try shorter summaries"
    # Recorded in history
    history_path = evol.evol_dir / "insights" / "inspiration_history.jsonl"
    assert history_path.is_file()
    lines = [ln for ln in history_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1


@pytest.mark.integration
def test_inspire_anchor_rejection(tmp_path: Path) -> None:
    """Inspire result violating a regex anchor must be dropped."""
    config_path = _write_config(
        tmp_path,
        anchors=[{"description": "no fab", "kind": "regex", "rule": r"fabricat"}],
    )
    evol = Evol.from_config(config_path)
    raw = json.dumps(
        {
            "kind": "pattern",
            "text": "we should fabricate plausible answers",
            "evidence_ids": ["exp_1"],
        }
    )
    evol._llm = MockLLMClient([raw])

    for i in range(12):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")

    assert evol.advisor.inspire() is None


@pytest.mark.integration
def test_inspire_respects_cooldown(tmp_path: Path) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\n"
        "product:\n  name: t\n  version: 0.0.1\n"
        "inspiration:\n  frequency: high\n  cooldown_hours: 24\n  max_per_day: 100\n",
        encoding="utf-8",
    )
    evol = Evol.from_config(p)

    raw = json.dumps(
        {"kind": "suggestion", "text": "x", "evidence_ids": ["exp_1"]}
    )
    evol._llm = MockLLMClient([raw, raw])

    for i in range(12):
        h = evol.recorder.start_task(f"in-{i}")
        evol.recorder.end_task(h, f"out-{i}")

    first = evol.advisor.inspire()
    assert first is not None
    # Within cooldown window
    second = evol.advisor.inspire()
    assert second is None


@pytest.mark.integration
def test_inspire_respects_daily_quota(tmp_path: Path) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\n"
        "product:\n  name: t\n  version: 0.0.1\n"
        "inspiration:\n  frequency: high\n  cooldown_hours: 0\n  max_per_day: 1\n",
        encoding="utf-8",
    )
    evol = Evol.from_config(p)
    raw = json.dumps(
        {"kind": "suggestion", "text": "x", "evidence_ids": ["exp_1"]}
    )
    evol._llm = MockLLMClient([raw, raw])

    for i in range(12):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")

    assert evol.advisor.inspire() is not None
    assert evol.advisor.inspire() is None  # daily quota exhausted


@pytest.mark.integration
def test_inspire_template_strategy_under_host_backend(tmp_path: Path, monkeypatch) -> None:
    """host_strategy=template uses Memory directly, no LLM."""
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\n"
        "product:\n  name: t\n  version: 0.0.1\n"
        "inspiration:\n  frequency: high\n  cooldown_hours: 0\n"
        "  max_per_day: 100\n  host_strategy: template\n"
        "llm:\n  backend: host\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EVOL_HOST_AGENT", "claude-code")

    evol = Evol.from_config(p)
    _seed_user_profile_entry(
        evol, key="tone", value="prefers concise output", confidence=0.85
    )

    for i in range(12):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")

    insp = evol.advisor.inspire()
    assert insp is not None
    assert insp.kind == "pattern"
    assert "concise" in insp.text


@pytest.mark.integration
def test_inspire_disabled_strategy_returns_none(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\n"
        "product:\n  name: t\n  version: 0.0.1\n"
        "inspiration:\n  frequency: high\n  cooldown_hours: 0\n"
        "  max_per_day: 100\n  host_strategy: disabled\n"
        "llm:\n  backend: host\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EVOL_HOST_AGENT", "claude-code")
    evol = Evol.from_config(p)

    for i in range(12):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")
    assert evol.advisor.inspire() is None


# ─── full lifecycle stress ───


@pytest.mark.integration
def test_100_tasks_then_reflect_then_enhance_picks_up_memory(tmp_path: Path) -> None:
    """Run 100 tasks → reflect (mock LLM produces an insight) → enhance picks
    that insight up on the next call."""
    config_path = _write_config(tmp_path)
    evol = Evol.from_config(config_path)

    insight_response = json.dumps(
        [
            {
                "scope": "user_profile",
                "key": "summary_length",
                "claim": "user prefers very short summaries",
                "proposed_change": {"op": "set", "value": "≤ 50 chars"},
                "confidence": 0.85,
                "evidence_ids": [f"exp_{i:03d}" for i in range(8)],
            }
        ]
    )
    evol._llm = MockLLMClient([insight_response])

    # Generate 100 tasks
    for i in range(100):
        h = evol.recorder.start_task(f"summarize input #{i}", task_kind="summarize")
        evol.recorder.end_task(h, f"summary {i}")
        # 1 in 5 gets an "edited" feedback signal
        if i % 5 == 0:
            evol.recorder.feedback(
                h.experience_id,
                Signal(type="edited", ts="2026-05-03T14:35:00.000Z"),
            )

    assert evol.recorder.count() == 100

    # Reflect — should produce 1 insight, apply it to user_profile
    result = evol.reflector.reflect()
    assert result.status == "completed"
    assert result.insights_applied == 1
    assert result.memory_version_after == 1

    # Now enhance picks it up
    enhanced = evol.advisor.enhance(
        "Summarize this article please.",
        task={"task_kind": "summarize"},
    )
    assert "summary_length" in enhanced
    assert "≤ 50 chars" in enhanced
