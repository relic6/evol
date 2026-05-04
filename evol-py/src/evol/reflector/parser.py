"""Parse LLM output into structured Insight objects.

Tolerates common deviations:
  - Markdown code fences (```json ... ``` / ``` ... ```)
  - Wrapping object ``{"insights": [...]}`` (host backend convention)
  - Surrounding prose (we extract the first ``[...]`` array)

Anything that fails after these recoveries surfaces as :class:`EvolParseError`,
which the Reflector handles by retrying once or marking the run ``parse_failed``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from evol.core.ids import gen_insight_id
from evol.core.time_utils import utc_now_iso
from evol.core.types import Insight, ProposedChange
from evol.errors import EvolParseError

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = _CODE_FENCE_RE.match(text)
    return m.group(1).strip() if m else text


def _find_first_array(text: str) -> str | None:
    """Find a top-level JSON array substring inside ``text``.

    Used as a last-resort recovery when LLMs prepend prose like
    ``"Here are the insights:\n[ ... ]"``.
    """
    start = text.find("[")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _coerce_to_array(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("insights"), list):
        return payload["insights"]
    raise EvolParseError(
        f"expected a JSON array (or {{'insights': [...]}}), got {type(payload).__name__}"
    )


def parse_insights(text: str, *, reflection_id: str) -> list[Insight]:
    """Parse LLM output into a list of :class:`Insight`.

    Args:
        text: raw LLM output.
        reflection_id: parent reflection batch ID — used to mint child
            ``ins_*`` IDs.

    Raises:
        EvolParseError: when no recovery path yields a valid JSON array of
            insight-shaped objects.
    """
    if not text or not text.strip():
        raise EvolParseError("empty LLM output")

    body = _strip_code_fence(text)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        snippet = _find_first_array(body)
        if snippet is None:
            raise EvolParseError(
                f"could not extract JSON array from output: {body[:200]!r}"
            ) from None
        try:
            payload = json.loads(snippet)
        except json.JSONDecodeError as e:
            raise EvolParseError(f"recovered array still invalid JSON: {e}") from e

    raw_items = _coerce_to_array(payload)

    insights: list[Insight] = []
    now = utc_now_iso()
    for seq, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise EvolParseError(f"insight #{seq} is not a JSON object")

        prepared = _prepare_insight_dict(raw, reflection_id=reflection_id, seq=seq, now=now)

        try:
            insights.append(Insight.model_validate(prepared))
        except ValidationError as e:
            raise EvolParseError(f"insight #{seq} schema invalid: {e}") from e

    return insights


def _prepare_insight_dict(
    raw: dict[str, Any], *, reflection_id: str, seq: int, now: str
) -> dict[str, Any]:
    """Inject id / reflection_id / created_at and normalize proposed_change."""
    prepared = dict(raw)
    prepared.setdefault("id", gen_insight_id(reflection_id, seq))
    prepared["reflection_id"] = reflection_id
    prepared.setdefault("created_at", now)
    prepared.setdefault("status", "pending")

    pc = prepared.get("proposed_change")
    if isinstance(pc, dict):
        # Validate eagerly so a bad op surfaces as a parse error, not a
        # later ValidationError on Insight.
        try:
            ProposedChange.model_validate(pc)
        except ValidationError as e:
            raise EvolParseError(f"insight #{seq} proposed_change invalid: {e}") from e
    else:
        raise EvolParseError(f"insight #{seq} missing proposed_change object")

    if "evidence_ids" not in prepared or not isinstance(prepared["evidence_ids"], list):
        raise EvolParseError(f"insight #{seq} missing or non-list evidence_ids")

    return prepared


__all__ = ["parse_insights"]
