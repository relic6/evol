"""journal-cli — a 60-line example of EVOL in production.

Pipe a day's diary text into stdin; get a 100-character summary back.
Each interaction is recorded as an Experience, advisor.enhance() injects
accumulated user preferences into the prompt, and inspire() occasionally
emits a thought-provoking observation.

After ~10 uses + a couple of edits / discards via the --feedback flag,
you should see the summary style adapt to your preferences.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from evol import Evol

_console = Console()
_PROMPT_TEMPLATE = """请把下面的日记总结成一段 100 字以内的概要：

{journal}
"""


def _build_messages(prompt: str) -> list[dict]:
    return [{"role": "user", "content": prompt}]


def _summarize(evol: Evol, journal: str) -> tuple[str, str | None]:
    handle = evol.recorder.start_task(input=journal, task_kind="summarize")
    prompt = _PROMPT_TEMPLATE.format(journal=journal)
    enhanced = evol.advisor.enhance(prompt, task={"task_kind": "summarize"})

    # Direct LLM call. The example uses the configured backend (Anthropic by
    # default); host/subprocess users won't hit this code path because they'd
    # let their host agent run the model directly.
    from evol.llm import LLMResponse, Message  # noqa: PLC0415

    response = evol.llm.chat(
        [Message(role="user", content=enhanced)],
        purpose="reflection",  # arbitrary; this is the product's own call
        max_tokens=512,
        temperature=0.4,
    )
    if not isinstance(response, LLMResponse):
        # Host backend would not be the right fit for a *task* call. We bail.
        evol.recorder.end_task(handle, output=None)
        raise click.ClickException(
            "EVOL is configured for host backend; product LLM calls should "
            "happen in the host agent, not here. Use the Skill example instead."
        )

    output = response.text.strip()
    evol.recorder.end_task(handle, output=output)

    inspiration = evol.advisor.inspire(task={"task_kind": "summarize"})
    return output, (inspiration.text if inspiration else None)


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=Path(__file__).with_name("evol.config.yaml"),
    show_default=True,
)
@click.option(
    "--feedback",
    type=click.Choice(["kept", "edited", "discarded"]),
    default=None,
    help="Attach this signal to the most recent task (use after running once "
    "and inspecting the output).",
)
@click.option(
    "--last-id",
    default=None,
    help="Experience id to attach feedback to (used with --feedback). "
    "If omitted, feedback is attached to the most recent closed task.",
)
def main(config_path: Path, feedback: str | None, last_id: str | None) -> None:
    """Read a journal entry from stdin and print a summary (+ maybe an inspiration)."""
    evol = Evol.from_config(config_path)

    if feedback is not None:
        target_id = last_id or _most_recent_experience_id(evol)
        if target_id is None:
            _console.print("[yellow]no recent experience to attach feedback to[/yellow]")
            return
        from evol.core.types import Signal  # noqa: PLC0415
        from evol.core.time_utils import utc_now_iso  # noqa: PLC0415

        evol.recorder.feedback(
            target_id, Signal(type=feedback, ts=utc_now_iso(), source="explicit")
        )
        _console.print(f"[green]✓[/green] attached {feedback} feedback to {target_id}")
        return

    journal = sys.stdin.read().strip()
    if not journal:
        raise click.UsageError("expected a journal entry on stdin")

    summary, inspiration = _summarize(evol, journal)
    _console.print(summary)
    if inspiration:
        _console.print(f"\n[bold magenta]💡 EVOL:[/bold magenta] {inspiration}")


def _most_recent_experience_id(evol: Evol) -> str | None:
    last_id: str | None = None
    for exp in evol.recorder.iter_experiences():
        if exp.status == "closed":
            last_id = exp.id
    return last_id


if __name__ == "__main__":
    main()
