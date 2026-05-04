"""Host Agent LLM backend — deferred RPC via the file protocol.

When EVOL is loaded as a Skill inside a host agent (Claude Code, Codex,
Cursor, ...), it has no LLM credentials of its own. Instead it writes a
human-and-agent-readable Markdown request file under
``.evol/pending_requests/`` and returns a :class:`DeferredLLMResponse`.

The host agent later processes that file (when the user runs
``/evol-reflect`` or asks it to) and writes the JSON answer to
``.evol/completed_responses/``. EVOL ``poll()`` (or ``Reflector.resume_pending``)
picks it up.

See LLM-BACKENDS §6 for the full design.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from evol._version import PROTOCOL_VERSION, __version__
from evol.concurrency import atomic_write_text
from evol.core.ids import gen_deferred_request_id
from evol.core.time_utils import add_hours, utc_now_iso
from evol.errors import EvolLLMError, EvolParseError
from evol.llm.base import (
    DeferredLLMResponse,
    LLMBackendKind,
    LLMClient,
    LLMResponse,
    Message,
)


# Schema text shown to host agents inside the markdown request, so they know
# what JSON shape we expect back. Indented inside a fenced code block.
_RESPONSE_SCHEMAS: dict[str, str] = {
    "reflection": """\
```json
{
  "insights": [
    {
      "scope": "user_profile|domain_knowledge|self_awareness",
      "key":   "<snake_case>",
      "claim": "<short claim>",
      "proposed_change": {"op": "set|merge|strengthen|weaken|retire", "value": ...},
      "confidence": 0.85,
      "evidence_ids": ["exp_..."]
    }
  ],
  "model": "<the model you used, optional>",
  "completed_at": "<ISO 8601, optional>"
}
```""",
    "inspiration": """\
```json
{
  "kind": "pattern|suggestion|question|insight",
  "text": "<= 80 chars",
  "evidence_ids": ["exp_..."]
}
```""",
    "anchor_check": """\
```json
{
  "verdict": "pass|reject",
  "reason": "<short explanation>"
}
```""",
}


class HostAgentClient(LLMClient):
    backend_kind = LLMBackendKind.HOST
    is_synchronous = False

    def __init__(
        self,
        *,
        evol_root: str | Path,
        host_name: str = "unknown",
        request_ttl_hours: int = 168,
    ) -> None:
        self.evol_root = Path(evol_root)
        self.pending_dir = self.evol_root / "pending_requests"
        self.completed_dir = self.evol_root / "completed_responses"
        self.processed_dir = self.completed_dir / "processed"
        self.host_name = host_name
        self.ttl = request_ttl_hours

    # ─── lifecycle ───

    def ensure_initialized(self) -> None:
        for d in (self.pending_dir, self.completed_dir, self.processed_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ─── chat (write deferred request) ───

    def chat(
        self,
        messages: list[Message],
        *,
        purpose: str = "reflection",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 120.0,
    ) -> DeferredLLMResponse:
        if purpose not in _RESPONSE_SCHEMAS:
            raise EvolLLMError(f"HostAgentClient: unknown purpose {purpose!r}")

        self.ensure_initialized()
        request_id = gen_deferred_request_id(purpose)
        pending_path = self.pending_dir / f"{request_id}.md"
        response_path = self.completed_dir / f"{request_id}.json"

        created_at = utc_now_iso()
        expires_at = add_hours(created_at, self.ttl)
        doc = self._render_request_doc(
            request_id=request_id,
            purpose=purpose,
            messages=messages,
            response_path=response_path,
            created_at=created_at,
            expires_at=expires_at,
        )
        atomic_write_text(pending_path, doc)

        return DeferredLLMResponse(
            request_id=request_id,
            backend=LLMBackendKind.HOST,
            pending_path=pending_path,
            expected_response_path=response_path,
            created_at=created_at,
            expires_at=expires_at,
            purpose=purpose if purpose in {"reflection", "anchor_check", "inspiration"}
            else "reflection",  # type: ignore[arg-type]
        )

    # ─── poll (read completed response) ───

    def poll(self, deferred: DeferredLLMResponse) -> LLMResponse | None:
        path = Path(deferred.expected_response_path)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise EvolParseError(
                f"host completed response not valid JSON ({path.name}): {e}"
            ) from e

        if isinstance(data, dict) and "text" in data:
            text = str(data["text"])
        else:
            # Reflection responses have shape {insights: [...]} — we serialize
            # the whole dict back to JSON so the parser can consume it.
            text = json.dumps(data, ensure_ascii=False)
        model = (
            data.get("model", self.host_name)
            if isinstance(data, dict)
            else self.host_name
        )
        return LLMResponse(
            text=text,
            backend=LLMBackendKind.HOST,
            model=str(model),
        )

    # ─── render the markdown request artifact ───

    def _render_request_doc(
        self,
        *,
        request_id: str,
        purpose: str,
        messages: list[Message],
        response_path: Path,
        created_at: str,
        expires_at: str,
    ) -> str:
        system_text = "\n\n".join(m.content for m in messages if m.role == "system")
        user_text = "\n\n".join(m.content for m in messages if m.role == "user")

        rel_path = self._rel(response_path)
        schema = _RESPONSE_SCHEMAS.get(purpose, "")
        purpose_label = _purpose_label(purpose)

        return _TEMPLATE.format(
            request_id=request_id,
            purpose=purpose,
            purpose_label=purpose_label,
            created_at=created_at,
            expires_at=expires_at,
            host=self.host_name,
            response_path=rel_path,
            system_text=system_text or "(no system prompt)",
            user_text=user_text or "(no user prompt)",
            schema=schema,
            evol_version=__version__,
            protocol_version=PROTOCOL_VERSION,
        )

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.evol_root.parent))
        except ValueError:
            return str(path)


def _purpose_label(purpose: str) -> str:
    mapping: dict[str, str] = {
        "reflection": "Reflection",
        "inspiration": "Inspiration",
        "anchor_check": "Anchor Check",
    }
    return mapping.get(purpose, purpose.title())


_TEMPLATE = """\
---
request_id: {request_id}
purpose: {purpose}
created_at: {created_at}
expires_at: {expires_at}
status: pending
host: {host}
expected_response_path: {response_path}
expected_response_format: json
---

# EVOL {purpose_label} Request

This file is a **deferred LLM request** generated by the EVOL framework
running inside a host agent (you, presumably).

## What you (the host agent) should do

1. Read the **System Prompt** and **User Prompt** sections below.
2. Treat them exactly as if they had been provided to you as a regular prompt
   — produce the requested output.
3. Write the output as a JSON file at the path listed in
   `expected_response_path` above.
4. The JSON MUST conform to the schema in **Expected Response Schema**.

If the user explicitly asks you to "process EVOL pending reflections" or runs
the `/evol-reflect` skill command, that's your trigger to handle this.
Otherwise, feel free to ask the user before proceeding.

---

## System Prompt

{system_text}

---

## User Prompt

{user_text}

---

## Expected Response Schema

The response file MUST be a JSON object with this shape:

{schema}

Save the JSON to: `{response_path}`

---

> Created by EVOL · framework_version={evol_version} · protocol_version={protocol_version}
"""


__all__ = ["HostAgentClient"]
