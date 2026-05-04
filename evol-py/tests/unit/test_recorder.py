"""Unit tests for evol.recorder.recorder."""

from __future__ import annotations

from pathlib import Path

from evol.core.types import Signal
from evol.recorder import Recorder


def test_start_end_round_trip(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    rec.ensure_initialized()

    handle = rec.start_task("hello", task_kind="summarize")
    eid = rec.end_task(handle, "world")
    assert eid == handle.experience_id

    exps = list(rec.iter_experiences())
    assert len(exps) == 1
    exp = exps[0]
    assert exp.id == eid
    assert exp.status == "closed"
    assert exp.input == "hello"
    assert exp.output == "world"
    assert exp.task_kind == "summarize"


def test_start_without_end_yields_open(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    rec.ensure_initialized()
    rec.start_task("x")

    exps = list(rec.iter_experiences())
    assert len(exps) == 1
    assert exps[0].status == "open"
    assert exps[0].output is None


def test_feedback_attached_via_overlay(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    rec.ensure_initialized()
    h = rec.start_task("x")
    eid = rec.end_task(h, "y")

    rec.feedback(eid, Signal(type="kept", ts="2026-05-03T14:35:00.000Z"))
    rec.feedback(
        eid,
        {
            "type": "rated",
            "ts": "2026-05-03T14:36:00.000Z",
            "value": 5,
        },
    )

    exp = rec.find(eid)
    assert exp is not None
    assert len(exp.signals) == 2
    assert exp.signals[0].type == "kept"
    assert exp.signals[1].type == "rated"
    assert exp.signals[1].value == 5


def test_feedback_does_not_mutate_main_log(tmp_path: Path) -> None:
    """The main jsonl file MUST stay append-only — overlay records the change."""
    rec = Recorder(tmp_path)
    rec.ensure_initialized()
    h = rec.start_task("x")
    eid = rec.end_task(h, "y")

    main_before = (tmp_path / "experiences.jsonl").read_text(encoding="utf-8")
    rec.feedback(eid, Signal(type="kept", ts="2026-05-03T14:35:00.000Z"))
    main_after = (tmp_path / "experiences.jsonl").read_text(encoding="utf-8")

    assert main_before == main_after
    overlay = (tmp_path / "experiences.feedback.jsonl").read_text(encoding="utf-8")
    assert "kept" in overlay


def test_feedback_on_unknown_experience_silent(tmp_path: Path) -> None:
    """Feedback for an unknown experience id should not crash —
    iter_experiences just won't surface it."""
    rec = Recorder(tmp_path)
    rec.ensure_initialized()
    rec.feedback("exp_does_not_exist", Signal(type="kept", ts="2026-05-03T14:35:00.000Z"))
    assert rec.count() == 0


def test_orphan_detection(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    rec.ensure_initialized()

    h1 = rec.start_task("first")
    rec.end_task(h1, "ok")
    rec.start_task("orphan")  # never ends

    orphaned = rec.detect_orphans()
    assert len(orphaned) == 1

    exps = {e.id: e for e in rec.iter_experiences()}
    assert exps[h1.experience_id].status == "closed"
    assert exps[orphaned[0]].status == "orphaned"


def test_orphan_detection_idempotent(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    rec.ensure_initialized()
    rec.start_task("orphan")
    a = rec.detect_orphans()
    b = rec.detect_orphans()
    assert len(a) == 1
    assert b == []   # already marked


def test_count_reflects_unique_experiences(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    rec.ensure_initialized()
    for _ in range(10):
        h = rec.start_task("x")
        rec.end_task(h, "y")
    assert rec.count() == 10


def test_find_returns_none_when_missing(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    rec.ensure_initialized()
    assert rec.find("exp_unknown") is None


def test_main_log_is_canonical_jsonl(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    rec.ensure_initialized()
    h = rec.start_task("hi", task_kind="summarize")
    rec.end_task(h, "bye")

    raw = (tmp_path / "experiences.jsonl").read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln]
    assert len(lines) == 2
    # Canonical: no whitespace between separators
    for ln in lines:
        assert ": " not in ln
        assert ", " not in ln
    # First line should start with id field
    assert lines[0].startswith('{"id":')
