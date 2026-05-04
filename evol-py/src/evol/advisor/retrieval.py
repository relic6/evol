"""Memory retrieval — keyword + tag + recency. **No vector DB.**

FLOWS §4.3.1 specifies the v0.1 scoring formula. The whole point: stay
human-debuggable. If the relevance score for an entry looks wrong, the
developer should be able to trace exactly why by reading this file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from evol.core.time_utils import parse_iso, utc_now
from evol.core.types import MemoryEntry, MemoryFile, MemoryKind

_RECENCY_DAYS = 30
_KEYWORD_KEY_HIT = 3
_KEYWORD_VALUE_HIT = 1
_TASK_KIND_HIT = 2
_RECENCY_BOOST = 1
_WORD_RE = re.compile(r"[A-Za-z0-9_一-鿿]+")


@dataclass
class Candidate:
    score: float
    entry: MemoryEntry
    kind: MemoryKind


def derive_keys(prompt: str, ctx: dict[str, Any] | None = None) -> list[str]:
    """Extract candidate keywords from the prompt + ctx hints.

    Heuristic, deterministic, not LLM-driven. Combines:
      - tokens from ``ctx['task_kind']``
      - tokens from ``ctx['tags']`` (if list)
      - top 12 most-frequent multi-char tokens from the prompt itself

    Returned in priority order, deduplicated, lower-cased.
    """
    ctx = ctx or {}
    parts: list[str] = []

    task_kind = ctx.get("task_kind")
    if isinstance(task_kind, str):
        parts.append(task_kind)

    tags = ctx.get("tags")
    if isinstance(tags, list):
        parts.extend(str(t) for t in tags if t)

    # Tokenize prompt
    tokens = [m.group(0).lower() for m in _WORD_RE.finditer(prompt)]
    counts: dict[str, int] = {}
    for tok in tokens:
        if len(tok) <= 1:
            continue
        counts[tok] = counts.get(tok, 0) + 1
    top_prompt = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:12]
    parts.extend(t for t, _ in top_prompt)

    return _dedupe_lower([str(p) for p in parts if p])


class Retrieval:
    """Score Memory entries against a query."""

    def relevant_entries(
        self,
        memory: dict[MemoryKind, MemoryFile],
        keys: list[str],
        ctx: dict[str, Any] | None = None,
        *,
        min_confidence: float = 0.30,
    ) -> list[Candidate]:
        ctx = ctx or {}
        keys_lower = [k.lower() for k in keys]
        candidates: list[Candidate] = []
        for kind in ("user_profile", "domain_knowledge", "self_awareness"):
            mf = memory.get(kind)  # type: ignore[arg-type]
            if mf is None:
                continue
            for entry in mf.entries:
                if entry.status != "active":
                    continue
                if entry.confidence < min_confidence:
                    continue
                score = self._score(entry, keys_lower, ctx)
                if score > 0:
                    candidates.append(Candidate(score=score, entry=entry, kind=kind))
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    # ─── scoring ───

    def _score(
        self,
        entry: MemoryEntry,
        keys: list[str],
        ctx: dict[str, Any],
    ) -> float:
        base = 0.0
        key_lower = entry.key.lower()
        value_text = self._stringify(entry.value).lower()
        key_fragments = [f for f in key_lower.split("_") if f]

        for k in keys:
            if k in key_lower:
                base += _KEYWORD_KEY_HIT
            elif self._loose_key_match(key_fragments, k):
                base += _KEYWORD_KEY_HIT // 2
            if k in value_text:
                base += _KEYWORD_VALUE_HIT

        task_kind = ctx.get("task_kind")
        if task_kind and isinstance(task_kind, str):
            tk = task_kind.lower()
            if tk in key_lower:
                base += _TASK_KIND_HIT
            elif self._loose_key_match(key_fragments, tk):
                base += _TASK_KIND_HIT // 2

        # Recency only AMPLIFIES an already-relevant entry; it never creates
        # relevance from nothing. (Otherwise every fresh entry would surface
        # for every prompt.)
        if base <= 0:
            return 0.0
        if self._recent(entry):
            base += _RECENCY_BOOST

        return base * entry.confidence

    @staticmethod
    def _loose_key_match(key_fragments: list[str], query: str) -> bool:
        """Looser bidirectional match: shared 5+ char prefix or fragment substring.

        Catches cases where the user prompt says 'summarize' but the Memory
        key is 'summary_length' (different conjugations of the same root).
        """
        if not query or len(query) < 4:
            return False
        for frag in key_fragments:
            if len(frag) < 4:
                continue
            if frag in query or query in frag:
                return True
            common = min(len(frag), len(query), 5)
            if common >= 5 and frag[:common] == query[:common]:
                return True
        return False

    @staticmethod
    def _recent(entry: MemoryEntry) -> bool:
        try:
            last = parse_iso(entry.last_validated_at)
        except Exception:  # noqa: BLE001
            return False
        delta = utc_now() - last
        return delta.days <= _RECENCY_DAYS

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, str):
            return value
        if value is None:
            return ""
        try:
            import json  # noqa: PLC0415

            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)


def _dedupe_lower(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        low = it.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(low)
    return out


__all__ = ["Candidate", "Retrieval", "derive_keys"]
