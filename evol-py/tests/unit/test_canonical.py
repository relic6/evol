"""Unit tests for evol.core.canonical — the cross-SDK consistency layer.

These tests are the most important in Phase 1: any divergence here means
``evol-py`` and ``evol-ts`` / ``evol-java`` will compute different checksums
for the same logical Memory, breaking the multi-SDK promise.
"""

from __future__ import annotations

import json

import pytest
import yaml

from evol.core.canonical import (
    canonical_jsonl_dump,
    canonical_yaml_dump,
    compute_memory_checksum,
)


# ─── canonical_yaml_dump ───


def test_yaml_field_order_is_fixed() -> None:
    """Fields appear in the fixed protocol order even if the input dict has
    them in a different order."""
    payload = {
        "entries": [],
        "version": 7,
        "checksum": "sha256:abc",
        "schema_version": 1,
        "memory_kind": "user_profile",
        "last_updated": "2026-05-03T20:00:00.000Z",
    }
    out = canonical_yaml_dump(payload)
    # Read back and assert key order
    keys_in_output = [
        line.split(":", 1)[0]
        for line in out.splitlines()
        if line and not line.startswith(" ") and ":" in line
    ]
    expected = ["schema_version", "memory_kind", "version", "last_updated", "checksum", "entries"]
    assert keys_in_output[: len(expected)] == expected


def test_yaml_entry_field_order_is_fixed() -> None:
    payload = {
        "schema_version": 1,
        "memory_kind": "user_profile",
        "version": 1,
        "last_updated": "2026-05-03T20:00:00.000Z",
        "entries": [
            {
                "status": "active",
                "key": "summary_length",
                "rationale": "user prefers shorter",
                "value": "60-80",
                "confidence": 0.85,
                "evidence_ids": ["exp_1"],
                "created_at": "2026-04-01T00:00:00.000Z",
                "last_validated_at": "2026-05-03T20:00:00.000Z",
                "last_revision_id": "ins_2026-05-03_001",
                "revision_count": 2,
            }
        ],
    }
    out = canonical_yaml_dump(payload)
    parsed = yaml.safe_load(out)
    entry_keys = list(parsed["entries"][0].keys())
    expected = [
        "key",
        "value",
        "confidence",
        "evidence_ids",
        "rationale",
        "created_at",
        "last_validated_at",
        "last_revision_id",
        "revision_count",
        "status",
    ]
    assert entry_keys == expected


def test_yaml_floats_normalized_to_two_decimals() -> None:
    payload = {
        "schema_version": 1,
        "memory_kind": "user_profile",
        "version": 1,
        "last_updated": "2026-05-03T20:00:00.000Z",
        "entries": [
            {
                "key": "k",
                "value": "v",
                "confidence": 0.8500001,
                "evidence_ids": ["exp_1"],
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
    assert parsed["entries"][0]["confidence"] == 0.85


def test_yaml_unicode_preserved() -> None:
    payload = {
        "schema_version": 1,
        "memory_kind": "user_profile",
        "version": 1,
        "last_updated": "2026-05-03T20:00:00.000Z",
        "entries": [
            {
                "key": "tone",
                "value": "用户偏好简洁陈述句",
                "confidence": 0.75,
                "evidence_ids": ["exp_1"],
                "rationale": "中文",
                "created_at": "2026-04-01T00:00:00.000Z",
                "last_validated_at": "2026-04-01T00:00:00.000Z",
                "last_revision_id": "ins_x",
                "revision_count": 0,
                "status": "active",
            }
        ],
    }
    out = canonical_yaml_dump(payload)
    assert "用户偏好简洁陈述句" in out
    assert "\\u" not in out  # not escaped


# ─── canonical_jsonl_dump ───


def test_jsonl_one_line_with_trailing_newline() -> None:
    out = canonical_jsonl_dump(
        {
            "id": "exp_1",
            "task_kind": "summarize",
            "status": "open",
            "started_at": "2026-05-03T14:30:00.000Z",
            "input": "hello",
        }
    )
    assert out.endswith("\n")
    assert out.count("\n") == 1


def test_jsonl_field_order() -> None:
    payload = {
        "redacted": False,
        "metadata": {},
        "anchors_applied": [],
        "advice_used": [],
        "signals": [],
        "output": None,
        "input": "hi",
        "ended_at": None,
        "started_at": "2026-05-03T14:30:00.000Z",
        "status": "open",
        "task_kind": "summarize",
        "id": "exp_x",
    }
    out = canonical_jsonl_dump(payload)
    decoded = json.loads(out)
    keys = list(decoded.keys())
    expected_prefix = [
        "id",
        "task_kind",
        "status",
        "started_at",
        "ended_at",
        "input",
        "output",
        "signals",
        "advice_used",
        "anchors_applied",
        "metadata",
        "redacted",
    ]
    assert keys == expected_prefix


def test_jsonl_no_whitespace_between_separators() -> None:
    out = canonical_jsonl_dump(
        {
            "id": "exp_1",
            "task_kind": "summarize",
            "status": "open",
            "started_at": "2026-05-03T14:30:00.000Z",
            "input": "hi",
        }
    )
    # No `: ` or `, ` should appear (only `:` and `,`)
    assert ": " not in out
    assert ", " not in out


def test_jsonl_unicode_preserved() -> None:
    out = canonical_jsonl_dump(
        {
            "id": "exp_1",
            "task_kind": "summarize",
            "status": "open",
            "started_at": "2026-05-03T14:30:00.000Z",
            "input": "中文输入",
        }
    )
    assert "中文输入" in out
    assert "\\u" not in out


# ─── compute_memory_checksum ───


def _empty_memory(kind: str) -> dict:
    return {
        "schema_version": 1,
        "memory_kind": kind,
        "version": 1,
        "last_updated": "2026-05-03T20:00:00.000Z",
        "entries": [],
    }


def test_checksum_starts_with_sha256_prefix() -> None:
    files = {k: _empty_memory(k) for k in ("user_profile", "domain_knowledge", "self_awareness")}
    cs = compute_memory_checksum(files)
    assert cs.startswith("sha256:")
    assert len(cs) == len("sha256:") + 64


def test_checksum_is_deterministic() -> None:
    files = {k: _empty_memory(k) for k in ("user_profile", "domain_knowledge", "self_awareness")}
    a = compute_memory_checksum(files)
    b = compute_memory_checksum(files)
    assert a == b


def test_checksum_changes_on_meaningful_edit() -> None:
    base = {k: _empty_memory(k) for k in ("user_profile", "domain_knowledge", "self_awareness")}
    cs_before = compute_memory_checksum(base)

    edited = {k: _empty_memory(k) for k in ("user_profile", "domain_knowledge", "self_awareness")}
    edited["user_profile"]["entries"].append(
        {
            "key": "summary_length",
            "value": "60-80",
            "confidence": 0.85,
            "evidence_ids": ["exp_1"],
            "rationale": "",
            "created_at": "2026-04-01T00:00:00.000Z",
            "last_validated_at": "2026-04-01T00:00:00.000Z",
            "last_revision_id": "ins_x",
            "revision_count": 0,
            "status": "active",
        }
    )
    cs_after = compute_memory_checksum(edited)
    assert cs_before != cs_after


def test_checksum_independent_of_top_level_field_order() -> None:
    """Same content, different dict insertion order → same checksum."""
    a = {k: _empty_memory(k) for k in ("user_profile", "domain_knowledge", "self_awareness")}
    # Reverse order in input dicts (canonicalization should normalize)
    b = {
        "user_profile": dict(reversed(list(_empty_memory("user_profile").items()))),
        "domain_knowledge": dict(reversed(list(_empty_memory("domain_knowledge").items()))),
        "self_awareness": dict(reversed(list(_empty_memory("self_awareness").items()))),
    }
    assert compute_memory_checksum(a) == compute_memory_checksum(b)


def test_checksum_strips_existing_checksum_field() -> None:
    """A pre-existing checksum field in the input MUST NOT influence the result."""
    base = {k: _empty_memory(k) for k in ("user_profile", "domain_knowledge", "self_awareness")}
    base_with_cs = {
        k: {**v, "checksum": "sha256:fake"}
        for k, v in base.items()
    }
    assert compute_memory_checksum(base) == compute_memory_checksum(base_with_cs)


def test_checksum_treats_missing_kind_as_empty() -> None:
    files = {"user_profile": _empty_memory("user_profile")}
    cs1 = compute_memory_checksum(files)

    full = {k: _empty_memory(k) for k in ("user_profile", "domain_knowledge", "self_awareness")}
    cs2 = compute_memory_checksum(full)

    # Non-trivially different because empty-dict canonicalization produces
    # something different from a full empty memory_file.
    assert cs1 != cs2


@pytest.mark.parametrize(
    "kind", ["user_profile", "domain_knowledge", "self_awareness"]
)
def test_each_kind_round_trip_through_yaml(kind: str) -> None:
    payload = _empty_memory(kind)
    out = canonical_yaml_dump(payload)
    rehydrated = yaml.safe_load(out)
    assert rehydrated["memory_kind"] == kind
    assert rehydrated["entries"] == []
