"""Inspire prompt building + response parsing.

The inspire prompt is **distinct** from the reflect prompt (FLOWS §5.4):
its goal is not to mine Insights but to surface **one** observation worth
sharing with the user. Quality over quantity.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from evol.core.types import Anchor, Experience, MemoryFile, MemoryKind
from evol.errors import EvolParseError
from evol.llm.base import Message

InspirationKind = Literal["pattern", "suggestion", "question", "insight", "none"]


class _InspireOutput(BaseModel):
    """Strict shape of a single inspire response."""

    model_config = ConfigDict(extra="ignore")

    kind: InspirationKind
    text: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


_SYSTEM_TEMPLATE = """\
You are an Evolution Inspirer.
Your job: based on accumulated user-specific Memory, offer ONE short
observation or suggestion the user has likely not yet considered.

Tone: gentle, curious, never preachy. Short — at most 80 characters
(or about 40 Chinese characters).

Anchors (you MUST honor):
{anchors_block}

You MUST output a JSON object:
  {{
    "kind": "pattern" | "suggestion" | "question" | "insight",
    "text": "<short string, ≤ 80 chars>",
    "evidence_ids": [<exp_id>, ...]
  }}

If nothing valuable to share, output:
  {{ "kind": "none", "text": null, "evidence_ids": [] }}

Quality over quantity. No prose, no markdown fences."""


_USER_TEMPLATE = """\
Active Memory (top entries):
{memory_block}

Recent Experiences (chronological):
{experiences_block}

Generate one inspiration if it would genuinely help the user. Otherwise,
return "none". Return only the JSON object."""


def build_inspire_prompt(
    *,
    anchors: list[Anchor],
    memory: dict[MemoryKind, MemoryFile],
    recent_experiences: list[Experience],
    domain: str | None = None,  # noqa: ARG001  (kept for symmetry; unused in v0.1)
    top_n: int = 6,
) -> list[Message]:
    """Render the system + user messages for an inspire LLM call."""
    return [
        Message(role="system", content=_system_text(anchors)),
        Message(role="user", content=_user_text(memory, recent_experiences, top_n=top_n)),
    ]


def _system_text(anchors: list[Anchor]) -> str:
    if anchors:
        block = "\n".join(f"  [{a.index}] {a.rule}" for a in anchors)
    else:
        block = "  (none)"
    return _SYSTEM_TEMPLATE.format(anchors_block=block)


def _user_text(
    memory: dict[MemoryKind, MemoryFile],
    experiences: list[Experience],
    *,
    top_n: int,
) -> str:
    return _USER_TEMPLATE.format(
        memory_block=_memory_block(memory, top_n=top_n),
        experiences_block=_experiences_block(experiences),
    )


def _memory_block(memory: dict[MemoryKind, MemoryFile], *, top_n: int) -> str:
    rows: list[tuple[float, str]] = []
    for kind in ("user_profile", "domain_knowledge", "self_awareness"):
        mf = memory.get(kind)  # type: ignore[arg-type]
        if mf is None:
            continue
        for e in mf.entries:
            if e.status != "active":
                continue
            rows.append(
                (
                    e.confidence,
                    f"  - [{kind}] {e.key}: {e.value} "
                    f"(confidence={e.confidence:.2f}, revisions={e.revision_count})",
                )
            )
    rows.sort(key=lambda t: t[0], reverse=True)
    selected = [r[1] for r in rows[:top_n]]
    return "\n".join(selected) if selected else "  (empty)"


def _experiences_block(experiences: list[Experience]) -> str:
    if not experiences:
        return "  (none)"
    chunks: list[str] = []
    for e in experiences[-5:]:
        signals = ", ".join(s.type for s in e.signals) or "—"
        chunks.append(
            f"  - {e.id} [{e.task_kind}, signals={signals}] "
            f"input={_truncate(_stringify(e.input), 80)} "
            f"output={_truncate(_stringify(e.output), 80)}"
        )
    return "\n".join(chunks)


def _stringify(v: Any) -> str:
    if v is None:
        return "—"
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# ─── parser ───


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def parse_inspiration(text: str) -> _InspireOutput | None:
    """Parse LLM output into an Inspiration. Returns None for ``kind=none``.

    Raises:
        EvolParseError if the text isn't recoverable JSON.
    """
    if not text or not text.strip():
        raise EvolParseError("empty inspiration output")

    body = text.strip()
    m = _CODE_FENCE_RE.match(body)
    if m:
        body = m.group(1).strip()

    # Tolerate prose before/after — find the first "{...}".
    if not body.startswith("{"):
        start = body.find("{")
        end = body.rfind("}")
        if start == -1 or end <= start:
            raise EvolParseError(f"no JSON object found in: {text[:120]!r}")
        body = body[start : end + 1]

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise EvolParseError(f"inspiration JSON invalid: {e}") from e

    if not isinstance(payload, dict):
        raise EvolParseError("inspiration must be a JSON object")

    try:
        out = _InspireOutput.model_validate(payload)
    except ValidationError as e:
        raise EvolParseError(f"inspiration schema invalid: {e}") from e

    if out.kind == "none":
        return None
    return out


__all__ = ["InspirationKind", "build_inspire_prompt", "parse_inspiration"]
