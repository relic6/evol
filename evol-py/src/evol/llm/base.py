"""LLM client abstraction — three-backend unified interface.

The three backends:
  - **direct**     : EVOL holds API credentials and calls Anthropic / OpenAI.
  - **subprocess** : EVOL spawns a local CLI (claude / codex) as a subprocess.
  - **host**       : EVOL is loaded as a Skill in a host agent (Claude Code
                     etc.); LLM calls are deferred via the file protocol.

Direct + subprocess are synchronous → return :class:`LLMResponse`.
Host is asynchronous → returns :class:`DeferredLLMResponse`; the host agent
later writes the JSON response, which EVOL picks up via :meth:`LLMClient.poll`.

Callers MUST handle both return types. See FLOWS.md §3.5.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class LLMBackendKind(str, Enum):
    DIRECT = "direct"
    SUBPROCESS = "subprocess"
    HOST = "host"


class Message(BaseModel):
    """A single chat message in the role/content format."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str


class LLMResponse(BaseModel):
    """Synchronous response — text is immediately available."""

    model_config = ConfigDict(extra="allow")

    text: str
    backend: LLMBackendKind
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None


class DeferredLLMResponse(BaseModel):
    """Asynchronous response — only available after the host agent fulfills it."""

    model_config = ConfigDict(extra="allow")

    request_id: str
    backend: LLMBackendKind
    pending_path: Path
    expected_response_path: Path
    created_at: str
    expires_at: str | None = None
    purpose: Literal["reflection", "anchor_check", "inspiration"] = "reflection"


class LLMClient(ABC):
    """The single interface every backend implements."""

    @property
    @abstractmethod
    def backend_kind(self) -> LLMBackendKind: ...

    @property
    @abstractmethod
    def is_synchronous(self) -> bool: ...

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        *,
        purpose: str = "reflection",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 120.0,
    ) -> LLMResponse | DeferredLLMResponse: ...

    def poll(self, deferred: DeferredLLMResponse) -> LLMResponse | None:
        """Check if a deferred response is ready. Synchronous backends always
        return ``None`` here — they don't produce DeferredLLMResponses."""
        return None

    def estimate_tokens(self, text: str) -> int:
        """Cheap default. Subclasses can override with tiktoken-backed precision."""
        return max(1, len(text) // 4)


__all__ = [
    "DeferredLLMResponse",
    "LLMBackendKind",
    "LLMClient",
    "LLMResponse",
    "Message",
]
