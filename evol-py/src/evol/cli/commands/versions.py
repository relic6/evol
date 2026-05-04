"""``evol versions`` — list Memory snapshot history."""

from __future__ import annotations

from pathlib import Path

import click

from evol.api import Evol
from evol.cli import output as out
from evol.config import load_config
from evol.errors import EvolError


@click.command(help="List all Memory snapshot versions on disk.")
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

    versions = evol.snapshot_manager.list_versions()
    current = evol.state().memory_version
    if not versions:
        out.warn("No snapshots yet.")
        return

    rows = [
        [v, "current" if v == current else "", f"memory-v{v}.snapshot"]
        for v in versions
    ]
    out.list_table("Memory snapshots", ["version", "active", "filename"], rows)
