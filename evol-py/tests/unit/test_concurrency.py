"""Unit tests for evol.concurrency."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from evol.concurrency import (
    atomic_write_bytes,
    atomic_write_text,
    extract_snapshot_tar,
    file_lock,
    make_snapshot_tar,
)
from evol.errors import EvolLockError, EvolStorageError


# ─── atomic_write_text / bytes ───


def test_atomic_write_text_creates_file(tmp_path: Path) -> None:
    p = tmp_path / "out.txt"
    atomic_write_text(p, "hello")
    assert p.read_text(encoding="utf-8") == "hello"


def test_atomic_write_text_overwrites(tmp_path: Path) -> None:
    p = tmp_path / "out.txt"
    atomic_write_text(p, "first")
    atomic_write_text(p, "second")
    assert p.read_text(encoding="utf-8") == "second"


def test_atomic_write_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "deep" / "nested" / "out.txt"
    atomic_write_text(p, "hi")
    assert p.exists()


def test_atomic_write_bytes_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "blob.bin"
    payload = b"\x00\x01\x02 hello \xff"
    atomic_write_bytes(p, payload)
    assert p.read_bytes() == payload


def test_atomic_write_no_orphan_tmp_files(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    atomic_write_text(p, "x")
    siblings = sorted(q.name for q in tmp_path.iterdir())
    assert siblings == ["a.txt"]


# ─── file_lock ───


def test_file_lock_basic_acquire_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "test.lock"
    with file_lock(lock_path):
        # Inside the lock, file exists.
        assert lock_path.exists()


def test_file_lock_serializes_writers(tmp_path: Path) -> None:
    lock_path = tmp_path / "ser.lock"
    out_path = tmp_path / "out.txt"
    out_path.write_text("", encoding="utf-8")

    barrier = threading.Barrier(5)

    def worker(i: int) -> None:
        barrier.wait()
        with file_lock(lock_path, timeout=10.0):
            existing = out_path.read_text(encoding="utf-8")
            time.sleep(0.01)  # Encourage interleaving without the lock.
            out_path.write_text(existing + f"{i}\n", encoding="utf-8")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = sorted(out_path.read_text(encoding="utf-8").strip().split("\n"))
    assert lines == ["0", "1", "2", "3", "4"]


def test_file_lock_timeout_raises(tmp_path: Path) -> None:
    lock_path = tmp_path / "busy.lock"
    holder_started = threading.Event()
    release = threading.Event()

    def hold_forever() -> None:
        with file_lock(lock_path, timeout=10.0):
            holder_started.set()
            release.wait()

    holder = threading.Thread(target=hold_forever)
    holder.start()
    try:
        holder_started.wait(timeout=5.0)
        with pytest.raises(EvolLockError):
            with file_lock(lock_path, timeout=0.2):
                pass
    finally:
        release.set()
        holder.join()


# ─── snapshot tar ───


def test_make_snapshot_round_trip(tmp_path: Path) -> None:
    src = tmp_path / "memory"
    src.mkdir()
    (src / "user_profile.yaml").write_text("a: 1\n", encoding="utf-8")
    (src / "domain_knowledge.yaml").write_text("b: 2\n", encoding="utf-8")
    (src / "self_awareness.yaml").write_text("c: 3\n", encoding="utf-8")

    archive = tmp_path / "memory-v1.snapshot"
    make_snapshot_tar(src, archive)
    assert archive.exists()
    assert archive.stat().st_size > 0

    out = tmp_path / "restored"
    extract_snapshot_tar(archive, out)
    assert (out / "user_profile.yaml").read_text(encoding="utf-8") == "a: 1\n"
    assert (out / "domain_knowledge.yaml").read_text(encoding="utf-8") == "b: 2\n"
    assert (out / "self_awareness.yaml").read_text(encoding="utf-8") == "c: 3\n"


def test_make_snapshot_rejects_non_directory(tmp_path: Path) -> None:
    f = tmp_path / "not-a-dir.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(EvolStorageError):
        make_snapshot_tar(f, tmp_path / "out.snapshot")


def test_extract_snapshot_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(EvolStorageError):
        extract_snapshot_tar(tmp_path / "missing.snapshot", tmp_path / "out")


def test_snapshot_paths_are_relative(tmp_path: Path) -> None:
    """Snapshot must contain relative paths, not absolute prefixes."""
    src = tmp_path / "memory"
    src.mkdir()
    (src / "a.yaml").write_text("x: 1\n", encoding="utf-8")

    archive = tmp_path / "snap.tar.gz"
    make_snapshot_tar(src, archive)

    import tarfile

    with tarfile.open(archive, "r:gz") as tar:
        names = [m.name for m in tar.getmembers()]
    assert all(not n.startswith("/") for n in names), names
    assert any(n.endswith("a.yaml") for n in names)


# ─── posix-only sanity ───


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only test")
def test_atomic_write_uses_rename_semantics(tmp_path: Path) -> None:
    """atomic_write_text leaves only the target file (no .tmp orphans)."""
    p = tmp_path / "f.txt"
    atomic_write_text(p, "data")
    assert sorted(f.name for f in tmp_path.iterdir()) == ["f.txt"]
