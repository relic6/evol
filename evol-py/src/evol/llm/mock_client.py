"""Test-only LLM client.

Allows tests to inject deterministic, prepared responses without ever
touching a network or a subprocess. Tests can either:

- Pass a list of strings: each call returns the next one.
- Pass a callable ``(messages, purpose) -> str``: full control.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from evol.errors import EvolLLMError
from evol.llm.base import LLMBackendKind, LLMClient, LLMResponse, Message


class MockLLMClient(LLMClient):
    backend_kind = LLMBackendKind.DIRECT
    is_synchronous = True

    def __init__(
        self,
        responses: list[str] | Callable[[list[Message], str], str] | None = None,
        *,
        model: str = "mock",
    ) -> None:
        self._queue: list[str] = list(responses) if isinstance(responses, list) else []
        self._fn: Callable[[list[Message], str], str] | None = (
            responses if callable(responses) else None
        )
        self.model = model
        self.calls: list[dict[str, Any]] = []  # for assertion in tests

    def chat(
        self,
        messages: list[Message],
        *,
        purpose: str = "reflection",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 120.0,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": [m.model_dump() for m in messages],
                "purpose": purpose,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if self._fn is not None:
            text = self._fn(messages, purpose)
        elif self._queue:
            text = self._queue.pop(0)
        else:
            raise EvolLLMError(
                "MockLLMClient: no more queued responses; "
                "supply more in the constructor or use a callable"
            )
        return LLMResponse(
            text=text,
            backend=LLMBackendKind.DIRECT,
            model=self.model,
            input_tokens=sum(self.estimate_tokens(m.content) for m in messages),
            output_tokens=self.estimate_tokens(text),
            finish_reason="stop",
        )


__all__ = ["MockLLMClient"]
