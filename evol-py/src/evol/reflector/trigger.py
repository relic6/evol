"""Reflection triggers — manual / threshold / scheduled.

Each trigger answers a single question: *is now the time to reflect?* The
Reflector orchestrator polls ``should_fire(...)`` and proceeds only when
the answer is yes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, cast

from evol.config import ReflectionConfig
from evol.errors import EvolConfigError


class TriggerBase(ABC):
    """Common interface for reflection triggers."""

    @abstractmethod
    def should_fire(
        self,
        *,
        new_experiences_since_last: int,
        last_reflection_at: str | None,
    ) -> bool: ...


class ManualTrigger(TriggerBase):
    """Fires only when explicitly invoked (CLI / programmatic)."""

    def should_fire(
        self,
        *,
        new_experiences_since_last: int,
        last_reflection_at: str | None,
    ) -> bool:
        return False


class ThresholdTrigger(TriggerBase):
    """Fires when N new experiences have accumulated since last reflection."""

    def __init__(self, threshold: int = 20) -> None:
        if threshold < 1:
            raise EvolConfigError(f"threshold must be ≥ 1, got {threshold}")
        self.threshold = threshold

    def should_fire(
        self,
        *,
        new_experiences_since_last: int,
        last_reflection_at: str | None,
    ) -> bool:
        return new_experiences_since_last >= self.threshold


class ScheduledTrigger(TriggerBase):
    """Fires when the cron expression's next-fire-time has passed.

    Uses ``croniter`` if installed; otherwise reports never-fires (caller
    should switch to manual mode).
    """

    def __init__(self, cron: str) -> None:
        self.cron = cron
        try:
            from croniter import croniter  # type: ignore[import-untyped]  # noqa: PLC0415

            self._croniter = croniter
            self._available = True
        except ImportError:  # pragma: no cover
            self._croniter = None
            self._available = False

    def should_fire(
        self,
        *,
        new_experiences_since_last: int,
        last_reflection_at: str | None,
    ) -> bool:
        if not self._available:
            return False
        if last_reflection_at is None:
            return True

        from evol.core.time_utils import parse_iso, utc_now  # noqa: PLC0415

        base = parse_iso(last_reflection_at)
        cron_factory = cast(Any, self._croniter)
        itr = cron_factory(self.cron, base)
        next_fire = cast(datetime, itr.get_next(ret_type=type(base)))
        return utc_now() >= next_fire


def build_trigger(config: ReflectionConfig) -> TriggerBase:
    if config.trigger == "manual":
        return ManualTrigger()
    if config.trigger == "threshold":
        return ThresholdTrigger(threshold=config.threshold)
    if config.trigger == "scheduled":
        if not config.schedule:
            raise EvolConfigError(
                "trigger=scheduled requires reflection.schedule (cron expression)"
            )
        return ScheduledTrigger(cron=config.schedule)
    raise EvolConfigError(f"unknown trigger: {config.trigger!r}")


__all__ = [
    "ManualTrigger",
    "ScheduledTrigger",
    "ThresholdTrigger",
    "TriggerBase",
    "build_trigger",
]
