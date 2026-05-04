"""Unit tests for evol.llm.detector — auto-detect and explicit selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from evol.config.schema import (
    Config,
    LLMConfig,
    LLMDirectConfig,
    LLMHostConfig,
    LLMSubprocessConfig,
    ProductConfig,
)
from evol.errors import EvolConfigError
from evol.llm import (
    HostAgentClient,
    LLMBackendKind,
    SubprocessLLMClient,
    detect_backend,
)


def _config(llm: LLMConfig) -> Config:
    return Config(
        product=ProductConfig(name="test", version="0.1"),
        llm=llm,
    )


# ─── auto-detection ───


def test_auto_picks_host_when_host_agent_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("EVOL_BACKEND", raising=False)
    monkeypatch.setenv("EVOL_HOST_AGENT", "claude-code")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    client = detect_backend(_config(LLMConfig()), evol_root=tmp_path)
    assert isinstance(client, HostAgentClient)
    assert client.backend_kind == LLMBackendKind.HOST


def test_auto_picks_direct_when_anthropic_key(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("anthropic")
    monkeypatch.delenv("EVOL_BACKEND", raising=False)
    monkeypatch.delenv("EVOL_HOST_AGENT", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    client = detect_backend(_config(LLMConfig()), evol_root=tmp_path)
    assert client.backend_kind == LLMBackendKind.DIRECT


def test_auto_explicit_via_evol_backend_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVOL_BACKEND", "host")
    monkeypatch.delenv("EVOL_HOST_AGENT", raising=False)
    client = detect_backend(_config(LLMConfig()), evol_root=tmp_path)
    assert client.backend_kind == LLMBackendKind.HOST


def test_auto_fails_when_nothing_available(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("EVOL_BACKEND", raising=False)
    monkeypatch.delenv("EVOL_HOST_AGENT", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # No claude/codex on PATH inside the test env
    monkeypatch.setattr(
        "evol.llm.detector.shutil.which",
        lambda name: None,
    )
    with pytest.raises(EvolConfigError):
        detect_backend(_config(LLMConfig()), evol_root=tmp_path)


# ─── explicit selection ───


def test_explicit_host_backend(tmp_path: Path) -> None:
    cfg = _config(LLMConfig(backend="host", host=LLMHostConfig(request_ttl_hours=24)))
    client = detect_backend(cfg, evol_root=tmp_path)
    assert isinstance(client, HostAgentClient)
    assert client.ttl == 24


def test_explicit_subprocess_backend(tmp_path: Path) -> None:
    cfg = _config(
        LLMConfig(
            backend="subprocess",
            subprocess=LLMSubprocessConfig(
                command=["echo", "x"], timeout_seconds=5, format="text"
            ),
        )
    )
    client = detect_backend(cfg, evol_root=tmp_path)
    assert isinstance(client, SubprocessLLMClient)
    assert client.command == ["echo", "x"]


def test_explicit_direct_backend_missing_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = _config(
        LLMConfig(
            backend="direct",
            direct=LLMDirectConfig(provider="anthropic"),
        )
    )
    from evol.errors import EvolLLMError  # noqa: PLC0415

    with pytest.raises(EvolLLMError):
        detect_backend(cfg, evol_root=tmp_path)


def test_host_backend_requires_evol_root() -> None:
    cfg = _config(LLMConfig(backend="host"))
    with pytest.raises(EvolConfigError, match="evol_root"):
        detect_backend(cfg, evol_root=None)
