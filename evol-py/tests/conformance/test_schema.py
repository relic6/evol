"""CTS · Schema conformance.

Asserts every on-disk artifact a conformant SDK produces validates against
the DATA-MODEL.md schemas — and that the canonicalization rules from
DATA-MODEL §11 produce reproducible bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from evol import Evol
from evol.core.canonical import (
    canonical_jsonl_dump,
    canonical_yaml_dump,
    compute_memory_checksum,
)
from evol.core.types import (
    Experience,
    Manifest,
    MemoryFile,
    Signal,
)

pytestmark = pytest.mark.conformance


# ─── canonicalization is deterministic ───


def test_yaml_canonicalization_byte_stable() -> None:
    """Same logical content → same bytes, regardless of dict insertion order."""
    payload_a = {
        "schema_version": 1,
        "memory_kind": "user_profile",
        "version": 1,
        "last_updated": "2026-05-03T20:00:00.000Z",
        "entries": [],
    }
    payload_b = dict(reversed(list(payload_a.items())))
    assert canonical_yaml_dump(payload_a) == canonical_yaml_dump(payload_b)


def test_jsonl_canonicalization_byte_stable() -> None:
    a = {
        "id": "exp_1",
        "task_kind": "x",
        "status": "open",
        "started_at": "2026-05-03T14:30:00.000Z",
        "input": "hi",
    }
    b = dict(reversed(list(a.items())))
    assert canonical_jsonl_dump(a) == canonical_jsonl_dump(b)


def test_checksum_is_sha256_hex() -> None:
    files = {
        "user_profile": {
            "schema_version": 1, "memory_kind": "user_profile",
            "version": 0, "last_updated": "2026-05-03T20:00:00.000Z", "entries": [],
        },
        "domain_knowledge": {
            "schema_version": 1, "memory_kind": "domain_knowledge",
            "version": 0, "last_updated": "2026-05-03T20:00:00.000Z", "entries": [],
        },
        "self_awareness": {
            "schema_version": 1, "memory_kind": "self_awareness",
            "version": 0, "last_updated": "2026-05-03T20:00:00.000Z", "entries": [],
        },
    }
    cs = compute_memory_checksum(files)
    assert cs.startswith("sha256:")
    hex_part = cs.split(":", 1)[1]
    assert len(hex_part) == 64
    int(hex_part, 16)  # valid hex


# ─── on-disk produced by Evol bootstrap ───


@pytest.fixture()
def fresh_evol(tmp_path: Path) -> Evol:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: cts-test\n  version: 0.0.1\n",
        encoding="utf-8",
    )
    return Evol.from_config(p)


def test_manifest_validates(fresh_evol: Evol) -> None:
    manifest = fresh_evol.manifest_store.read()
    assert isinstance(manifest, Manifest)
    assert manifest.protocol_version == "0.1"
    assert "current_version" in manifest.memory
    assert "checksum" in manifest.memory


def test_each_memory_file_validates(fresh_evol: Evol) -> None:
    for kind in ("user_profile", "domain_knowledge", "self_awareness"):
        mf = fresh_evol.memory_store.load(kind)  # type: ignore[arg-type]
        assert isinstance(mf, MemoryFile)
        assert mf.memory_kind == kind


def test_experiences_jsonl_lines_validate_as_experience(fresh_evol: Evol) -> None:
    h = fresh_evol.recorder.start_task("hi", task_kind="cts")
    fresh_evol.recorder.end_task(h, "bye")

    text = (fresh_evol.evol_dir / "experiences.jsonl").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for line in lines:
        # Each line must parse as JSON and validate against Experience schema.
        d = json.loads(line)
        Experience.model_validate(d)


def test_feedback_overlay_records_have_required_fields(
    fresh_evol: Evol,
) -> None:
    h = fresh_evol.recorder.start_task("x")
    eid = fresh_evol.recorder.end_task(h, "y")
    fresh_evol.recorder.feedback(eid, Signal(type="kept", ts="2026-05-03T14:00:00.000Z"))

    text = (fresh_evol.evol_dir / "experiences.feedback.jsonl").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.strip())
    record = json.loads(line)
    assert "type" in record  # overlay record type
    assert "experience_id" in record
    assert "ts" in record


def test_canonical_jsonl_is_single_line_with_newline(fresh_evol: Evol) -> None:
    h = fresh_evol.recorder.start_task("x")
    fresh_evol.recorder.end_task(h, "y")
    raw = (fresh_evol.evol_dir / "experiences.jsonl").read_text(encoding="utf-8")
    for line in raw.splitlines():
        if line:
            # No nested newlines, no whitespace between separators
            assert ": " not in line
            assert ", " not in line


def test_memory_yaml_has_no_stale_checksum(fresh_evol: Evol) -> None:
    """Bootstrap MUST NOT leave a checksum field inside memory yaml."""
    raw = (fresh_evol.evol_dir / "memory" / "user_profile.yaml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    assert "checksum" not in parsed


def test_manifest_checksum_matches_disk(fresh_evol: Evol) -> None:
    """The manifest's recorded checksum must equal what we recompute from disk."""
    manifest = fresh_evol.manifest_store.read()
    files = fresh_evol.memory_store.load_all()
    actual = compute_memory_checksum(files)
    assert actual == manifest.memory["checksum"]


def test_canonicalization_uses_lf_only(fresh_evol: Evol) -> None:
    """No CRLF in any text artifact. (DATA-MODEL §11.1)"""
    targets = [
        fresh_evol.evol_dir / "manifest.yaml",
        fresh_evol.evol_dir / "memory" / "user_profile.yaml",
    ]
    for p in targets:
        raw = p.read_bytes()
        assert b"\r\n" not in raw, p


def test_protocol_version_field_present(fresh_evol: Evol) -> None:
    manifest = fresh_evol.manifest_store.read()
    assert manifest.protocol_version
    # Must match SemVer-ish "MAJOR.MINOR"
    parts = manifest.protocol_version.split(".")
    assert len(parts) == 2
    assert all(p.isdigit() for p in parts)


def test_floats_are_normalized_to_two_decimals() -> None:
    """confidence values written to disk should not exhibit FP-precision noise."""
    payload = {
        "schema_version": 1,
        "memory_kind": "user_profile",
        "version": 1,
        "last_updated": "2026-05-03T20:00:00.000Z",
        "entries": [
            {
                "key": "k",
                "value": "v",
                "confidence": 0.123456789,
                "evidence_ids": ["e1"],
                "rationale": "",
                "created_at": "2026-04-01T00:00:00.000Z",
                "last_validated_at": "2026-04-01T00:00:00.000Z",
                "last_revision_id": "ins_x",
                "revision_count": 0,
                "status": "active",
            }
        ],
    }
    out = canonical_yaml_dump(payload)
    parsed = yaml.safe_load(out)
    # Reading back the float must yield exactly the rounded value.
    assert parsed["entries"][0]["confidence"] == 0.12


def test_checksum_computation_documented_algorithm() -> None:
    """The published algorithm in DATA-MODEL §11.3 must produce the same hash
    as our implementation. This guards against future implementations
    drifting from the spec."""
    # Manual reimplementation of the spec — kinds in fixed order, joined by
    # the sentinel separator, then sha256.
    kinds = ("user_profile", "domain_knowledge", "self_awareness")
    files = {
        k: {
            "schema_version": 1, "memory_kind": k,
            "version": 0, "last_updated": "2026-05-03T20:00:00.000Z", "entries": [],
        }
        for k in kinds
    }
    expected_parts = []
    for k in kinds:
        body = {**files[k]}
        body.pop("checksum", None)
        expected_parts.append(canonical_yaml_dump(body))
    expected = "sha256:" + hashlib.sha256(
        "\n---\n".join(expected_parts).encode("utf-8")
    ).hexdigest()
    assert compute_memory_checksum(files) == expected
