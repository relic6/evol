"""``evol pause`` / ``evol resume``."""

from __future__ import annotations

from pathlib import Path

import click

from evol.api import Evol
from evol.cli import output as out
from evol.config import load_config
from evol.errors import EvolError


def _open_evol(ctx: click.Context, config_path: Path) -> Evol:
    root: Path = ctx.obj["root"]
    try:
        config = load_config(config_path)
        return Evol(config=config, root=root)
    except EvolError as e:
        out.error(str(e))
        raise click.Abort() from e


@click.command(help="Freeze EVOL: stop recording / reflecting / inspiring.")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=Path("evol.config.yaml"),
    show_default=True,
)
@click.pass_context
def pause_cmd(ctx: click.Context, config_path: Path) -> None:
    evol = _open_evol(ctx, config_path)
    evol.pause()
    out.success("EVOL paused — recording, reflection, inspiration are disabled.")


@click.command(help="Resume a previously paused EVOL.")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=Path("evol.config.yaml"),
    show_default=True,
)
@click.pass_context
def resume_cmd(ctx: click.Context, config_path: Path) -> None:
    evol = _open_evol(ctx, config_path)
    evol.resume()
    out.success("EVOL resumed.")
