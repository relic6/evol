"""Advisor: enhance prompts + emit inspirations.

Public API (per CONTRACT §7):
  - :meth:`Advisor.enhance(prompt, task=None) -> str`
  - :meth:`Advisor.inspire(task=None) -> Inspiration | None`

Both **never raise** to the product. Internal failures degrade gracefully:
``enhance`` falls back to the original prompt; ``inspire`` returns None.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from evol.advisor.budget import BudgetManager
from evol.advisor.inspiration_history import InspirationHistory, InspirationRecord
from evol.advisor.inspire_prompt import (
    build_inspire_prompt,
    parse_inspiration,
)
from evol.advisor.retrieval import Candidate, Retrieval, derive_keys
from evol.config.schema import Config
from evol.core.ids import gen_deferred_request_id
from evol.core.time_utils import utc_now_iso
from evol.core.types import Anchor, Experience, MemoryEntry
from evol.errors import EvolError, EvolParseError
from evol.llm.base import (
    DeferredLLMResponse,
    LLMClient,
    LLMResponse,
)
from evol.logging import get_logger
from evol.memory import MemoryStore
from evol.recorder import Recorder

_log = get_logger("evol.advisor")

_FREQUENCY_PROBS: dict[str, float] = {
    "never": 0.0,
    "low": 0.15,
    "medium": 0.35,
    "high": 0.70,
}
_WARMUP_MIN_EXPERIENCES = 10
_INSPIRATION_TEXT_PREVIEW_CHARS = 80


class Inspiration(BaseModel):
    """Output of :meth:`Advisor.inspire`."""

    model_config = ConfigDict(extra="allow")

    text: str
    kind: Literal["pattern", "suggestion", "question", "insight"]
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.5


# ───────────────────────── advice rendering ─────────────────────────


_ADVICE_HEADER = "[Advice from EVOL · derived from prior interactions]"
_ADVICE_FOOTER = "[End advice]"


def render_candidate_line(cand: Candidate) -> str:
    """Render one Memory entry as one advice-block line.

    Used both for the visible block and (via BudgetManager) for token cost
    estimation, so the two stay in sync.
    """
    e = cand.entry
    return (
        f"- [{cand.kind} / {e.key}, conf {e.confidence:.2f}] {_value_str(e.value)}"
    )


def render_advice_block(candidates: list[Candidate]) -> str:
    if not candidates:
        return ""
    body_lines = [render_candidate_line(c) for c in candidates]
    # HTML-comment tracebacks (FLOWS §4.3.4) — invisible to the user but
    # parseable by tooling.
    trace_lines = [
        f"<!-- evol:advice ref=\"mem_{c.kind}#{c.entry.key}\" conf=\"{c.entry.confidence:.2f}\" -->"
        for c in candidates
    ]
    return (
        _ADVICE_HEADER
        + "\n"
        + "\n".join(body_lines)
        + "\n"
        + _ADVICE_FOOTER
        + "\n"
        + "\n".join(trace_lines)
    )


def _value_str(v: Any) -> str:
    if isinstance(v, str):
        return v
    if v is None:
        return "—"
    import json  # noqa: PLC0415

    return json.dumps(v, ensure_ascii=False)


def advice_ref(cand: Candidate) -> str:
    """Stable advice ref string used for ``Experience.advice_used``."""
    return f"mem_{cand.kind}#{cand.entry.key}"


# ───────────────────────── Advisor ─────────────────────────


class Advisor:
    """Memory → prompt + Memory → user inspirations.

    Construction is intentionally cheap: the heavy collaborators (memory
    store, anchors, history) are passed in. The :class:`evol.api.Evol`
    facade instantiates this lazily.
    """

    def __init__(
        self,
        *,
        config: Config,
        evol_root: str | Path,
        llm: LLMClient,
        anchors: list[Anchor],
        memory_store: MemoryStore,
        recorder: Recorder,
    ) -> None:
        self.config = config
        self.evol_root = Path(evol_root)
        self.llm = llm
        self.anchors = anchors
        self.memory_store = memory_store
        self.recorder = recorder

        self.retrieval = Retrieval()
        self.budget = BudgetManager(llm)
        self.history = InspirationHistory(self.evol_root)

    # ───────────────────────── enhance ─────────────────────────

    def enhance(self, prompt: str, *, task: dict[str, Any] | None = None) -> str:
        """Inject relevant Memory above the prompt. Never raises.

        If anything goes wrong (memory missing, retrieval crashes, budget
        cannot be computed), returns the original ``prompt`` unchanged.
        """
        try:
            keys = derive_keys(prompt, task)
            memory = self.memory_store.load_all()
            min_conf = max(0.0, _entry_min_confidence(self.config))
            ranked = self.retrieval.relevant_entries(
                memory, keys, task, min_confidence=min_conf
            )
            plan = self.budget.fit(prompt, ranked)
            if not plan.selected:
                return prompt
            block = render_advice_block(plan.selected)
            return f"{block}\n\n{prompt}"
        except EvolError as e:
            _log.warning("enhance failed", extra={"err": str(e)})
            return prompt
        except Exception as e:  # noqa: BLE001  — never bubble up
            _log.warning("enhance unexpected exception", extra={"err": str(e)})
            return prompt

    # ───────────────────────── inspire ─────────────────────────

    def inspire(self, *, task: dict[str, Any] | None = None) -> Inspiration | None:
        """Maybe surface an inspiration. Never raises. May return None."""
        try:
            return self._inspire_inner(task)
        except EvolError as e:
            _log.warning("inspire failed", extra={"err": str(e)})
            return None
        except Exception as e:  # noqa: BLE001
            _log.warning("inspire unexpected exception", extra={"err": str(e)})
            return None

    def _inspire_inner(self, task: dict[str, Any] | None) -> Inspiration | None:
        cfg = self.config.inspiration
        # ── gate 1: frequency ──
        if cfg.frequency == "never":
            return None
        # ── gate 2: cooldown ──
        if self.history.in_cooldown(hours=cfg.cooldown_hours):
            return None
        # ── gate 3: daily quota ──
        if self.history.count_today() >= cfg.max_per_day:
            return None
        # ── gate 4: warmup ──
        total_experiences = self.recorder.count()
        if total_experiences < _WARMUP_MIN_EXPERIENCES:
            return None

        # ── coin flip ──
        if not self._coin_flip(cfg.frequency, task=task):
            return None

        # ── host backend special handling ──
        if not self.llm.is_synchronous:
            return self._handle_host_backend(task)

        # ── direct / subprocess: full LLM-driven inspiration ──
        return self._inspire_via_llm(task)

    # ─── direct/subprocess path ───

    def _inspire_via_llm(self, task: dict[str, Any] | None) -> Inspiration | None:
        memory = self.memory_store.load_all()
        recent: list[Experience] = list(self.recorder.iter_experiences())[-10:]
        messages = build_inspire_prompt(
            anchors=self.anchors,
            memory=memory,
            recent_experiences=recent,
            domain=self.config.product.domain,
        )

        try:
            resp = self.llm.chat(
                messages,
                purpose="inspiration",
                max_tokens=256,
                temperature=0.5,
                timeout=30.0,
            )
        except EvolError as e:
            _log.warning("inspire LLM call failed", extra={"err": str(e)})
            return None

        # If somehow we got a deferred (shouldn't, given is_synchronous), bail.
        if not isinstance(resp, LLMResponse):
            return None

        try:
            out = parse_inspiration(resp.text)
        except EvolParseError as e:
            _log.warning("inspire parse failed", extra={"err": str(e)})
            return None
        if out is None:
            return None
        if not out.text or not out.evidence_ids:
            return None
        if self._anchor_violates(out.text):
            _log.info("inspire result rejected by anchor")
            return None

        inspiration = Inspiration(
            text=out.text,
            kind=out.kind if out.kind != "none" else "insight",  # type: ignore[arg-type]
            evidence_ids=list(out.evidence_ids),
        )
        self._record(inspiration)
        return inspiration

    # ─── host backend path ───

    def _handle_host_backend(
        self, task: dict[str, Any] | None
    ) -> Inspiration | None:
        strategy = self.config.inspiration.host_strategy
        if strategy == "disabled":
            return None
        if strategy == "template":
            return self._inspire_template_only()
        # default: defer
        return self._inspire_deferred(task)

    def _inspire_template_only(self) -> Inspiration | None:
        """Skip LLM entirely. Use the highest-confidence Memory entry to
        synthesize a soft, templated suggestion. Quiet by design."""
        memory = self.memory_store.load_all()
        best: tuple[float, MemoryEntry, str] | None = None
        for kind in ("user_profile", "domain_knowledge", "self_awareness"):
            mf = memory.get(kind)  # type: ignore[arg-type]
            if mf is None:
                continue
            for e in mf.entries:
                if e.status != "active":
                    continue
                if best is None or e.confidence > best[0]:
                    best = (e.confidence, e, kind)
        if best is None:
            return None

        _, entry, _ = best
        text = (
            f"Pattern noticed: {_value_str(entry.value)} "
            f"(rooted in {len(entry.evidence_ids)} past interactions)"
        )
        if len(text) > _INSPIRATION_TEXT_PREVIEW_CHARS:
            text = text[: _INSPIRATION_TEXT_PREVIEW_CHARS - 1] + "…"

        inspiration = Inspiration(
            text=text,
            kind="pattern",
            evidence_ids=list(entry.evidence_ids),
            confidence=entry.confidence,
        )
        if self._anchor_violates(inspiration.text):
            return None
        self._record(inspiration)
        return inspiration

    def _inspire_deferred(self, task: dict[str, Any] | None) -> Inspiration | None:
        """Write a pending inspiration request via the host LLM client.

        We **don't** persist a deferred-state file for inspirations (unlike
        reflections). Inspirations are low-stakes; if the host never answers,
        nothing is lost. The pending markdown stays under ``pending_requests/``
        until expiry.
        """
        memory = self.memory_store.load_all()
        recent = list(self.recorder.iter_experiences())[-10:]
        messages = build_inspire_prompt(
            anchors=self.anchors,
            memory=memory,
            recent_experiences=recent,
            domain=self.config.product.domain,
        )
        try:
            resp = self.llm.chat(
                messages,
                purpose="inspiration",
                max_tokens=256,
                temperature=0.5,
                timeout=30.0,
            )
        except EvolError as e:
            _log.warning("inspire deferred call failed", extra={"err": str(e)})
            return None
        # Host backend should return a DeferredLLMResponse — which means the
        # text isn't ready *yet*. Caller gets None this turn; the markdown
        # is on disk for the host to process.
        if isinstance(resp, DeferredLLMResponse):
            _log.info(
                "inspire deferred to host",
                extra={"request_id": resp.request_id},
            )
            return None
        # Defensive: if the host client somehow returned a sync response,
        # treat it as direct path.
        try:
            out = parse_inspiration(resp.text)
        except EvolParseError:
            return None
        if out is None or not out.text:
            return None
        if self._anchor_violates(out.text):
            return None
        inspiration = Inspiration(
            text=out.text,
            kind=out.kind if out.kind != "none" else "insight",  # type: ignore[arg-type]
            evidence_ids=list(out.evidence_ids),
        )
        self._record(inspiration)
        return inspiration

    # ─── helpers ───

    def _coin_flip(self, frequency: str, *, task: dict[str, Any] | None) -> bool:
        """Deterministic PRNG keyed on a stable surface so the same context
        always gives the same outcome (FLOWS §5.3)."""
        prob = _FREQUENCY_PROBS.get(frequency, 0.0)
        if prob >= 1.0:
            return True
        if prob <= 0.0:
            return False
        seed_material = "|".join(
            [
                str(self.recorder.count()),
                str(self.history.count_today()),
                str((task or {}).get("task_kind", "")),
            ]
        )
        digest = hashlib.sha256(seed_material.encode("utf-8")).digest()
        # Convert first 8 bytes to a value in [0, 1)
        roll = int.from_bytes(digest[:8], "big") / float(1 << 64)
        return roll < prob

    def _anchor_violates(self, text: str) -> bool:
        """Cheap regex-only check on inspirations (text/semantic anchors are
        expensive and inspirations are low-stakes — rejecting on regex match
        is the conservative fast path)."""
        import re  # noqa: PLC0415

        for a in self.anchors:
            if a.kind != "regex":
                continue
            try:
                if re.search(a.rule, text, flags=re.IGNORECASE):
                    return True
            except re.error:
                # Bad regex: fail-safe
                return True
        return False

    def _record(self, inspiration: Inspiration) -> None:
        record = InspirationRecord(
            id=gen_deferred_request_id("inspire").replace("req_", "ins_emit_"),
            ts=utc_now_iso(),
            kind=inspiration.kind,
            evidence_ids=list(inspiration.evidence_ids),
            text_preview=(
                inspiration.text[: _INSPIRATION_TEXT_PREVIEW_CHARS]
                if inspiration.text
                else None
            ),
        )
        try:
            self.history.record(record)
        except EvolError as e:
            _log.warning("inspiration history record failed", extra={"err": str(e)})


# ─── helpers (module level) ───


def _entry_min_confidence(config: Config) -> float:
    # Future: read from config.advisor.min_confidence. For v0.1, fixed default.
    return 0.30


__all__ = [
    "Advisor",
    "Inspiration",
    "advice_ref",
    "render_advice_block",
    "render_candidate_line",
]
