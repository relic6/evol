"""Auto-detect which LLM backend to use.

Order of precedence (CONTRACT §6 / LLM-BACKENDS §6.7):

1. ``EVOL_BACKEND`` environment variable (explicit override)
2. ``EVOL_HOST_AGENT`` env var → ``host`` backend
3. ``ANTHROPIC_API_KEY`` env var → direct (Anthropic)
4. ``OPENAI_API_KEY`` env var → direct (OpenAI)
5. ``which claude`` succeeds → subprocess
6. fail-fast (request explicit ``llm.backend`` config)

Explicit ``config.llm.backend`` ≠ "auto" always wins over auto-detection.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Literal, cast

from evol.config.schema import Config
from evol.errors import EvolConfigError
from evol.llm.base import LLMClient
from evol.logging import get_logger

_log = get_logger("evol.llm.detector")
_BackendName = Literal["direct", "subprocess", "host", "auto"]


def detect_backend(
    config: Config,
    *,
    evol_root: str | Path | None = None,
) -> LLMClient:
    """Resolve the configured (or auto-detected) LLM backend.

    Args:
        config: validated EVOL config.
        evol_root: required for ``host`` backend (so the client can locate
            ``pending_requests/`` and friends).

    Raises:
        EvolConfigError: if no backend can be determined or required state
            for the chosen backend is missing.
    """
    backend: _BackendName = config.llm.backend
    if backend == "auto":
        backend = _auto_detect()

    return _build(backend, config, evol_root)


def _auto_detect() -> _BackendName:
    explicit = os.environ.get("EVOL_BACKEND", "").strip().lower()
    if explicit in {"direct", "subprocess", "host"}:
        _log.info("backend chosen by EVOL_BACKEND env var", extra={"backend": explicit})
        return cast(_BackendName, explicit)

    host_marker = os.environ.get("EVOL_HOST_AGENT", "").strip().lower()
    if host_marker:
        _log.info("backend=host (EVOL_HOST_AGENT set)", extra={"host": host_marker})
        return "host"

    if os.environ.get("ANTHROPIC_API_KEY"):
        _log.info("backend=direct (ANTHROPIC_API_KEY found)")
        return "direct"
    if os.environ.get("OPENAI_API_KEY"):
        _log.info("backend=direct (OPENAI_API_KEY found)")
        return "direct"

    if shutil.which("claude") or shutil.which("codex"):
        _log.info("backend=subprocess (local CLI detected)")
        return "subprocess"

    raise EvolConfigError(
        "Cannot auto-detect LLM backend. Set llm.backend explicitly in "
        "evol.config.yaml, or provide one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, "
        "EVOL_HOST_AGENT, or install a local `claude` / `codex` CLI."
    )


def _build(backend: str, config: Config, evol_root: str | Path | None) -> LLMClient:
    if backend == "direct":
        return _build_direct(config)
    if backend == "subprocess":
        return _build_subprocess(config)
    if backend == "host":
        return _build_host(config, evol_root)
    raise EvolConfigError(f"unknown llm backend: {backend!r}")


def _build_direct(config: Config) -> LLMClient:
    direct = config.llm.direct
    provider = direct.provider if direct else "anthropic"
    if provider == "anthropic":
        from evol.llm.anthropic_client import AnthropicClient  # noqa: PLC0415

        return AnthropicClient(
            api_key_env=direct.api_key_env if direct else "ANTHROPIC_API_KEY",
            model=direct.model if direct else "claude-sonnet-4-6",
        )
    if provider == "openai":
        from evol.llm.openai_client import OpenAIClient  # noqa: PLC0415

        return OpenAIClient(
            api_key_env=direct.api_key_env if direct else "OPENAI_API_KEY",
            model=direct.model if direct else "gpt-4o-mini",
        )
    raise EvolConfigError(f"unknown direct provider: {provider!r}")


def _build_subprocess(config: Config) -> LLMClient:
    from evol.llm.subprocess_client import SubprocessLLMClient  # noqa: PLC0415

    sub = config.llm.subprocess
    if sub is None:
        # Auto-detect: prefer claude, fallback codex.
        if shutil.which("claude"):
            command = ["claude", "-p"]
        elif shutil.which("codex"):
            command = ["codex", "exec"]
        else:
            raise EvolConfigError(
                "subprocess backend selected but no `claude` or `codex` found and "
                "no llm.subprocess.command configured"
            )
        return SubprocessLLMClient(command=command)
    return SubprocessLLMClient(
        command=sub.command,
        timeout_seconds=sub.timeout_seconds,
        format=sub.format,
    )


def _build_host(config: Config, evol_root: str | Path | None) -> LLMClient:
    from evol.llm.host_client import HostAgentClient  # noqa: PLC0415

    if evol_root is None:
        raise EvolConfigError(
            "host backend requires evol_root; pass it via Evol or detect_backend(..., evol_root=...)"
        )
    host_cfg = config.llm.host
    return HostAgentClient(
        evol_root=evol_root,
        host_name=os.environ.get("EVOL_HOST_AGENT", "unknown"),
        request_ttl_hours=host_cfg.request_ttl_hours if host_cfg else 168,
    )


__all__ = ["detect_backend"]
