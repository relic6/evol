"""Anthropic Claude direct backend."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, cast

from evol.errors import EvolLLMError
from evol.llm.base import LLMBackendKind, LLMClient, LLMResponse, Message

if TYPE_CHECKING:  # pragma: no cover
    from anthropic import Anthropic


class AnthropicClient(LLMClient):
    backend_kind = LLMBackendKind.DIRECT
    is_synchronous = True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str = "ANTHROPIC_API_KEY",
        model: str = "claude-sonnet-4-6",
    ) -> None:
        try:
            from anthropic import Anthropic  # noqa: PLC0415
        except ImportError as e:  # pragma: no cover
            raise EvolLLMError(
                "the 'anthropic' package is required for the direct (Anthropic) backend; "
                "install it via `pip install anthropic`"
            ) from e

        key = api_key or os.environ.get(api_key_env)
        if not key:
            raise EvolLLMError(
                f"no API key found: pass api_key=... or set {api_key_env}"
            )
        self._client: Anthropic = Anthropic(api_key=key)
        self.model = model

    def chat(
        self,
        messages: list[Message],
        *,
        purpose: str = "reflection",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 120.0,
    ) -> LLMResponse:
        # Anthropic API takes ``system`` separately from messages.
        system_text = "\n\n".join(m.content for m in messages if m.role == "system")
        chat_msgs = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]
        try:
            kwargs: dict[str, object] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": chat_msgs,
                "timeout": timeout,
            }
            if system_text:
                kwargs["system"] = system_text
            resp = self._client.messages.create(**cast(Any, kwargs))
        except Exception as e:
            raise EvolLLMError(f"Anthropic call failed: {e}") from e

        text_parts = [
            getattr(block, "text", "")
            for block in getattr(resp, "content", [])
            if getattr(block, "type", None) == "text"
        ]
        text = "".join(text_parts).strip()
        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text=text,
            backend=LLMBackendKind.DIRECT,
            model=getattr(resp, "model", self.model),
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
            finish_reason=getattr(resp, "stop_reason", None),
        )


__all__ = ["AnthropicClient"]
