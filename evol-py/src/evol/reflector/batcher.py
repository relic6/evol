"""Experience batch selection — by signal priority + cap.

FLOWS §3.3 prioritises experiences with high-signal feedback (edited /
discarded / rated≤2 / comment) over plain ``kept`` ones. When the batch
exceeds ``max_experiences_per_run``, lower-priority experiences are dropped
first.
"""

from __future__ import annotations

from collections.abc import Iterable

from evol.core.types import Experience

# Higher = more important, kept first when over budget.
_HIGH_SIGNAL_TYPES = {"edited", "discarded", "comment"}
_LOW_SIGNAL_TYPES = {"kept"}


def _priority(exp: Experience) -> int:
    """Return a sort key. Higher = more important.

    Heuristic order:
        3 = explicit negative / edit feedback (most informative)
        2 = rated 1-2 (negative-leaning)
        1 = no signal but task_kind has variation (default informative)
        0 = only ``kept`` signals (low information density)
    """
    types = {s.type for s in exp.signals}
    if types & _HIGH_SIGNAL_TYPES:
        return 3
    for s in exp.signals:
        if s.type == "rated" and isinstance(s.value, int | float) and s.value <= 2:
            return 2
    if types and not types.issubset(_LOW_SIGNAL_TYPES):
        return 1
    if types and types.issubset(_LOW_SIGNAL_TYPES):
        return 0
    # No signals at all: middle priority — could still teach.
    return 1


class Batcher:
    """Select an experience batch for reflection."""

    def __init__(self, max_experiences_per_run: int = 100) -> None:
        if max_experiences_per_run < 1:
            from evol.errors import EvolConfigError  # noqa: PLC0415

            raise EvolConfigError(
                f"max_experiences_per_run must be ≥ 1, got {max_experiences_per_run}"
            )
        self.max_n = max_experiences_per_run

    def select(self, experiences: Iterable[Experience]) -> list[Experience]:
        """Return up to ``max_n`` experiences, preferring high-priority ones.

        Priority is the only sort criterion *for filtering*; chronological
        order is preserved within the result so the LLM sees the timeline.
        """
        # First materialize and pair each with its original index + priority
        all_with_meta = [(idx, _priority(e), e) for idx, e in enumerate(experiences)]
        if len(all_with_meta) <= self.max_n:
            return [e for _, _, e in all_with_meta]

        # Drop lowest-priority items first (then oldest-first within ties).
        all_with_meta.sort(key=lambda t: (t[1], -t[0]), reverse=True)
        kept = all_with_meta[: self.max_n]
        # Restore chronological order by original index.
        kept.sort(key=lambda t: t[0])
        return [e for _, _, e in kept]


__all__ = ["Batcher"]
