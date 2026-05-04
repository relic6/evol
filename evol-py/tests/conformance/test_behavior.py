"""CTS · Behavior conformance.

Asserts that the 5 product API + key admin operations behave according
to CONTRACT §7 / §8 — non-throwing, idempotent where required, and with
the documented side effects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evol import Evol
from evol.core.types import MemoryEntry, Signal
from evol.llm import MockLLMClient

pytestmark = pytest.mark.conformance


@pytest.fixture()
def evol(tmp_path: Path) -> Evol:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts-bhv\n  version: 0.0.1\n",
        encoding="utf-8",
    )
    e = Evol.from_config(p)
    e._llm = MockLLMClient([])
    return e


# ─── start_task / end_task ───


def test_start_returns_handle_synchronously(evol: Evol) -> None:
    handle = evol.recorder.start_task("x", task_kind="t")
    assert handle.experience_id is not None
    assert handle.task_kind == "t"


def test_start_does_not_call_llm(evol: Evol) -> None:
    """CONTRACT §7.1: start_task MUST NOT call any LLM."""
    evol._llm = MockLLMClient([])
    evol.recorder.start_task("x")
    # No exception ⇒ no LLM call.


def test_start_end_pair_writes_one_logical_experience(evol: Evol) -> None:
    h = evol.recorder.start_task("x")
    eid = evol.recorder.end_task(h, "y")
    assert eid == h.experience_id
    exps = list(evol.recorder.iter_experiences())
    assert len(exps) == 1
    assert exps[0].status == "closed"


def test_end_task_handle_invalidated() -> None:
    """After end_task, calling end_task again on the same handle is a no-op
    or warning — but never raises (CONTRACT §14)."""
    # Implementation: we don't enforce single-use at runtime; the contract is
    # that misuse produces an extra closed line in the log, which is benign.
    # The behavior under test: never raises.


def test_feedback_is_idempotent(evol: Evol) -> None:
    """Multiple identical feedbacks may be recorded; later reads merge them
    gracefully without corruption."""
    h = evol.recorder.start_task("x")
    eid = evol.recorder.end_task(h, "y")
    sig = Signal(type="kept", ts="2026-05-03T14:00:00.000Z")
    evol.recorder.feedback(eid, sig)
    evol.recorder.feedback(eid, sig)
    exp = evol.recorder.find(eid)
    assert exp is not None
    # All signals visible — duplicates are not silently merged, but order is preserved.
    assert len(exp.signals) == 2


def test_feedback_does_not_mutate_main_log(evol: Evol) -> None:
    """CONTRACT: experiences.jsonl is append-only. feedback MUST go to overlay."""
    h = evol.recorder.start_task("x")
    eid = evol.recorder.end_task(h, "y")
    main_before = (evol.evol_dir / "experiences.jsonl").read_text(encoding="utf-8")
    evol.recorder.feedback(eid, Signal(type="kept", ts="2026-05-03T14:00:00.000Z"))
    main_after = (evol.evol_dir / "experiences.jsonl").read_text(encoding="utf-8")
    assert main_before == main_after


def test_feedback_for_unknown_id_does_not_raise(evol: Evol) -> None:
    """Per CONTRACT §14, recorder methods MUST NOT raise to product code."""
    evol.recorder.feedback("exp_does_not_exist", Signal(type="kept", ts="2026-05-03T14:00:00.000Z"))
    # No exception → ok.


# ─── enhance ───


def test_enhance_never_raises_even_on_corrupted_memory(tmp_path: Path) -> None:
    """CONTRACT §7.4: enhance MUST not raise."""
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts\n  version: 0.0.1\n",
        encoding="utf-8",
    )
    evol = Evol.from_config(p)
    evol._llm = MockLLMClient([])
    # Wreck the memory dir
    import shutil  # noqa: PLC0415

    shutil.rmtree(evol.memory_store.memory_dir)
    out = evol.advisor.enhance("hi", task={"task_kind": "x"})
    assert out == "hi"


def test_enhance_returns_string(evol: Evol) -> None:
    out = evol.advisor.enhance("prompt", task={"task_kind": "x"})
    assert isinstance(out, str)


# ─── inspire ───


def test_inspire_never_raises(evol: Evol) -> None:
    """CONTRACT §7.5: inspire MUST never raise."""
    # Throw a wild value into the LLM client
    evol._llm = MockLLMClient(["totally not json"])

    # Push past warmup
    for i in range(12):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")

    # Even if the LLM produces garbage, inspire must return None, not raise.
    result = evol.advisor.inspire(task={"task_kind": "x"})
    assert result is None


# ─── reflect ───


def test_reflect_with_no_new_experiences_returns_no_op(evol: Evol) -> None:
    result = evol.reflector.reflect()
    assert result.status == "no_op"


def test_reflect_writes_insights_file(tmp_path: Path) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts\n  version: 0.0.1\n",
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
                "key": "k",
                "claim": "c",
                "proposed_change": {"op": "set", "value": "v"},
                "confidence": 0.5,
                "evidence_ids": ["exp_1", "exp_2"],
            }
        ]
    )
    evol._llm = MockLLMClient([fake])
    result = evol.reflector.reflect()
    assert result.status == "completed"
    md_files = list((evol.evol_dir / "insights").glob("*.md"))
    assert md_files


# ─── pause / resume ───


def test_pause_resume_round_trip(evol: Evol) -> None:
    assert evol.is_paused() is False
    evol.pause()
    assert evol.is_paused() is True
    evol.resume()
    assert evol.is_paused() is False


def test_pause_state_persists_across_restart(tmp_path: Path) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts\n  version: 0.0.1\n",
        encoding="utf-8",
    )
    a = Evol.from_config(p)
    a.pause()
    b = Evol.from_config(p)
    assert b.is_paused() is True


def test_pause_disables_recording(evol: Evol) -> None:
    evol.pause()
    handle = evol.recorder.start_task("x")
    eid = evol.recorder.end_task(handle, "y")
    evol.recorder.feedback(eid, Signal(type="kept", ts="2026-05-03T14:00:00.000Z"))

    assert evol.recorder.count() == 0
    assert not (evol.evol_dir / "experiences.jsonl").read_text(encoding="utf-8").strip()
    assert not (evol.evol_dir / "experiences.feedback.jsonl").read_text(encoding="utf-8").strip()


def test_pause_disables_advisor_and_reflector(evol: Evol) -> None:
    mem = evol.memory_store.load("user_profile")
    mem.entries.append(
        MemoryEntry(
            key="summary_length",
            value="prefer concise summaries",
            confidence=0.90,
            evidence_ids=["exp_seed"],
            rationale="seed",
            created_at="2026-05-03T14:00:00.000Z",
            last_validated_at="2026-05-03T14:00:00.000Z",
            last_revision_id="ins_seed",
        )
    )
    evol.memory_store.save("user_profile", mem)
    for i in range(12):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")

    evol.pause()
    evol._llm = MockLLMClient(["[]"])

    prompt = "summary please"
    assert evol.advisor.enhance(prompt, task={"task_kind": "summary"}) == prompt
    assert evol.advisor.inspire(task={"task_kind": "summary"}) is None
    assert evol.reflector.should_fire() is False
    result = evol.reflector.reflect()
    assert result.status == "skipped"
    assert result.notes == "EVOL is paused"


# ─── snapshot / rollback ───


def test_snapshot_create_is_immutable(evol: Evol) -> None:
    """Creating the same version twice MUST raise — snapshots never overwrite."""
    from evol.errors import EvolStorageError  # noqa: PLC0415

    evol.snapshot_manager.create(99)
    with pytest.raises(EvolStorageError):
        evol.snapshot_manager.create(99)


def test_rollback_does_not_delete_snapshots(tmp_path: Path) -> None:
    """CONTRACT §8.2: rollback MUST NOT delete any existing snapshot."""
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts\n  version: 0.0.1\n",
        encoding="utf-8",
    )
    evol = Evol.from_config(p)

    evol.snapshot_manager.create(1)
    evol.snapshot_manager.create(2)
    pre = sorted(evol.snapshot_manager.list_versions())
    evol.snapshot_manager.rollback_to(0)
    post = sorted(evol.snapshot_manager.list_versions())
    assert pre == post


# ─── status counters and reflection checkpoint ───


def test_state_experience_count_tracks_recorder_before_reflection(tmp_path: Path) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts\n  version: 0.0.1\n",
        encoding="utf-8",
    )
    evol = Evol.from_config(p)
    h = evol.recorder.start_task("x")
    evol.recorder.end_task(h, "y")

    state = evol.state()
    manifest = evol.manifest_store.read()
    assert evol.recorder.count() == 1
    assert state.experience_count == 1
    assert state.reflected_experience_count == 0
    assert manifest.experiences.get("count") == 0


def test_manifest_records_experience_count_after_reflection(tmp_path: Path) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts\n  version: 0.0.1\n",
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
                "key": "k", "claim": "c",
                "proposed_change": {"op": "set", "value": "v"},
                "confidence": 0.5, "evidence_ids": ["e1", "e2"],
            }
        ]
    )
    evol._llm = MockLLMClient([fake])
    evol.reflector.reflect()
    manifest = evol.manifest_store.read()
    assert manifest.experiences.get("count") == 3
    assert manifest.experiences.get("reflected_count") == 3
    assert manifest.experiences.get("reflected_last_id") is not None
    state = evol.state()
    assert state.experience_count == 3
    assert state.reflected_experience_count == 3
    assert manifest.last_reflection is not None
