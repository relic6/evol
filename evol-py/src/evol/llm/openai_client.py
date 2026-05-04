"""OpenAI direct backend (optional dependency).

Requires ``pip install evol-kit[openai]``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, cast

from evol.errors import EvolLLMError
from evol.llm.base import LLMBackendKind, LLMClient, LLMResponse, Message

if TYPE_CHECKING:  # pragma: no cover
    from openai import OpenAI


class OpenAIClient(LLMClient):
    backend_kind = LLMBackendKind.DIRECT
    is_synchronous = True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        model: str = "gpt-4o-mini",
    ) -> None:
        try:
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as e:  # pragma: no cover
            raise EvolLLMError(
                "the 'openai' package is required for the OpenAI backend; "
                "install it via `pip install evol-kit[openai]`"
            ) from e

        key = api_key or os.environ.get(api_key_env)
        if not key:
            raise EvolLLMError(
                f"no API key found: pass api_key=... or set {api_key_env}"
            )
        self._client: OpenAI = OpenAI(api_key=key)
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
        api_messages = [{"role": m.role, "content": m.content} for m in messages]
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=cast(Any, api_messages),
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
        except Exception as e:
            raise EvolLLMError(f"OpenAI call failed: {e}") from e

        choice = resp.choices[0] if getattr(resp, "choices", None) else None
        text = (choice.message.content or "").strip() if choice else ""
        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text=text,
            backend=LLMBackendKind.DIRECT,
            model=getattr(resp, "model", self.model),
            input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            finish_reason=getattr(choice, "finish_reason", None) if choice else None,
        )


__all__ = ["OpenAIClient"]
