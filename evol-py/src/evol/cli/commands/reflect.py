"""``evol reflect`` — manually trigger a reflection cycle.

Also picks up any deferred host-backend reflections whose response has now
arrived. With ``--pickup-only`` it does only the pickup step.
"""

from __future__ import annotations

from pathlib import Path

import click

from evol.api import Evol
from evol.cli import output as out
from evol.config import load_config
from evol.errors import EvolError


@click.command(help="Trigger a reflection cycle now.")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=Path("evol.config.yaml"),
    show_default=True,
)
@click.option(
    "--pickup-only",
    is_flag=True,
    default=False,
    help="Only resume any pending deferred reflections; don't start a new cycle.",
)
@click.pass_context
def cmd(ctx: click.Context, config_path: Path, pickup_only: bool) -> None:
    root: Path = ctx.obj["root"]
    try:
        config = load_config(config_path)
        evol = Evol(config=config, root=root)
    except EvolError as e:
        out.error(str(e))
        raise click.Abort() from e

    if evol.is_paused():
        out.warn("EVOL is paused; reflect refuses to run. Use `evol resume` first.")
        return

    # Step 1: resume anything pending (idempotent).
    try:
        resumed = evol.reflector.resume_pending()
    except EvolError as e:
        out.error(f"resume_pending failed: {e}")
        raise click.Abort() from e

    for r in resumed:
        out.success(
            f"resumed deferred reflection {r.reflection_id} "
            f"(applied={r.insights_applied}, rejected={r.insights_rejected})"
        )

    if pickup_only:
        if not resumed:
            out.info("nothing pending.")
        return

    # Step 2: fresh reflection.
    try:
        result = evol.reflector.reflect()
    except EvolError as e:
        out.error(f"reflect failed: {e}")
        raise click.Abort() from e

    _print_result(result)


def _print_result(result) -> None:  # type: ignore[no-untyped-def]
    out.kv_table(
        f"Reflection {result.reflection_id}",
        {
            "status": result.status,
            "insights_total": result.insights_total,
            "insights_applied": result.insights_applied,
            "insights_rejected": result.insights_rejected,
            "memory_version_before": result.memory_version_before,
            "memory_version_after": result.memory_version_after,
            "deferred_id": result.deferred_id,
            "notes": result.notes,
        },
    )
    if result.status == "pending_host":
        out.info("Reflection deferred to host agent. Run `evol reflect` again after the host responds.")
    elif result.status == "completed":
        out.success("Reflection complete; Memory updated.")
    elif result.status == "no_op":
        out.info("No new experiences since last reflection.")
    elif result.status in {"llm_failed", "parse_failed", "consolidate_failed", "preflight_failed"}:
        out.error(f"Reflection {result.status}")
