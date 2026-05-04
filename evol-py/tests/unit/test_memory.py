"""Unit tests for evol.memory: store, manifest, snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

from evol.core.types import MemoryEntry, MemoryFile
from evol.errors import EvolStorageError
from evol.memory import (
    ManifestStore,
    MemoryStore,
    SnapshotManager,
    build_initial_manifest,
    compute_checksum_from_memory,
)

# ─── MemoryStore ───


def test_memory_store_ensure_initialized_creates_three_files(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.ensure_initialized()
    assert (tmp_path / "memory" / "user_profile.yaml").exists()
    assert (tmp_path / "memory" / "domain_knowledge.yaml").exists()
    assert (tmp_path / "memory" / "self_awareness.yaml").exists()


def test_memory_store_ensure_initialized_idempotent(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.ensure_initialized()
    user = store.load("user_profile")

    # Mutate, save, then re-init: existing files MUST NOT be wiped.
    user.entries.append(_dummy_entry("k1"))
    store.save("user_profile", user)
    store.ensure_initialized()

    rehydrated = store.load("user_profile")
    assert len(rehydrated.entries) == 1


def test_memory_store_save_and_load_round_trip(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.ensure_initialized()

    mem = MemoryFile(
        memory_kind="user_profile",
        version=3,
        last_updated="2026-05-03T20:00:00.000Z",
        entries=[_dummy_entry("k1"), _dummy_entry("k2")],
    )
    store.save("user_profile", mem)

    rehydrated = store.load("user_profile")
    assert rehydrated.version == 3
    assert {e.key for e in rehydrated.entries} == {"k1", "k2"}


def test_memory_store_query(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.ensure_initialized()
    mem = MemoryFile(
        memory_kind="user_profile",
        version=1,
        last_updated="2026-05-03T20:00:00.000Z",
        entries=[_dummy_entry("a"), _dummy_entry("b")],
    )
    store.save("user_profile", mem)

    assert store.query("user_profile", "a") is not None
    assert store.query("user_profile", "missing") is None


def test_memory_store_save_rejects_kind_mismatch(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.ensure_initialized()
    mem = MemoryFile(
        memory_kind="user_profile",
        version=1,
        last_updated="2026-05-03T20:00:00.000Z",
    )
    with pytest.raises(EvolStorageError, match="kind mismatch"):
        store.save("domain_knowledge", mem)


def test_memory_store_drops_checksum_field_on_save(tmp_path: Path) -> None:
    """The on-disk file MUST NOT contain a stale checksum from in-memory state."""
    store = MemoryStore(tmp_path / "memory")
    store.ensure_initialized()
    mem = MemoryFile(
        memory_kind="user_profile",
        version=1,
        last_updated="2026-05-03T20:00:00.000Z",
        checksum="sha256:stale",
    )
    store.save("user_profile", mem)
    raw = (tmp_path / "memory" / "user_profile.yaml").read_text(encoding="utf-8")
    assert "stale" not in raw
    assert "checksum" not in raw


def test_memory_store_load_all(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.ensure_initialized()
    files = store.load_all()
    assert set(files.keys()) == {"user_profile", "domain_knowledge", "self_awareness"}


# ─── checksum helpers ───


def test_compute_checksum_deterministic(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.ensure_initialized()
    files = store.load_all()
    cs1 = compute_checksum_from_memory(files)
    cs2 = compute_checksum_from_memory(files)
    assert cs1 == cs2 and cs1.startswith("sha256:")


# ─── ManifestStore ───


def test_manifest_round_trip(tmp_path: Path) -> None:
    ms = ManifestStore(tmp_path / ".evol")
    m = build_initial_manifest(
        product_name="journal-cli",
        product_version="0.1.0",
        product_domain="diary",
    )
    ms.write(m)
    assert ms.exists()
    rehydrated = ms.read()
    assert rehydrated.product["name"] == "journal-cli"
    assert rehydrated.protocol_version == "0.1"
    assert rehydrated.memory["current_version"] == 0


def test_manifest_update_memory_pointer(tmp_path: Path) -> None:
    ms = ManifestStore(tmp_path / ".evol")
    m = build_initial_manifest(product_name="p", product_version="0.1.0")
    ms.write(m)
    updated = ms.update_memory_pointer(version=3, checksum="sha256:abc")
    assert updated.memory["current_version"] == 3
    assert updated.memory["checksum"] == "sha256:abc"
    assert ms.read().memory["current_version"] == 3


def test_manifest_update_experiences_and_reflection(tmp_path: Path) -> None:
    ms = ManifestStore(tmp_path / ".evol")
    ms.write(build_initial_manifest(product_name="p", product_version="0.1.0"))
    ms.update_experiences_pointer(count=42, last_id="exp_x", oldest_kept="exp_a")
    ms.update_last_reflection(reflection_id="ref_2026-05-03_a3f9")
    m = ms.read()
    assert m.experiences["count"] == 42
    assert m.experiences["last_id"] == "exp_x"
    assert m.last_reflection is not None
    assert m.last_reflection["id"] == "ref_2026-05-03_a3f9"


def test_manifest_read_missing_raises(tmp_path: Path) -> None:
    ms = ManifestStore(tmp_path / ".evol")
    with pytest.raises(EvolStorageError):
        ms.read()


# ─── SnapshotManager ───


def test_snapshot_create_and_list(tmp_path: Path) -> None:
    evol_dir = tmp_path / ".evol"
    memory_dir = evol_dir / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "user_profile.yaml").write_text("a: 1\n", encoding="utf-8")

    sm = SnapshotManager(evol_dir)
    sm.ensure_initialized()
    sm.create(0)
    sm.create(1)

    assert sm.list_versions() == [0, 1]
    assert sm.latest_version() == 1
    assert sm.has_version(0) and not sm.has_version(2)


def test_snapshot_create_refuses_overwrite(tmp_path: Path) -> None:
    evol_dir = tmp_path / ".evol"
    (evol_dir / "memory").mkdir(parents=True)
    (evol_dir / "memory" / "u.yaml").write_text("x", encoding="utf-8")

    sm = SnapshotManager(evol_dir)
    sm.ensure_initialized()
    sm.create(0)
    with pytest.raises(EvolStorageError, match="already exists"):
        sm.create(0)


def test_snapshot_rollback_restores_memory(tmp_path: Path) -> None:
    evol_dir = tmp_path / ".evol"
    memory_dir = evol_dir / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "user_profile.yaml").write_text("v: 1\n", encoding="utf-8")

    sm = SnapshotManager(evol_dir)
    sm.ensure_initialized()
    sm.create(0)

    # Mutate memory then rollback
    (memory_dir / "user_profile.yaml").write_text("v: 999\n", encoding="utf-8")
    sm.rollback_to(0)
    assert (memory_dir / "user_profile.yaml").read_text(encoding="utf-8") == "v: 1\n"


def test_snapshot_rollback_missing_version(tmp_path: Path) -> None:
    sm = SnapshotManager(tmp_path / ".evol")
    sm.ensure_initialized()
    with pytest.raises(EvolStorageError, match="not found"):
        sm.rollback_to(7)


def test_snapshot_prune_keeps_latest(tmp_path: Path) -> None:
    evol_dir = tmp_path / ".evol"
    (evol_dir / "memory").mkdir(parents=True)
    (evol_dir / "memory" / "u.yaml").write_text("x", encoding="utf-8")
    sm = SnapshotManager(evol_dir)
    sm.ensure_initialized()
    for v in range(5):
        sm.create(v)
    removed = sm.prune(keep=2)
    assert removed == [0, 1, 2]
    assert sm.list_versions() == [3, 4]


def test_snapshot_prune_no_op_when_few(tmp_path: Path) -> None:
    evol_dir = tmp_path / ".evol"
    (evol_dir / "memory").mkdir(parents=True)
    (evol_dir / "memory" / "u.yaml").write_text("x", encoding="utf-8")
    sm = SnapshotManager(evol_dir)
    sm.ensure_initialized()
    sm.create(0)
    assert sm.prune(keep=10) == []


def test_snapshot_prune_rejects_bad_keep(tmp_path: Path) -> None:
    sm = SnapshotManager(tmp_path / ".evol")
    sm.ensure_initialized()
    with pytest.raises(EvolStorageError):
        sm.prune(keep=0)


# ─── helpers ───


def _dummy_entry(key: str) -> MemoryEntry:
    return MemoryEntry(
        key=key,
        value="v",
        confidence=0.5,
        evidence_ids=["exp_1"],
        rationale="r",
        created_at="2026-04-01T00:00:00.000Z",
        last_validated_at="2026-04-01T00:00:00.000Z",
        last_revision_id="ins_x",
        revision_count=0,
    )
