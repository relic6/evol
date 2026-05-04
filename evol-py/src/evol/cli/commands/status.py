"""``evol status`` — show current EVOL state."""

from __future__ import annotations

from pathlib import Path

import click

from evol.api import Evol
from evol.cli import output as out
from evol.config import load_config
from evol.errors import EvolError


@click.command(help="Show the current state of this project's EVOL.")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=Path("evol.config.yaml"),
    show_default=True,
)
@click.pass_context
def cmd(ctx: click.Context, config_path: Path) -> None:
    root: Path = ctx.obj["root"]

    try:
        config = load_config(config_path)
        evol = Evol(config=config, root=root)
    except EvolError as e:
        out.error(str(e))
        raise click.Abort() from e

    state = evol.state()
    paused_label = "[bold red]PAUSED[/bold red]" if state.paused else "running"
    out.kv_table(
        "EVOL status",
        {
            "product": f"{state.product_name} v{state.product_version}",
            "protocol_version": state.protocol_version,
            "memory_version": state.memory_version,
            "memory_checksum": _short(state.memory_checksum),
            "experience_count": state.experience_count,
            "snapshot_versions": state.snapshot_versions,
            "last_reflection": _format_last_reflection(state),
            "runtime": paused_label,
        },
    )


def _short(checksum: str) -> str:
    if not checksum:
        return "—"
    if len(checksum) <= 24:
        return checksum
    return f"{checksum[:14]}…{checksum[-6:]}"


def _format_last_reflection(state) -> str:  # type: ignore[no-untyped-def]
    if not state.last_reflection_id:
        return "—"
    return f"{state.last_reflection_id} @ {state.last_reflection_at or '—'}"
