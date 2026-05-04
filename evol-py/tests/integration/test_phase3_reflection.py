"""End-to-end Phase 3 integration: reflection cycle, anchor reject, host backend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evol import Evol
from evol.llm import HostAgentClient, MockLLMClient

# ───────────────────────── direct-backend reflection ─────────────────────────


@pytest.mark.integration
def test_reflection_cycle_completes_and_updates_memory(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        anchors=[{"description": "be honest", "kind": "text", "rule": "no fabricated facts"}],
    )

    evol = Evol.from_config(config_path)

    # Generate experiences with explicit feedback signals
    for i in range(5):
        h = evol.recorder.start_task(f"input-{i}", task_kind="summarize")
        evol.recorder.end_task(h, f"output-{i}")
        evol.recorder.feedback(
            h.experience_id,
            {"type": "edited", "ts": "2026-05-03T14:35:00.000Z"},
        )

    # Inject a mock LLM that produces a valid JSON response
    fake = json.dumps(
        [
            {
                "scope": "user_profile",
                "key": "summary_length",
                "claim": "user prefers shorter summaries",
                "proposed_change": {"op": "set", "value": "short"},
                "confidence": 0.85,
                "evidence_ids": [f"exp_{i}" for i in range(5)],
            }
        ]
    )
    # Anchor filter check -> "PASS"; main reflection -> insights array
    evol._llm = MockLLMClient([fake, "PASS"])

    result = evol.reflector.reflect()
    assert result.status == "completed"
    assert result.insights_total == 1
    assert result.insights_applied == 1
    assert result.memory_version_after == 1

    # Memory was actually updated
    mem = evol.memory_store.load("user_profile")
    assert any(e.key == "summary_length" for e in mem.entries)

    # Insights file written
    insights_files = list((evol.evol_dir / "insights").glob("*.md"))
    assert insights_files, "expected an insights/<date>-<reflection_id>.md"


@pytest.mark.integration
def test_reflection_anchor_rejects_violation(tmp_path: Path) -> None:
    """An insight that matches a regex anchor MUST be rejected and logged."""
    config_path = _write_config(
        tmp_path,
        anchors=[
            {
                "description": "no fabrication",
                "kind": "regex",
                "rule": r"fabricat|invent|halluc",
            }
        ],
    )
    evol = Evol.from_config(config_path)

    for i in range(3):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")

    fake = json.dumps(
        [
            {
                "scope": "user_profile",
                "key": "k_good",
                "claim": "user prefers concise output",
                "proposed_change": {"op": "set", "value": "concise"},
                "confidence": 0.85,
                "evidence_ids": ["exp_a", "exp_b"],
            },
            {
                "scope": "user_profile",
                "key": "k_bad",
                "claim": "we should fabricate plausible-sounding answers",
                "proposed_change": {"op": "set", "value": "lie"},
                "confidence": 0.85,
                "evidence_ids": ["exp_c"],
            },
        ]
    )
    evol._llm = MockLLMClient([fake])

    result = evol.reflector.reflect()
    assert result.status == "completed"
    assert result.insights_total == 2
    assert result.insights_applied == 1
    assert result.insights_rejected == 1

    # The bad insight didn't end up in memory
    mem = evol.memory_store.load("user_profile")
    keys = {e.key for e in mem.entries}
    assert "k_good" in keys
    assert "k_bad" not in keys

    # Rejection captured in insights/*.md
    md_text = next((evol.evol_dir / "insights").glob("*.md")).read_text(encoding="utf-8")
    assert "Rejected insights" in md_text
    assert "k_bad" in md_text


@pytest.mark.integration
def test_reflection_no_op_when_no_new_experiences(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    evol = Evol.from_config(config_path)
    evol._llm = MockLLMClient([])
    result = evol.reflector.reflect()
    assert result.status == "no_op"


@pytest.mark.integration
def test_reflection_parse_failure(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    evol = Evol.from_config(config_path)

    for i in range(2):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")

    # Garbage LLM output
    evol._llm = MockLLMClient(["not even close to JSON"])
    result = evol.reflector.reflect()
    assert result.status == "parse_failed"


# ───────────────────────── host-backend reflection ─────────────────────────


@pytest.mark.integration
def test_host_backend_pending_then_resume(tmp_path: Path, monkeypatch) -> None:
    """Host backend: reflect() writes a pending request; once the host
    completes it, resume_pending() consolidates."""
    config_path = _write_config(
        tmp_path,
        llm_block="llm:\n  backend: host\n",
    )
    monkeypatch.setenv("EVOL_HOST_AGENT", "claude-code")

    evol = Evol.from_config(config_path)
    assert isinstance(evol.llm, HostAgentClient)

    for i in range(3):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")

    result = evol.reflector.reflect()
    assert result.status == "pending_host"
    assert result.deferred_id is not None

    # The pending markdown file should exist and be readable
    pending_files = list((evol.evol_dir / "pending_requests").glob("*.md"))
    assert pending_files
    pending_md = pending_files[0].read_text(encoding="utf-8")
    assert "## System Prompt" in pending_md
    assert "## User Prompt" in pending_md

    # A pending insights placeholder was written
    placeholders = list((evol.evol_dir / "insights").glob("*-pending.md"))
    assert placeholders

    # Simulate the host agent completing the request
    deferred_state_files = list((evol.evol_dir / "deferred").glob("*.state.json"))
    assert deferred_state_files
    state = json.loads(deferred_state_files[0].read_text(encoding="utf-8"))
    assert state["status"] == "pending"

    response_path = Path(state["expected_response_path"])
    response_path.write_text(
        json.dumps(
            {
                "insights": [
                    {
                        "scope": "user_profile",
                        "key": "tone",
                        "claim": "user prefers concise",
                        "proposed_change": {"op": "set", "value": "concise"},
                        "confidence": 0.7,
                        "evidence_ids": ["exp_001", "exp_002", "exp_003"],
                    }
                ],
                "model": "claude-code-internal",
            }
        ),
        encoding="utf-8",
    )

    # Now resume_pending should consolidate
    resumed = evol.reflector.resume_pending()
    assert len(resumed) == 1
    assert resumed[0].status == "resumed_host"
    assert resumed[0].insights_applied == 1

    # Deferred state marked as consumed
    new_state = json.loads(deferred_state_files[0].read_text(encoding="utf-8"))
    assert new_state["status"] == "consumed"
    assert new_state["consumed_at"] is not None

    # Resuming again is a no-op (idempotent)
    again = evol.reflector.resume_pending()
    assert again == []


@pytest.mark.integration
def test_host_backend_pickup_only_after_restart(tmp_path: Path, monkeypatch) -> None:
    """Even after Evol restart, deferred pending requests with completed
    responses are picked up automatically on next reflect."""
    config_path = _write_config(tmp_path, llm_block="llm:\n  backend: host\n")
    monkeypatch.setenv("EVOL_HOST_AGENT", "claude-code")

    # Session 1: defer a reflection
    evol1 = Evol.from_config(config_path)
    for i in range(2):
        h = evol1.recorder.start_task(f"x-{i}")
        evol1.recorder.end_task(h, f"y-{i}")
    r1 = evol1.reflector.reflect()
    assert r1.status == "pending_host"

    # Host writes the response between sessions
    state_path = next((evol1.evol_dir / "deferred").glob("*.state.json"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    Path(state["expected_response_path"]).write_text(
        json.dumps(
            {
                "insights": [
                    {
                        "scope": "user_profile",
                        "key": "k",
                        "claim": "c",
                        "proposed_change": {"op": "set", "value": "v"},
                        "confidence": 0.6,
                        "evidence_ids": ["e1", "e2"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    # Session 2: opening Evol auto-resumes
    evol2 = Evol.from_config(config_path)
    # The init-time resume should have already consumed it, but test that
    # a manual call confirms idempotency.
    again = evol2.reflector.resume_pending()
    assert again == []
    new_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert new_state["status"] == "consumed"


# ───────────────────────── helpers ─────────────────────────


def _write_config(
    tmp_path: Path,
    *,
    anchors: list[dict] | None = None,
    llm_block: str = "",
) -> Path:
    p = tmp_path / "evol.config.yaml"
    body = "schema_version: 1\nproduct:\n  name: test-cli\n  version: 0.0.1\n"
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
