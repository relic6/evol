"""Unit tests for evol.recorder.jsonl_store."""

from __future__ import annotations

import threading
from pathlib import Path

from evol.recorder.jsonl_store import JsonlStore


def test_append_and_iter(tmp_path: Path) -> None:
    s = JsonlStore(tmp_path / "log.jsonl")
    s.append({"id": "a", "v": 1})
    s.append({"id": "b", "v": 2})

    out = list(s.iter_all())
    assert out == [{"id": "a", "v": 1}, {"id": "b", "v": 2}]


def test_count(tmp_path: Path) -> None:
    s = JsonlStore(tmp_path / "log.jsonl")
    assert s.count() == 0
    s.append({"id": "a"})
    s.append({"id": "b"})
    assert s.count() == 2


def test_find_by_id(tmp_path: Path) -> None:
    s = JsonlStore(tmp_path / "log.jsonl")
    s.append({"id": "x", "v": 1})
    s.append({"id": "y", "v": 2})

    assert s.find_by_id("y") == {"id": "y", "v": 2}
    assert s.find_by_id("missing") is None


def test_iter_skips_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "log.jsonl"
    p.write_text(
        '{"id": "a"}\n\n{"id": "b"}\n  \n',
        encoding="utf-8",
    )
    s = JsonlStore(p)
    assert list(s.iter_all()) == [{"id": "a"}, {"id": "b"}]


def test_iter_skips_malformed_lines(tmp_path: Path) -> None:
    p = tmp_path / "log.jsonl"
    p.write_text(
        '{"id": "a"}\nthis is not json\n{"id": "b"}\n',
        encoding="utf-8",
    )
    s = JsonlStore(p)
    out = list(s.iter_all())
    assert out == [{"id": "a"}, {"id": "b"}]


def test_concurrent_appends_serialize(tmp_path: Path) -> None:
    s = JsonlStore(tmp_path / "log.jsonl")
    barrier = threading.Barrier(8)

    def worker(i: int) -> None:
        barrier.wait()
        for j in range(5):
            s.append({"thread": i, "n": j})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    records = list(s.iter_all())
    assert len(records) == 40
    # Every record must be a complete dict (no torn lines).
    assert all(isinstance(r, dict) and "thread" in r and "n" in r for r in records)


def test_pre_rendered_line_must_end_with_newline(tmp_path: Path) -> None:
    s = JsonlStore(tmp_path / "log.jsonl")
    import pytest  # noqa: PLC0415

    from evol.errors import EvolStorageError  # noqa: PLC0415

    with pytest.raises(EvolStorageError):
        s.append({"id": "a"}, line='{"id":"a"}')  # missing \n
