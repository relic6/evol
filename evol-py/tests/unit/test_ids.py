"""Unit tests for evol.core.ids."""

from __future__ import annotations

import re

import pytest

from evol.core.ids import (
    gen_deferred_request_id,
    gen_experience_id,
    gen_insight_id,
    gen_reflection_id,
)


_EXP_RE = re.compile(r"^exp_\d{8}T\d{9}_[0-9a-f]{4}$")
_REF_RE = re.compile(r"^ref_\d{4}-\d{2}-\d{2}_[0-9a-f]{4}$")
_INS_RE = re.compile(r"^ins_\d{4}-\d{2}-\d{2}_\d{3}$")
_REQ_RE = re.compile(r"^req_\d{8}T\d{9}_[0-9a-f]{4}_[a-zA-Z0-9_]+$")


def test_experience_id_format() -> None:
    eid = gen_experience_id()
    assert _EXP_RE.match(eid), eid


def test_experience_id_uniqueness() -> None:
    ids = {gen_experience_id() for _ in range(50)}
    assert len(ids) == 50


def test_reflection_id_format() -> None:
    rid = gen_reflection_id()
    assert _REF_RE.match(rid), rid


def test_insight_id_seq_padded() -> None:
    rid = "ref_2026-05-03_a3f9"
    assert gen_insight_id(rid, 0) == "ins_2026-05-03_000"
    assert gen_insight_id(rid, 7) == "ins_2026-05-03_007"
    assert gen_insight_id(rid, 142) == "ins_2026-05-03_142"


def test_insight_id_rejects_invalid_reflection_id() -> None:
    with pytest.raises(ValueError):
        gen_insight_id("not-a-reflection", 0)


@pytest.mark.parametrize("seq", [-1, 1000])
def test_insight_id_rejects_out_of_range_seq(seq: int) -> None:
    with pytest.raises(ValueError):
        gen_insight_id("ref_2026-05-03_a3f9", seq)


def test_deferred_request_id_includes_purpose() -> None:
    rid = gen_deferred_request_id("reflection")
    assert _REQ_RE.match(rid), rid
    assert rid.endswith("_reflection")


def test_deferred_request_id_rejects_bad_purpose() -> None:
    with pytest.raises(ValueError):
        gen_deferred_request_id("")
    with pytest.raises(ValueError):
        gen_deferred_request_id("has space")
    with pytest.raises(ValueError):
        gen_deferred_request_id("has-dash")
