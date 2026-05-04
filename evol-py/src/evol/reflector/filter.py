"""AnchorFilter — post-process Insights to enforce value anchors.

Even though anchors are baked into the reflection prompt, we MUST re-check
them on the LLM's output (FLOWS §3.6). Three anchor kinds are supported:

  - ``regex``    — pure pattern match on ``Insight.claim``; no LLM needed
  - ``text``     — meta-prompt the LLM to evaluate "does this claim violate
                   this anchor?" (purely synchronous-only currently)
  - ``semantic`` — same as ``text`` for v0.1; future versions may distinguish

Fail-safe: any evaluation that itself fails (LLM error, malformed output)
results in ``conflict = True`` so the Insight is rejected. Better to drop a
borderline Insight than let a contradicting one through.

For host (deferred) backends, ``text`` / ``semantic`` anchors cannot be
evaluated synchronously without launching a second deferred call. v0.1
treats this as a conflict by default; products needing fine-grained
anchor checks under host backend should prefer ``regex`` anchors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from evol.core.types import Anchor, Insight, Rejection
from evol.errors import EvolError
from evol.llm.base import LLMClient, LLMResponse, Message
from evol.logging import get_logger

_log = get_logger("evol.reflector.filter")

_VERDICT_PASS = "pass"
_VERDICT_REJECT = "reject"
HostTextStrategy = Literal["fail_safe", "allow"]

_TEXT_ANCHOR_SYSTEM = """\
You are an EVOL Anchor Validator.
You will be given a single Insight claim and a single Anchor rule.
Your only job: decide whether the Insight CONTRADICTS the Anchor.

Output exactly one word: PASS or REJECT.
- PASS   = the Insight does NOT contradict the Anchor.
- REJECT = the Insight contradicts the Anchor.
No prose, no explanation, no formatting."""


@dataclass
class FilterOutcome:
    approved: list[Insight]
    rejected: list[Insight]


class AnchorFilter:
    """Filter a list of Insights against a list of Anchors."""

    def __init__(
        self,
        anchors: list[Anchor],
        *,
        llm: LLMClient | None = None,
        host_text_strategy: HostTextStrategy = "fail_safe",
    ) -> None:
        self.anchors = anchors
        self.llm = llm
        # ``fail_safe`` (default): host backend treats text/semantic as conflict.
        # ``allow``: assume PASS when the product explicitly accepts that risk.
        self.host_text_strategy = host_text_strategy

    def filter(self, insights: list[Insight]) -> FilterOutcome:
        approved: list[Insight] = []
        rejected: list[Insight] = []
        for ins in insights:
            verdict = self._evaluate(ins)
            if verdict is None:
                approved.append(ins.model_copy(update={"status": "pending"}))
            else:
                rejected.append(
                    ins.model_copy(
                        update={"status": "rejected", "rejection": verdict}
                    )
                )
        return FilterOutcome(approved=approved, rejected=rejected)

    # ─── core evaluation ───

    def _evaluate(self, ins: Insight) -> Rejection | None:
        for anchor in self.anchors:
            try:
                conflict = self._conflicts(ins, anchor)
            except EvolError as e:
                _log.warning(
                    "anchor evaluation error (fail-safe rejecting)",
                    extra={"insight_id": ins.id, "anchor_index": anchor.index, "err": str(e)},
                )
                conflict = True
            if conflict:
                return Rejection(
                    by_anchor=anchor.index,
                    rule=anchor.rule,
                    reason=f"Insight conflicts with anchor[{anchor.index}] (kind={anchor.kind})",
                )
        return None

    def _conflicts(self, ins: Insight, anchor: Anchor) -> bool:
        if anchor.kind == "regex":
            return self._regex_conflict(ins.claim, anchor.rule)
        if anchor.kind in {"text", "semantic"}:
            return self._llm_conflict(ins, anchor)
        # Unknown kind: fail-safe.
        return True

    def _regex_conflict(self, claim: str, pattern: str) -> bool:
        try:
            return re.search(pattern, claim, flags=re.IGNORECASE) is not None
        except re.error as e:
            _log.warning(
                "invalid anchor regex; treating as conflict",
                extra={"pattern": pattern, "err": str(e)},
            )
            return True

    def _llm_conflict(self, ins: Insight, anchor: Anchor) -> bool:
        if self.llm is None:
            return True
        if not self.llm.is_synchronous:
            return self._host_text_conflict(ins, anchor)

        messages = [
            Message(role="system", content=_TEXT_ANCHOR_SYSTEM),
            Message(
                role="user",
                content=f"Anchor rule:\n{anchor.rule}\n\nInsight claim:\n{ins.claim}",
            ),
        ]
        try:
            resp = self.llm.chat(messages, purpose="anchor_check", max_tokens=4, temperature=0.0)
        except EvolError as e:
            _log.warning(
                "anchor LLM check failed; fail-safe reject",
                extra={"insight_id": ins.id, "anchor_index": anchor.index, "err": str(e)},
            )
            return True

        if not isinstance(resp, LLMResponse):
            # Synchronous client returned a deferred? Treat as fail-safe reject.
            return True

        return self._verdict_conflict(resp, ins)

    def _verdict_conflict(self, resp: LLMResponse, ins: Insight) -> bool:
        verdict = resp.text.strip().lower()
        if verdict.startswith(_VERDICT_PASS):
            return False
        if verdict.startswith(_VERDICT_REJECT):
            return True
        # Unrecognized output — fail-safe reject.
        _log.warning(
            "anchor LLM check returned unrecognised verdict; fail-safe reject",
            extra={"insight_id": ins.id, "verdict": verdict[:80]},
        )
        return True

    def _host_text_conflict(self, ins: Insight, anchor: Anchor) -> bool:
        if self.host_text_strategy == "allow":
            return False
        _log.info(
            "host backend cannot synchronously evaluate text anchor — fail-safe reject",
            extra={"insight_id": ins.id, "anchor_index": anchor.index},
        )
        return True


__all__ = ["AnchorFilter", "FilterOutcome", "HostTextStrategy"]
