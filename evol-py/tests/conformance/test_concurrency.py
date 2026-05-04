"""CTS · Concurrency conformance.

Asserts that file locks, atomic writes, and snapshot semantics survive
multi-writer scenarios — and that a residual / orphaned state from a
crashed previous session is recoverable.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from evol import Evol
from evol.concurrency import atomic_write_text, file_lock
from evol.core.types import Experience
from evol.errors import EvolLockError


pytestmark = pytest.mark.conformance


# ─── file lock serializes writers ───


def test_file_lock_serializes_concurrent_writers(tmp_path: Path) -> None:
    lock_path = tmp_path / "ser.lock"
    counter_path = tmp_path / "n.txt"
    counter_path.write_text("0", encoding="utf-8")

    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        with file_lock(lock_path, timeout=10.0):
            n = int(counter_path.read_text(encoding="utf-8"))
            counter_path.write_text(str(n + 1), encoding="utf-8")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert counter_path.read_text(encoding="utf-8") == "8"


def test_file_lock_timeout_raises(tmp_path: Path) -> None:
    lock_path = tmp_path / "busy.lock"
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with file_lock(lock_path, timeout=10.0):
            held.set()
            release.wait()

    t = threading.Thread(target=hold)
    t.start()
    try:
        held.wait(timeout=5.0)
        with pytest.raises(EvolLockError):
            with file_lock(lock_path, timeout=0.2):
                pass
    finally:
        release.set()
        t.join()


# ─── atomic write ───


def test_atomic_write_no_orphan_tmp_files(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    atomic_write_text(target, "ok")
    leftovers = sorted(p.name for p in tmp_path.iterdir())
    assert leftovers == ["f.txt"]


def test_atomic_write_replaces_existing(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    atomic_write_text(target, "first")
    atomic_write_text(target, "second")
    assert target.read_text(encoding="utf-8") == "second"


# ─── orphan recovery ───


def test_orphaned_experience_marked_on_next_start(tmp_path: Path) -> None:
    """Simulate a crashed session: start_task happens, end_task never does.
    On the next Evol.from_config(), the orphan MUST be marked."""
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts\n  version: 0.0.1\n",
        encoding="utf-8",
    )
    evol1 = Evol.from_config(p)
    evol1.recorder.start_task("never-finishes")
    # Pretend the process died here.

    evol2 = Evol.from_config(p)
    exps = list(evol2.recorder.iter_experiences())
    assert len(exps) == 1
    assert exps[0].status == "orphaned"


def test_orphan_detection_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts\n  version: 0.0.1\n",
        encoding="utf-8",
    )
    evol = Evol.from_config(p)
    evol.recorder.start_task("orphan-me")
    a = evol.recorder.detect_orphans()
    b = evol.recorder.detect_orphans()
    assert len(a) == 1
    assert b == []


# ─── concurrent appends ───


def test_concurrent_jsonl_appends_no_torn_lines(tmp_path: Path) -> None:
    """Multiple threads appending to experiences.jsonl must produce well-formed lines."""
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts\n  version: 0.0.1\n",
        encoding="utf-8",
    )
    evol = Evol.from_config(p)

    barrier = threading.Barrier(4)

    def worker(i: int) -> None:
        barrier.wait()
        for j in range(10):
            h = evol.recorder.start_task(f"in_{i}_{j}", task_kind="cts")
            evol.recorder.end_task(h, f"out_{i}_{j}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every line in the JSONL must be a valid Experience
    raw = (evol.evol_dir / "experiences.jsonl").read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    # 4 threads × 10 iterations × 2 lines (open + closed) = 80
    assert len(lines) == 80
    import json  # noqa: PLC0415

    for line in lines:
        Experience.model_validate(json.loads(line))


# ─── reflection lock ───


def test_reflection_lock_skips_when_busy(tmp_path: Path) -> None:
    """Two reflect() calls back to back: the second one MUST be 'skipped'
    if the first is still running. (We can't easily emulate concurrent
    long-running reflections in-process; we exercise the lock-busy path
    indirectly via a held lock.)"""
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts\n  version: 0.0.1\n",
        encoding="utf-8",
    )
    evol = Evol.from_config(p)
    for i in range(3):
        h = evol.recorder.start_task(f"x-{i}")
        evol.recorder.end_task(h, f"y-{i}")

    lock_path = evol.evol_dir / "locks" / "reflection.lock"

    # Grab the lock from another thread & hold it.
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with file_lock(lock_path, timeout=10.0):
            held.set()
            release.wait()

    t = threading.Thread(target=hold)
    t.start()
    try:
        held.wait(timeout=5.0)
        result = evol.reflector.reflect()
        assert result.status == "skipped"
    finally:
        release.set()
        t.join()
