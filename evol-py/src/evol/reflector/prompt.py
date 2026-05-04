"""Reflection prompt builder.

Implements the three-section prompt template specified in FLOWS §3.4:

  - System: domain + memory kinds + anchors + JSON output schema
  - User:   current memory snapshot + experiences in chronological order
            + concrete instructions

Prompt content is intentionally explicit and conservative — we want LLMs
to lean on the structured schema rather than improvise.
"""

from __future__ import annotations

import json
from typing import Any

from evol.core.types import Anchor, Experience, MemoryFile, MemoryKind
from evol.llm.base import Message

_DOMAIN_FALLBACK = "general"
_MEMORY_KINDS: tuple[MemoryKind, ...] = (
    "user_profile",
    "domain_knowledge",
    "self_awareness",
)

_SYSTEM_TEMPLATE = """\
You are an Evolution Reflector.
Your job: examine a batch of past task interactions and produce structured
Insights about how the product can serve its user better.

Domain: {domain}

Memory kinds you can update:
  - user_profile      (preferences, habits, style)
  - domain_knowledge  (patterns, pitfalls, best practices)
  - self_awareness    (own strengths, weaknesses, error patterns)

You MUST respect the following anchors. If an Insight contradicts any anchor,
do NOT emit it.

Anchors:
{anchors_block}

You MUST output a JSON array of Insight objects. Each object has the shape:
  {{
    "scope": "user_profile" | "domain_knowledge" | "self_awareness",
    "key":   "<snake_case_identifier>",
    "claim": "<short natural-language claim>",
    "proposed_change": {{ "op": "set" | "merge" | "strengthen" | "weaken" | "retire", "value": <op-specific> }},
    "confidence": <float 0..1>,
    "evidence_ids": [<experience_id>, ...]
  }}

Return ONLY the JSON array. No prose, no markdown fences."""


_USER_TEMPLATE = """\
Existing Memory (current state):
{memory_block}

Recent Experiences (chronological):
{experiences_block}

Reflect on these Experiences. Produce Insights only when there is
sufficient evidence (≥ 2 supporting experiences SHOULD be the default;
single-experience Insights are allowed but should carry confidence ≤ 0.30).

Prefer "merge" or "strengthen" over "set" when an existing Memory entry
is partly correct.

Return only the JSON array. No prose."""


class PromptBuilder:
    """Render reflection prompts. Stateless — safe to share across reflections."""

    def __init__(self, *, max_input_chars: int = 1200) -> None:
        # Per-experience truncation cap for the user prompt; protects against
        # blowing the context window on a single huge input.
        self.max_input_chars = max_input_chars

    def build(
        self,
        *,
        domain: str | None,
        anchors: list[Anchor],
        memory: dict[MemoryKind, MemoryFile],
        experiences: list[Experience],
    ) -> list[Message]:
        return [
            Message(role="system", content=self._system_text(domain, anchors)),
            Message(role="user", content=self._user_text(memory, experiences)),
        ]

    # ─── system section ───

    def _system_text(self, domain: str | None, anchors: list[Anchor]) -> str:
        return _SYSTEM_TEMPLATE.format(
            domain=domain or _DOMAIN_FALLBACK,
            anchors_block=self._anchors_block(anchors),
        )

    def _anchors_block(self, anchors: list[Anchor]) -> str:
        if not anchors:
            return "  (none)"
        return "\n".join(f"  [{a.index}] {a.rule}" for a in anchors)

    # ─── user section ───

    def _user_text(
        self,
        memory: dict[MemoryKind, MemoryFile],
        experiences: list[Experience],
    ) -> str:
        return _USER_TEMPLATE.format(
            memory_block=self._memory_block(memory),
            experiences_block=self._experiences_block(experiences),
        )

    def _memory_block(self, memory: dict[MemoryKind, MemoryFile]) -> str:
        lines: list[str] = []
        for kind in _MEMORY_KINDS:
            mf = memory.get(kind)
            entries = mf.entries if mf else []
            lines.append(f"## {kind}")
            if not entries:
                lines.append("  (empty)")
                continue
            for e in entries:
                if e.status != "active":
                    continue
                lines.append(
                    f"  - {e.key}: {e.value} "
                    f"(confidence={e.confidence:.2f}, "
                    f"revisions={e.revision_count})"
                )
        return "\n".join(lines)

    def _experiences_block(self, experiences: list[Experience]) -> str:
        if not experiences:
            return "  (none)"
        chunks: list[str] = []
        for exp in experiences:
            chunks.append(self._format_experience(exp))
        return "\n\n".join(chunks)

    def _format_experience(self, exp: Experience) -> str:
        signals = ", ".join(self._format_signal(s) for s in exp.signals) or "—"
        input_text = self._stringify(exp.input)
        output_text = self._stringify(exp.output)
        return (
            f"id: {exp.id}\n"
            f"task_kind: {exp.task_kind}\n"
            f"status: {exp.status}\n"
            f"started_at: {exp.started_at}\n"
            f"input: {input_text}\n"
            f"output: {output_text}\n"
            f"signals: {signals}"
        )

    def _format_signal(self, s: Any) -> str:
        if s.value is None:
            return str(s.type)
        return f"{s.type}={s.value}"

    def _stringify(self, value: object) -> str:
        if value is None:
            return "—"
        text = value if isinstance(value, str) else str(json.dumps(value, ensure_ascii=False))
        if len(text) > self.max_input_chars:
            return text[: self.max_input_chars] + " …(truncated)"
        return text


__all__ = ["PromptBuilder"]
