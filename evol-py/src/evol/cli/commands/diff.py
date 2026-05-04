"""``evol diff <a> <b>`` — text diff between two snapshot versions."""

from __future__ import annotations

import difflib
import tarfile
import tempfile
from pathlib import Path

import click

from evol.api import Evol
from evol.cli import output as out
from evol.config import load_config
from evol.errors import EvolError
from evol.memory.snapshot import snapshot_filename


@click.command(help="Diff two Memory snapshot versions, kind by kind.")
@click.argument("a", type=int)
@click.argument("b", type=int)
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=Path("evol.config.yaml"),
    show_default=True,
)
@click.pass_context
def cmd(ctx: click.Context, a: int, b: int, config_path: Path) -> None:
    root: Path = ctx.obj["root"]
    try:
        config = load_config(config_path)
        evol = Evol(config=config, root=root)
    except EvolError as e:
        out.error(str(e))
        raise click.Abort() from e

    versions_dir = evol.snapshot_manager.versions_dir
    snap_a = versions_dir / snapshot_filename(a)
    snap_b = versions_dir / snapshot_filename(b)
    for name, p in (("a", snap_a), ("b", snap_b)):
        if not p.is_file():
            out.error(f"snapshot {name}=v{a if name == 'a' else b} not found at {p}")
            raise click.Abort()

    with tempfile.TemporaryDirectory() as scratch:
        scratch_path = Path(scratch)
        dir_a = scratch_path / f"v{a}"
        dir_b = scratch_path / f"v{b}"
        _extract(snap_a, dir_a)
        _extract(snap_b, dir_b)
        for kind in ("user_profile", "domain_knowledge", "self_awareness"):
            file_a = dir_a / f"{kind}.yaml"
            file_b = dir_b / f"{kind}.yaml"
            text_a = file_a.read_text(encoding="utf-8") if file_a.is_file() else ""
            text_b = file_b.read_text(encoding="utf-8") if file_b.is_file() else ""
            if text_a == text_b:
                out.info(f"{kind}: unchanged")
                continue
            out.info(f"{kind}: ↓")
            diff = difflib.unified_diff(
                text_a.splitlines(keepends=True),
                text_b.splitlines(keepends=True),
                fromfile=f"v{a}/{kind}.yaml",
                tofile=f"v{b}/{kind}.yaml",
            )
            click.echo("".join(diff))


def _extract(snap: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    with tarfile.open(snap, "r:gz") as tar:
        try:
            tar.extractall(dst, filter="data")  # type: ignore[arg-type]
        except TypeError:
            tar.extractall(dst)  # noqa: S202
