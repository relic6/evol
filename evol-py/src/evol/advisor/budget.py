"""Token budget management for the enhance flow.

FLOWS §4.3.2 caps the advice block at ``min(max_advice_tokens, ratio * tokens(prompt))``.
This module is intentionally cheap: the LLM client supplies token estimates
(it might use tiktoken if available), and we just iterate candidates by score
and accept until full.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from evol.advisor.retrieval import Candidate
from evol.llm.base import LLMClient


_DEFAULT_MAX_TOKENS = 600
_DEFAULT_RATIO = 0.30
_MIN_BUDGET = 60   # always allow at least a tiny block, even on tiny prompts


@dataclass
class BudgetPlan:
    selected: list[Candidate]
    used_tokens: int
    budget_tokens: int


class BudgetManager:
    """Filter candidates to fit within a per-call token budget."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        max_advice_tokens: int = _DEFAULT_MAX_TOKENS,
        ratio: float = _DEFAULT_RATIO,
    ) -> None:
        self.llm = llm
        self.max_advice_tokens = max_advice_tokens
        self.ratio = ratio

    def fit(
        self,
        prompt: str,
        candidates: Iterable[Candidate],
    ) -> BudgetPlan:
        prompt_tokens = self.llm.estimate_tokens(prompt)
        budget = max(_MIN_BUDGET, min(self.max_advice_tokens, int(prompt_tokens * self.ratio)))

        selected: list[Candidate] = []
        used = 0
        for cand in candidates:
            cost = self._candidate_cost(cand)
            if used + cost <= budget:
                selected.append(cand)
                used += cost
            else:
                # Try to fit smaller candidates further down the list.
                continue
        return BudgetPlan(selected=selected, used_tokens=used, budget_tokens=budget)

    def _candidate_cost(self, cand: Candidate) -> int:
        # Render once exactly the way Advisor will, so cost reflects reality.
        from evol.advisor.advisor import render_candidate_line  # noqa: PLC0415

        line = render_candidate_line(cand)
        return self.llm.estimate_tokens(line)


__all__ = ["BudgetManager", "BudgetPlan"]
