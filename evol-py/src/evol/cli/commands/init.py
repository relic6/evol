"""``evol init`` — initialize a fresh ``.evol/`` directory.

Bootstrap behavior is implemented inside ``Evol.__init__`` (it self-initializes
when ``.evol/`` is missing). This command exposes that path explicitly and
prints a friendly summary.
"""

from __future__ import annotations

from pathlib import Path

import click

from evol.api import Evol
from evol.cli import output as out
from evol.config import load_config
from evol.errors import EvolError


@click.command(help="Initialize a fresh .evol/ directory in the current project.")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=Path("evol.config.yaml"),
    show_default=True,
    help="Path to evol.config.yaml",
)
@click.pass_context
def cmd(ctx: click.Context, config_path: Path) -> None:
    root: Path = ctx.obj["root"]
    out.info(f"Initializing EVOL in {root}")

    try:
        config = load_config(config_path)
        evol = Evol(config=config, root=root)
    except EvolError as e:
        out.error(str(e))
        raise click.Abort() from e

    state = evol.state()
    out.success(f"Created .evol/ at {evol.evol_dir}")
    out.kv_table(
        "Initial state",
        {
            "product": f"{state.product_name} v{state.product_version}",
            "protocol_version": state.protocol_version,
            "memory_version": state.memory_version,
            "experience_count": state.experience_count,
            "snapshots": state.snapshot_versions,
            "paused": state.paused,
        },
    )
