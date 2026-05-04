"""Unit tests for evol.config."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from evol.config import (
    Config,
    compute_rule_hash,
    detect_anchor_drift,
    load_config,
    parse_anchors,
    write_runtime_copy,
)
from evol.config.schema import AnchorConfig
from evol.errors import EvolConfigError

# ─── load_config / schema validation ───


def test_load_minimal_config(tmp_path: Path, minimal_config_yaml: str) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(minimal_config_yaml, encoding="utf-8")
    config = load_config(p)
    assert config.product.name == "test-cli"
    assert config.product.version == "0.0.1"
    assert config.anchors == []
    assert config.growth.knowledge_evolution is True
    assert config.reflection.threshold == 20
    assert config.inspiration.frequency == "low"
    assert config.inspiration.host_strategy == "defer"
    assert config.llm.backend == "auto"
    assert config.llm.host is None


def test_load_full_config(tmp_path: Path) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        """
schema_version: 1
product:
  name: journal-cli
  version: 0.1.0
  domain: 个人日记总结
anchors:
  - description: 不杜撰
    kind: text
    rule: 总结必须忠实于原文,不杜撰
  - description: 同语言
    kind: text
    rule: 输出语言与输入保持一致
growth:
  knowledge_evolution: true
  inspirational_feedback: true
reflection:
  trigger: threshold
  threshold: 20
inspiration:
  frequency: medium
  cooldown_hours: 12
  host_strategy: template
llm:
  backend: direct
  direct:
    provider: anthropic
    model: claude-sonnet-4-6
""",
        encoding="utf-8",
    )
    config = load_config(p)
    assert config.product.domain == "个人日记总结"
    assert len(config.anchors) == 2
    assert config.anchors[0].rule.startswith("总结必须忠实")
    assert config.inspiration.host_strategy == "template"
    assert config.llm.backend == "direct"
    assert config.llm.direct is not None
    assert config.llm.direct.model == "claude-sonnet-4-6"


def test_load_host_anchor_text_strategy(tmp_path: Path) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(
        """
schema_version: 1
product:
  name: host-cli
  version: 0.1.0
llm:
  backend: host
  host:
    request_ttl_hours: 24
    anchor_text_strategy: allow
""",
        encoding="utf-8",
    )
    config = load_config(p)
    assert config.llm.host is not None
    assert config.llm.host.anchor_text_strategy == "allow"


def test_load_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(EvolConfigError, match="not found"):
        load_config(tmp_path / "absent.yaml")


def test_load_config_invalid_yaml(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("foo: : :\n", encoding="utf-8")
    with pytest.raises(EvolConfigError, match="invalid YAML"):
        load_config(p)


def test_load_config_top_level_must_be_mapping(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(EvolConfigError, match="mapping"):
        load_config(p)


def test_load_config_unknown_schema_version(tmp_path: Path) -> None:
    p = tmp_path / "wrong.yaml"
    p.write_text(
        "schema_version: 99\nproduct:\n  name: x\n  version: 1.0\n",
        encoding="utf-8",
    )
    with pytest.raises(EvolConfigError):
        load_config(p)


def test_load_config_invalid_product_name(tmp_path: Path) -> None:
    p = tmp_path / "bad-name.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: 'has spaces'\n  version: 1.0\n",
        encoding="utf-8",
    )
    with pytest.raises(EvolConfigError):
        load_config(p)


def test_load_config_extra_field_forbidden(tmp_path: Path) -> None:
    p = tmp_path / "extra.yaml"
    p.write_text(
        "schema_version: 1\nproduct:\n  name: x\n  version: 1.0\n  unknown: 'bad'\n",
        encoding="utf-8",
    )
    with pytest.raises(EvolConfigError):
        load_config(p)


# ─── write_runtime_copy ───


def test_write_runtime_copy_round_trip(tmp_path: Path, minimal_config_yaml: str) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(minimal_config_yaml, encoding="utf-8")
    config = load_config(p)

    evol_dir = tmp_path / ".evol"
    out = write_runtime_copy(config, evol_dir)
    assert out.exists()
    rehydrated = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert rehydrated["product"]["name"] == "test-cli"


def test_write_runtime_copy_creates_dir(tmp_path: Path, minimal_config_yaml: str) -> None:
    p = tmp_path / "evol.config.yaml"
    p.write_text(minimal_config_yaml, encoding="utf-8")
    config = load_config(p)

    evol_dir = tmp_path / "deep" / "nested" / ".evol"
    out = write_runtime_copy(config, evol_dir)
    assert out.exists()
    assert out.parent == evol_dir


# ─── anchors ───


def test_compute_rule_hash_stable() -> None:
    a = compute_rule_hash("不杜撰")
    b = compute_rule_hash("不杜撰")
    assert a == b
    assert a.startswith("sha256:")


def test_compute_rule_hash_strips_whitespace() -> None:
    a = compute_rule_hash("不杜撰")
    b = compute_rule_hash("  不杜撰  ")
    assert a == b


def test_compute_rule_hash_differs_on_content_change() -> None:
    a = compute_rule_hash("不杜撰")
    b = compute_rule_hash("不杜撰事实")
    assert a != b


def test_parse_anchors_basic() -> None:
    cfgs = [
        AnchorConfig(description="d1", kind="text", rule="r1"),
        AnchorConfig(description="d2", kind="regex", rule="^foo"),
    ]
    anchors = parse_anchors(cfgs, activated_at="2026-04-01T00:00:00.000Z")
    assert anchors[0].index == 0
    assert anchors[1].index == 1
    assert anchors[0].rule_hash == compute_rule_hash("r1")
    assert anchors[0].activated_at == "2026-04-01T00:00:00.000Z"


def test_detect_anchor_drift_no_change() -> None:
    cfgs = [AnchorConfig(description="d", kind="text", rule="rule")]
    a1 = parse_anchors(cfgs, activated_at="2026-04-01T00:00:00.000Z")
    a2 = parse_anchors(cfgs, activated_at="2026-05-01T00:00:00.000Z")
    # Different timestamps but same rule — no drift.
    assert detect_anchor_drift(a1, a2) == []


def test_detect_anchor_drift_rule_change() -> None:
    a1 = parse_anchors(
        [AnchorConfig(description="d", kind="text", rule="r1")],
        activated_at="2026-04-01T00:00:00.000Z",
    )
    a2 = parse_anchors(
        [AnchorConfig(description="d", kind="text", rule="r2")],
        activated_at="2026-04-01T00:00:00.000Z",
    )
    assert detect_anchor_drift(a1, a2) == [0]


def test_detect_anchor_drift_size_change() -> None:
    a1 = parse_anchors(
        [AnchorConfig(description="d", kind="text", rule="r1")],
        activated_at="2026-04-01T00:00:00.000Z",
    )
    a2 = parse_anchors(
        [
            AnchorConfig(description="d", kind="text", rule="r1"),
            AnchorConfig(description="d2", kind="text", rule="r2"),
        ],
        activated_at="2026-04-01T00:00:00.000Z",
    )
    # Index 1 in a2 has no counterpart in a1.
    assert detect_anchor_drift(a1, a2) == [1]


def test_config_round_trips_through_model_dump() -> None:
    """A loaded config should re-validate after model_dump → model_validate."""
    config = Config.model_validate(
        {
            "schema_version": 1,
            "product": {"name": "p", "version": "0.1"},
            "anchors": [{"description": "d", "kind": "text", "rule": "r"}],
        }
    )
    rehydrated = Config.model_validate(config.model_dump())
    assert rehydrated == config
