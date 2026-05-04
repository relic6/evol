"""Subprocess LLM backend — pipe prompts to a local CLI.

Used when the user has ``claude`` or ``codex`` installed locally and prefers
to reuse those tools' credentials and model selection rather than have EVOL
hold its own keys. See LLM-BACKENDS §5.
"""

from __future__ import annotations

import os
import subprocess
from typing import Literal

from evol.errors import EvolLLMError
from evol.llm.base import LLMBackendKind, LLMClient, LLMResponse, Message


class SubprocessLLMClient(LLMClient):
    backend_kind = LLMBackendKind.SUBPROCESS
    is_synchronous = True

    def __init__(
        self,
        *,
        command: list[str],
        timeout_seconds: float = 180.0,
        format: Literal["text", "json"] = "text",
        env: dict[str, str] | None = None,
    ) -> None:
        if not command:
            raise EvolLLMError("SubprocessLLMClient: command must be non-empty")
        self.command = list(command)
        self.timeout = timeout_seconds
        self.format = format
        self._env = env or {}

    def chat(
        self,
        messages: list[Message],
        *,
        purpose: str = "reflection",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 120.0,
    ) -> LLMResponse:
        prompt_text = self._serialize_messages(messages)
        merged_env = os.environ.copy()
        merged_env.update(self._env)

        try:
            result = subprocess.run(
                self.command,
                input=prompt_text,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                env=merged_env,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise EvolLLMError(
                f"subprocess timed out after {e.timeout}s: {' '.join(self.command)}"
            ) from e
        except FileNotFoundError as e:
            raise EvolLLMError(
                f"subprocess command not found: {self.command[0]!r}"
            ) from e

        if result.returncode != 0:
            stderr_snippet = (result.stderr or "")[:400]
            raise EvolLLMError(
                f"subprocess exited with code {result.returncode}: {stderr_snippet}"
            )

        text = self._extract_text(result.stdout)
        return LLMResponse(
            text=text,
            backend=LLMBackendKind.SUBPROCESS,
            model=self.command[0],
            finish_reason="stop",
        )

    # ─── helpers ───

    @staticmethod
    def _serialize_messages(messages: list[Message]) -> str:
        parts: list[str] = []
        for m in messages:
            tag = m.role.upper()
            parts.append(f"<<{tag}>>\n{m.content}\n<<END_{tag}>>")
        return "\n".join(parts) + "\n"

    def _extract_text(self, stdout: str) -> str:
        if self.format == "json":
            import json  # noqa: PLC0415

            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError as e:
                raise EvolLLMError(f"subprocess JSON parse failed: {e}") from e
            if isinstance(payload, dict) and "text" in payload:
                return str(payload["text"]).strip()
            return json.dumps(payload, ensure_ascii=False)
        return stdout.strip()


__all__ = ["SubprocessLLMClient"]
