"""End-to-end Phase 2 integration tests.

These exercise the full ``Evol`` facade as product code would: bootstrap a
fresh ``.evol/``, run a sequence of tasks, attach feedback, restart, verify
state survives, exercise pause/resume/snapshot/rollback.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evol import Evol
from evol.config import load_config
from evol.core.types import Signal


@pytest.mark.integration
def test_e2e_bootstrap_record_and_persist(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    evol = Evol.from_config(config_path)
    assert evol.evol_dir == tmp_path / ".evol"
    assert evol.evol_dir.is_dir()
    assert (evol.evol_dir / "manifest.yaml").is_file()
    assert (evol.evol_dir / "memory" / "user_profile.yaml").is_file()
    assert (evol.evol_dir / "versions" / "memory-v0.snapshot").is_file()

    # Run 5 tasks
    handles = []
    for i in range(5):
        h = evol.recorder.start_task(f"input-{i}", task_kind="summarize")
        handles.append(h)
    for i, h in enumerate(handles):
        evol.recorder.end_task(h, f"output-{i}")

    assert evol.recorder.count() == 5
    closed = list(evol.recorder.iter_experiences())
    assert all(e.status == "closed" for e in closed)
    assert [e.input for e in closed] == [f"input-{i}" for i in range(5)]


@pytest.mark.integration
def test_e2e_persistence_across_restarts(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    # Session 1
    evol1 = Evol.from_config(config_path)
    h = evol1.recorder.start_task("persistent")
    eid = evol1.recorder.end_task(h, "ok")
    evol1.recorder.feedback(
        eid,
        Signal(type="kept", ts="2026-05-03T14:35:00.000Z"),
    )

    # Session 2: re-open
    evol2 = Evol.from_config(config_path)
    state2 = evol2.state()
    assert state2.protocol_version == "0.1"
    assert state2.product_name == "test-cli"

    exp = evol2.recorder.find(eid)
    assert exp is not None
    assert exp.status == "closed"
    assert len(exp.signals) == 1
    assert exp.signals[0].type == "kept"


@pytest.mark.integration
def test_e2e_orphan_recovery_across_restart(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)

    evol1 = Evol.from_config(config_path)
    h_done = evol1.recorder.start_task("done")
    evol1.recorder.end_task(h_done, "ok")

    h_orphan = evol1.recorder.start_task("never-ends")
    # Session 1 ends without end_task on h_orphan

    # Session 2: orphan detection runs in __init__
    evol2 = Evol.from_config(config_path)
    exps = {e.id: e for e in evol2.recorder.iter_experiences()}
    assert exps[h_done.experience_id].status == "closed"
    assert exps[h_orphan.experience_id].status == "orphaned"


@pytest.mark.integration
def test_e2e_pause_resume(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)
    evol = Evol.from_config(config_path)
    assert not evol.is_paused()
    evol.pause()
    assert evol.is_paused()
    assert evol.state().paused is True

    # State persists across reload
    evol2 = Evol.from_config(config_path)
    assert evol2.is_paused()
    evol2.resume()
    assert not evol2.is_paused()


@pytest.mark.integration
def test_e2e_snapshot_rollback(tmp_path: Path) -> None:
    config_path = _write_minimal_config(tmp_path)
    evol = Evol.from_config(config_path)

    # v0 snapshot was taken at bootstrap. Mutate memory and snapshot v1.
    user = evol.memory_store.load("user_profile")
    from evol.core.types import MemoryEntry, MemoryFile  # noqa: PLC0415

    user = MemoryFile(
        memory_kind="user_profile",
        version=1,
        last_updated="2026-05-03T20:00:00.000Z",
        entries=[
            MemoryEntry(
                key="summary_length",
                value="60-80",
                confidence=0.85,
                evidence_ids=["exp_1"],
                rationale="r",
                created_at="2026-04-01T00:00:00.000Z",
                last_validated_at="2026-04-01T00:00:00.000Z",
                last_revision_id="ins_1",
            )
        ],
    )
    evol.memory_store.save("user_profile", user)
    evol.snapshot_manager.create(1)
    assert evol.snapshot_manager.list_versions() == [0, 1]

    # Rollback to v0 — Memory should be empty again.
    evol.snapshot_manager.rollback_to(0)
    restored = evol.memory_store.load("user_profile")
    assert restored.entries == []


@pytest.mark.integration
def test_e2e_anchor_drift_triggers_snapshot(tmp_path: Path) -> None:
    config_path = tmp_path / "evol.config.yaml"
    config_path.write_text(
        """
schema_version: 1
product:
  name: test-cli
  version: 0.0.1
anchors:
  - description: a1
    kind: text
    rule: rule-one
""",
        encoding="utf-8",
    )

    evol1 = Evol.from_config(config_path)
    assert evol1.snapshot_manager.list_versions() == [0]

    # Edit the anchor rule
    config_path.write_text(
        """
schema_version: 1
product:
  name: test-cli
  version: 0.0.1
anchors:
  - description: a1
    kind: text
    rule: rule-one-edited
""",
        encoding="utf-8",
    )

    evol2 = Evol.from_config(config_path)
    # Drift detection MUST take a forced snapshot
    assert evol2.snapshot_manager.list_versions() == [0, 1]


# ─── helpers ───


def _write_minimal_config(tmp_path: Path) -> Path:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: test-cli\n  version: 0.0.1\n",
        encoding="utf-8",
    )
    return p
