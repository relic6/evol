"""CTS · Anchor conformance.

Asserts that anchors are unbypassable, fail-safe, and properly recorded
in the audit trail (insights/<date>-*.md "Rejected" section).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evol import Evol
from evol.advisor import Advisor
from evol.config.schema import (
    AnchorConfig,
    Config,
    InspirationConfig,
    ProductConfig,
)
from evol.config.anchors import parse_anchors
from evol.core.types import Insight, ProposedChange
from evol.llm import MockLLMClient
from evol.reflector.filter import AnchorFilter


pytestmark = pytest.mark.conformance


# ─── filter behavior ───


def _ins(scope: str, key: str, claim: str) -> Insight:
    return Insight(
        id=f"ins_{key}",
        reflection_id="ref_test_aaaa",
        created_at="2026-05-03T20:00:00.000Z",
        scope=scope,  # type: ignore[arg-type]
        key=key,
        claim=claim,
        proposed_change=ProposedChange(op="set", value="v"),
        confidence=0.85,
        evidence_ids=["exp_1"],
    )


def _config_with_anchors(anchors: list[dict]) -> Config:
    return Config(
        product=ProductConfig(name="cts", version="0.0.1"),
        anchors=[AnchorConfig(**a) for a in anchors],
    )


def test_regex_anchor_blocks_match() -> None:
    cfg = _config_with_anchors(
        [{"description": "no fab", "kind": "regex", "rule": r"fabricat"}]
    )
    runtime = parse_anchors(cfg.anchors)
    f = AnchorFilter(anchors=runtime)
    out = f.filter(
        [
            _ins("user_profile", "good", "user prefers concise output"),
            _ins("user_profile", "bad", "we should fabricate plausible answers"),
        ]
    )
    assert {i.key for i in out.approved} == {"good"}
    assert {i.key for i in out.rejected} == {"bad"}


def test_invalid_regex_is_fail_safe_reject() -> None:
    """Per FLOWS §6.6: a malformed anchor regex MUST result in conflict=True."""
    cfg = _config_with_anchors(
        [{"description": "broken", "kind": "regex", "rule": r"[unclosed"}]
    )
    runtime = parse_anchors(cfg.anchors)
    f = AnchorFilter(anchors=runtime)
    out = f.filter([_ins("user_profile", "k", "anything")])
    assert len(out.rejected) == 1


def test_text_anchor_with_no_llm_fail_safe_rejects() -> None:
    """Per FLOWS §6.6: text/semantic anchors with no synchronous LLM
    available MUST be treated as conflicts."""
    cfg = _config_with_anchors(
        [{"description": "x", "kind": "text", "rule": "no political claims"}]
    )
    runtime = parse_anchors(cfg.anchors)
    f = AnchorFilter(anchors=runtime, llm=None)
    out = f.filter([_ins("user_profile", "k", "user prefers concise")])
    assert len(out.rejected) == 1


def test_text_anchor_unrecognised_verdict_fail_safe() -> None:
    """If the LLM returns a verdict that isn't PASS/REJECT, fail-safe REJECT."""
    cfg = _config_with_anchors(
        [{"description": "x", "kind": "text", "rule": "no political claims"}]
    )
    runtime = parse_anchors(cfg.anchors)
    llm = MockLLMClient(["i'm not sure"])
    f = AnchorFilter(anchors=runtime, llm=llm)
    out = f.filter([_ins("user_profile", "k", "x")])
    assert len(out.rejected) == 1


# ─── reflect-time enforcement ───


def test_anchor_violation_excluded_from_memory(tmp_path: Path) -> None:
    """An LLM-produced Insight that violates a regex anchor MUST NOT enter Memory."""
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\n"
        "product:\n  name: cts\n  version: 0.0.1\n"
        "anchors:\n"
        "  - description: no fab\n"
        "    kind: regex\n"
        "    rule: fabricat\n",
        encoding="utf-8",
    )
    evol = Evol.from_config(p)

    for i in range(3):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")

    fake = json.dumps(
        [
            {
                "scope": "user_profile",
                "key": "k_good",
                "claim": "user prefers concise",
                "proposed_change": {"op": "set", "value": "concise"},
                "confidence": 0.85,
                "evidence_ids": ["e1", "e2"],
            },
            {
                "scope": "user_profile",
                "key": "k_bad",
                "claim": "we should fabricate plausible answers",
                "proposed_change": {"op": "set", "value": "lie"},
                "confidence": 0.85,
                "evidence_ids": ["e3"],
            },
        ]
    )
    evol._llm = MockLLMClient([fake])  # noqa: SLF001
    result = evol.reflector.reflect()
    assert result.status == "completed"
    assert result.insights_applied == 1
    assert result.insights_rejected == 1

    mem = evol.memory_store.load("user_profile")
    keys = {e.key for e in mem.entries}
    assert "k_good" in keys
    assert "k_bad" not in keys


def test_anchor_rejection_recorded_in_audit_log(tmp_path: Path) -> None:
    """Rejected insights MUST appear in insights/<date>-<reflection_id>.md
    under a 'Rejected insights' section."""
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\n"
        "product:\n  name: cts\n  version: 0.0.1\n"
        "anchors:\n"
        "  - description: no fab\n"
        "    kind: regex\n"
        "    rule: fabricat\n",
        encoding="utf-8",
    )
    evol = Evol.from_config(p)

    for i in range(3):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")

    fake = json.dumps(
        [
            {
                "scope": "user_profile",
                "key": "k_bad",
                "claim": "we should fabricate plausible answers",
                "proposed_change": {"op": "set", "value": "lie"},
                "confidence": 0.85,
                "evidence_ids": ["e1"],
            }
        ]
    )
    evol._llm = MockLLMClient([fake])  # noqa: SLF001
    evol.reflector.reflect()

    md = next((evol.evol_dir / "insights").glob("*.md")).read_text(encoding="utf-8")
    assert "Rejected insights" in md
    assert "k_bad" in md
    assert "fabricat" in md or "anchor" in md.lower()


# ─── inspire-time enforcement ───


def test_inspire_anchor_blocks_violating_text(tmp_path: Path) -> None:
    """Inspire output that matches a regex anchor MUST be dropped silently
    (not recorded in inspiration_history)."""
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\n"
        "product:\n  name: cts\n  version: 0.0.1\n"
        "inspiration:\n  frequency: high\n  cooldown_hours: 0\n"
        "  max_per_day: 100\n"
        "anchors:\n"
        "  - description: no fab\n"
        "    kind: regex\n"
        "    rule: fabricat\n",
        encoding="utf-8",
    )
    evol = Evol.from_config(p)
    raw = json.dumps(
        {
            "kind": "pattern",
            "text": "we should fabricate plausible answers",
            "evidence_ids": ["e1"],
        }
    )
    evol._llm = MockLLMClient([raw])  # noqa: SLF001
    for i in range(12):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")
    assert evol.advisor.inspire() is None
    # Nothing recorded
    history_path = evol.evol_dir / "insights" / "inspiration_history.jsonl"
    if history_path.exists():
        text = history_path.read_text(encoding="utf-8")
        assert "fabricate" not in text


# ─── runtime API: anchors are not mutable ───


def test_no_runtime_api_to_mutate_anchors(tmp_path: Path) -> None:
    """CONTRACT §13 A-5: SDKs MUST NOT provide any API to mutate anchors at
    runtime. We assert that the public Evol facade has no such method."""
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts\n  version: 0.0.1\n",
        encoding="utf-8",
    )
    evol = Evol.from_config(p)

    forbidden = {"add_anchor", "remove_anchor", "set_anchors", "update_anchors"}
    public_methods = {a for a in dir(evol) if not a.startswith("_")}
    assert public_methods.isdisjoint(forbidden)
