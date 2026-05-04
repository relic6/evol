"""Skill entry point: prepare an enhanced prompt for the host agent.

Usage (called by Claude Code or another host agent):

    python journal_summarize.py < today.txt
    # → prints the enhanced prompt for the host to consume

After the host (Claude Code) produces a summary, it should call:

    python journal_summarize.py --record <experience_id> < summary.txt
    # → records the host's response as the task output

The split is intentional: EVOL never calls a model in this flow. The host
is the LLM; this script just orchestrates the file protocol.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from evol import Evol


_HERE = Path(__file__).resolve().parent
_CONFIG = _HERE.parent / "evol.config.yaml"


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=_CONFIG,
    show_default=True,
)
@click.option(
    "--record",
    "experience_id",
    default=None,
    help="Mark a previously-prepared task as completed with stdin content as output.",
)
@click.option(
    "--reflect-pickup",
    is_flag=True,
    default=False,
    help="Pick up any deferred reflections the host has answered.",
)
def main(config_path: Path, experience_id: str | None, reflect_pickup: bool) -> None:
    evol = Evol.from_config(config_path)

    if reflect_pickup:
        results = evol.reflector.resume_pending()
        click.echo(json.dumps([r.model_dump() for r in results], default=str, ensure_ascii=False))
        return

    if experience_id:
        # The host has produced output; close the task.
        output = sys.stdin.read().strip()
        # We don't have a TaskHandle anymore (different process), so we close
        # by appending a 'closed' record manually via the recorder's main store.
        from evol.core.canonical import canonical_jsonl_dump  # noqa: PLC0415
        from evol.core.time_utils import utc_now_iso  # noqa: PLC0415

        record = {
            "id": experience_id,
            "task_kind": "summarize",
            "status": "closed",
            "started_at": utc_now_iso(),
            "ended_at": utc_now_iso(),
            "input": "(see prior open record)",
            "output": output,
            "signals": [],
            "advice_used": [],
            "anchors_applied": [],
            "metadata": {"closed_via": "skill"},
            "redacted": False,
        }
        evol.recorder.main.append(record, line=canonical_jsonl_dump(record))
        click.echo(f"recorded host response for {experience_id}")
        return

    # Default flow: prepare an enhanced prompt for the host to consume.
    journal = sys.stdin.read().strip()
    if not journal:
        raise click.UsageError("expected journal text on stdin")

    handle = evol.recorder.start_task(input=journal, task_kind="summarize")
    base_prompt = (
        "请把下面的日记总结成一段 100 字以内的概要：\n\n"
        f"{journal}\n"
    )
    enhanced = evol.advisor.enhance(base_prompt, task={"task_kind": "summarize"})

    # Output a small JSON envelope the host can parse
    click.echo(
        json.dumps(
            {
                "experience_id": handle.experience_id,
                "enhanced_prompt": enhanced,
                "instructions": (
                    "Run this prompt yourself. Then call this script again "
                    f"with --record {handle.experience_id} and pipe the summary on stdin."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
