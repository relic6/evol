"""Deterministic 30-day evolution simulation.

Runs without an API key — uses :class:`MockLLMClient` to play the role of
the LLM. Demonstrates that:
  - Memory accumulates across days
  - Reflections sharpen the user_profile
  - Day-1 vs Day-30 outputs differ in measurable ways
  - All artifacts in ``.evol/`` stay human-readable

Run from this directory:

    python simulate_30_days.py

Then poke at:

    cat .evol/memory/user_profile.yaml
    ls .evol/insights/
    ls .evol/versions/
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from rich.console import Console

from evol import Evol
from evol.core.types import Signal
from evol.llm import MockLLMClient

_console = Console()
_HERE = Path(__file__).parent
_EVOL_DIR = _HERE / ".evol"
_CONFIG = _HERE / "evol.config.yaml"


# ───────── deterministic "LLM" behavior ─────────


def _summarize_response(day: int) -> str:
    """The 'LLM' summary for day N. Stays terse."""
    return f"Day {day}: 今天主要在工作 + 阅读，总体充实。"


def _reflection_response(memory_version: int) -> str:
    """Shape: a JSON array of insights. Memory grows version by version."""
    insights = []
    if memory_version == 0:
        insights = [
            {
                "scope": "user_profile",
                "key": "summary_length",
                "claim": "user prefers shorter summaries (< 80 chars)",
                "proposed_change": {"op": "set", "value": "60-80 chars"},
                "confidence": 0.85,
                "evidence_ids": [f"exp_seed_{i}" for i in range(8)],
            }
        ]
    elif memory_version == 1:
        insights = [
            {
                "scope": "user_profile",
                "key": "highlight_pattern",
                "claim": "user values '今天学到了什么' over '今天做了什么'",
                "proposed_change": {"op": "set", "value": "highlight learnings, not activities"},
                "confidence": 0.85,
                "evidence_ids": [f"exp_seed_{i}" for i in range(8)],
            }
        ]
    elif memory_version == 2:
        insights = [
            {
                "scope": "domain_knowledge",
                "key": "common_themes",
                "claim": "diary entries cluster around: AI 工程, 阅读, 健身",
                "proposed_change": {"op": "set", "value": "[AI 工程, 阅读, 健身]"},
                "confidence": 0.85,
                "evidence_ids": [f"exp_seed_{i}" for i in range(8)],
            }
        ]
    elif memory_version >= 3:
        insights = [
            {
                "scope": "self_awareness",
                "key": "weakness_first_line",
                "claim": "first-line summaries get edited > 60% of the time",
                "proposed_change": {"op": "set", "value": "first line is tricky for me"},
                "confidence": 0.85,
                "evidence_ids": [f"exp_seed_{i}" for i in range(8)],
            }
        ]
    return json.dumps(insights)


class _SimulatorLLM:
    """A faked LLM that returns summaries for normal turns and structured
    JSON insights when reflection asks for it."""

    def __init__(self) -> None:
        self._reflect_count = 0
        self._summary_day = 0
        self._underlying = MockLLMClient([])

    def _next(self, kind: str) -> str:
        if kind == "reflection":
            text = _reflection_response(self._reflect_count)
            self._reflect_count += 1
            return text
        if kind == "anchor_check":
            return "PASS"
        if kind == "summary":
            self._summary_day += 1
            return _summarize_response(self._summary_day)
        return "(no response configured)"

    # match LLMClient interface ─────────
    @property
    def backend_kind(self):  # type: ignore[no-untyped-def]
        return self._underlying.backend_kind

    is_synchronous = True

    def chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        purpose = kwargs.get("purpose", "reflection")
        from evol.llm.base import LLMBackendKind, LLMResponse  # noqa: PLC0415

        # Heuristic: a system prompt mentioning "Evolution Reflector" → reflection.
        sys_text = "\n".join(m.content for m in messages if m.role == "system")
        if "Evolution Reflector" in sys_text:
            text = self._next("reflection")
        elif "Anchor Validator" in sys_text:
            text = self._next("anchor_check")
        elif purpose == "inspiration":
            text = json.dumps(
                {
                    "kind": "suggestion",
                    "text": "试试用'反常识现象'切入下次的总结",
                    "evidence_ids": ["exp_seed_0", "exp_seed_1"],
                }
            )
        else:
            text = self._next("summary")
        return LLMResponse(
            text=text,
            backend=LLMBackendKind.DIRECT,
            model="mock-simulator",
        )

    def poll(self, deferred):  # type: ignore[no-untyped-def, ARG002]
        return None

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


# ───────── simulation harness ─────────


def _reset() -> None:
    if _EVOL_DIR.exists():
        shutil.rmtree(_EVOL_DIR)


def _print_state(evol: Evol, label: str) -> None:
    state = evol.state()
    user = evol.memory_store.load("user_profile")
    domain = evol.memory_store.load("domain_knowledge")
    self_aware = evol.memory_store.load("self_awareness")
    _console.rule(f"[bold]{label}[/bold]")
    _console.print(
        f"memory v{state.memory_version}  "
        f"experiences={state.experience_count}  "
        f"snapshots={state.snapshot_versions}"
    )
    for kind, mf in (
        ("user_profile", user),
        ("domain_knowledge", domain),
        ("self_awareness", self_aware),
    ):
        if mf.entries:
            _console.print(f"\n[cyan]{kind}[/cyan]")
            for e in mf.entries:
                if e.status != "active":
                    continue
                _console.print(
                    f"  - {e.key}: {e.value!s} "
                    f"(conf={e.confidence:.2f}, evidence={len(e.evidence_ids)})"
                )


def main(*, days: int = 30) -> None:
    _reset()
    evol = Evol.from_config(_CONFIG)
    evol._llm = _SimulatorLLM()  # noqa: SLF001 — test-only injection

    _print_state(evol, "Day 0 — fresh .evol/")

    for day in range(1, days + 1):
        # Each day produces one diary entry → one task.
        h = evol.recorder.start_task(
            input=f"Day {day}: 今天主要在工作 + 阅读，体感充实。",
            task_kind="summarize",
        )
        # In a real product this is where the LLM call would happen using
        # the *enhanced* prompt; we just call the mock.
        from evol.llm.base import Message  # noqa: PLC0415

        prompt = "summarize today's diary"
        enhanced = evol.advisor.enhance(prompt, task={"task_kind": "summarize"})
        response = evol.llm.chat(
            [Message(role="user", content=enhanced)],
            purpose="summary",
        )
        evol.recorder.end_task(h, output=response.text)

        # Every 3rd day the user "edits" the result (simulating dissatisfaction).
        if day % 3 == 0:
            evol.recorder.feedback(
                h.experience_id,
                Signal(type="edited", ts="2026-05-04T00:00:00.000Z"),
            )

        # Every 5 tasks (per config), a reflection runs.
        if evol.reflector.should_fire():
            result = evol.reflector.reflect()
            _console.print(
                f"[dim]day {day}: reflect → {result.status} "
                f"(applied={result.insights_applied})[/dim]"
            )

        # Sample inspiration on day 11 just to demonstrate it.
        if day == 11:
            insp = evol.advisor.inspire(task={"task_kind": "summarize"})
            if insp:
                _console.print(f"[magenta]💡 day {day}: {insp.text}[/magenta]")

    _print_state(evol, f"Day {days} — final state")
    _console.print(
        "\n[green]✓ simulation complete.[/green] Try:\n"
        f"  cat {_EVOL_DIR}/memory/user_profile.yaml\n"
        f"  ls {_EVOL_DIR}/insights/\n"
        f"  ls {_EVOL_DIR}/versions/"
    )


if __name__ == "__main__":
    main()
