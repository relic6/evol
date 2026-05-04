"""Entrypoint for the ``evol`` CLI.

Each subcommand lives under ``evol.cli.commands``. This module is just a
Click group + plumbing. Avoid putting business logic here.
"""

from __future__ import annotations

from pathlib import Path

import click

from evol._version import __version__
from evol.cli.commands import diff as cmd_diff
from evol.cli.commands import export_import as cmd_export_import
from evol.cli.commands import init as cmd_init
from evol.cli.commands import memory_cmd
from evol.cli.commands import pause_resume as cmd_pause_resume
from evol.cli.commands import reflect as cmd_reflect
from evol.cli.commands import rollback as cmd_rollback
from evol.cli.commands import status as cmd_status
from evol.cli.commands import versions as cmd_versions


@click.group(help="EVOL — growth infrastructure for AI software.")
@click.version_option(version=__version__, prog_name="evol")
@click.option(
    "--root",
    type=click.Path(exists=False, file_okay=False, dir_okay=True, path_type=Path),
    default=Path.cwd(),
    show_default="cwd",
    help="Project root directory containing (or about to contain) .evol/",
)
@click.pass_context
def main(ctx: click.Context, root: Path) -> None:
    ctx.ensure_object(dict)
    ctx.obj["root"] = root.resolve()


main.add_command(cmd_init.cmd, name="init")
main.add_command(cmd_status.cmd, name="status")
main.add_command(cmd_reflect.cmd, name="reflect")
main.add_command(memory_cmd.cmd, name="memory")
main.add_command(cmd_rollback.cmd, name="rollback")
main.add_command(cmd_diff.cmd, name="diff")
main.add_command(cmd_export_import.export_cmd, name="export")
main.add_command(cmd_export_import.import_cmd, name="import")
main.add_command(cmd_pause_resume.pause_cmd, name="pause")
main.add_command(cmd_pause_resume.resume_cmd, name="resume")
main.add_command(cmd_versions.cmd, name="versions")


if __name__ == "__main__":
    main()  # pragma: no cover


__all__ = ["main"]
