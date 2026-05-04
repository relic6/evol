"""Pydantic schema for ``evol.config.yaml``.

This is the **input contract** for product authors. The on-disk config feeds
straight into these models, which then validate / fill defaults. CONTRACT §6
specifies the user-facing schema; this module is its executable form.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from evol.core.types import AnchorKind

_PRODUCT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


# ───────────────────────── product / anchors ─────────────────────────


class ProductConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    domain: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _PRODUCT_NAME_RE.match(v):
            raise ValueError(
                f"product.name must match {_PRODUCT_NAME_RE.pattern!r}, got {v!r}"
            )
        return v


class AnchorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    kind: AnchorKind = "text"
    rule: str

    @field_validator("rule")
    @classmethod
    def _non_empty_rule(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("anchor.rule must not be empty")
        return v


# ───────────────────────── growth / reflection / inspiration ─────────────────────────


class GrowthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_evolution: bool = True
    inspirational_feedback: bool = True


class ReflectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: Literal["manual", "threshold", "scheduled"] = "threshold"
    threshold: int = 20
    schedule: str | None = None
    max_experiences_per_run: int = 100


class InspirationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frequency: Literal["never", "low", "medium", "high"] = "low"
    cooldown_hours: int = 24
    max_per_day: int = 3
    host_strategy: Literal["defer", "template", "disabled"] = "defer"


# ───────────────────────── memory retention ─────────────────────────


class MemoryRetentionExperiences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_count: int = 10000
    max_days: int = 365


class MemoryRetentionSnapshots(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keep: int = 20


class MemoryRetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiences: MemoryRetentionExperiences = MemoryRetentionExperiences()
    snapshots: MemoryRetentionSnapshots = MemoryRetentionSnapshots()


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retention: MemoryRetentionConfig = MemoryRetentionConfig()


# ───────────────────────── llm backends ─────────────────────────


class LLMDirectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["anthropic", "openai"] = "anthropic"
    model: str = "claude-sonnet-4-6"
    api_key_env: str = "ANTHROPIC_API_KEY"


class LLMSubprocessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: list[str]
    timeout_seconds: int = 180
    format: Literal["text", "json"] = "text"


class LLMHostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_ttl_hours: int = 168
    purpose_whitelist: list[str] = Field(
        default_factory=lambda: ["reflection", "anchor_check", "inspiration"]
    )


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["direct", "subprocess", "host", "auto"] = "auto"
    direct: LLMDirectConfig | None = None
    subprocess: LLMSubprocessConfig | None = None
    host: LLMHostConfig | None = None


# ───────────────────────── top-level ─────────────────────────


class Config(BaseModel):
    """Top-level ``evol.config.yaml`` model.

    ``schema_version`` MUST be 1 in v0.1; loaders that encounter an unknown
    version fail fast (CONTRACT §3 / §6).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    product: ProductConfig
    anchors: list[AnchorConfig] = Field(default_factory=list)
    growth: GrowthConfig = GrowthConfig()
    reflection: ReflectionConfig = ReflectionConfig()
    inspiration: InspirationConfig = InspirationConfig()
    memory: MemoryConfig = MemoryConfig()
    llm: LLMConfig = LLMConfig()
    extensions: list[dict[str, object]] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError(
                f"unsupported schema_version: {v} (this SDK supports schema_version=1)"
            )
        return v

    @field_validator("anchors")
    @classmethod
    def _check_anchor_count(cls, v: list[AnchorConfig]) -> list[AnchorConfig]:
        # SHOULD: ≤ 16 anchors. We log via warnings module, not errors here,
        # to keep this loader resilient. The check is informational.
        if len(v) > 16:
            import warnings  # noqa: PLC0415

            warnings.warn(
                f"anchors count is {len(v)}; consider keeping it ≤ 16 "
                "(CONTRACT §6 SHOULD constraint).",
                stacklevel=2,
            )
        return v


__all__ = [
    "AnchorConfig",
    "Config",
    "GrowthConfig",
    "InspirationConfig",
    "LLMConfig",
    "LLMDirectConfig",
    "LLMHostConfig",
    "LLMSubprocessConfig",
    "MemoryConfig",
    "MemoryRetentionConfig",
    "MemoryRetentionExperiences",
    "MemoryRetentionSnapshots",
    "ProductConfig",
    "ReflectionConfig",
]
