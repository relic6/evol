"""``evol rollback <version>`` — restore Memory from a snapshot.

The rollback flow follows CONTRACT §8.2 / FLOWS §6.4:
  1. acquire reflection.lock (so a concurrent reflection can't race us)
  2. extract the target snapshot into ``memory/``
  3. update ``manifest.yaml.memory.current_version`` + checksum
  4. append a system Experience to ``experiences.jsonl`` documenting the rollback
"""

from __future__ import annotations

from pathlib import Path

import click

from evol.api import Evol
from evol.cli import output as out
from evol.concurrency import file_lock
from evol.config import load_config
from evol.core.canonical import canonical_jsonl_dump
from evol.core.ids import gen_experience_id
from evol.core.time_utils import utc_now_iso
from evol.errors import EvolError
from evol.memory import compute_checksum_from_memory


@click.command(help="Roll Memory back to a specific snapshot version.")
@click.argument("version", type=int)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the interactive confirmation prompt.",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=Path("evol.config.yaml"),
    show_default=True,
)
@click.pass_context
def cmd(
    ctx: click.Context,
    version: int,
    yes: bool,
    config_path: Path,
) -> None:
    root: Path = ctx.obj["root"]
    try:
        config = load_config(config_path)
        evol = Evol(config=config, root=root)
    except EvolError as e:
        out.error(str(e))
        raise click.Abort() from e

    sm = evol.snapshot_manager
    if not sm.has_version(version):
        out.error(
            f"snapshot v{version} not found. Available: {sm.list_versions() or '—'}"
        )
        raise click.Abort()

    state = evol.state()
    out.info(
        f"Rolling back: memory v{state.memory_version} → v{version}"
    )

    if not yes and not click.confirm("Proceed?", default=False):
        out.info("aborted")
        return

    lock_path = evol.evol_dir / "locks" / "reflection.lock"
    try:
        with file_lock(lock_path, timeout=5.0):
            sm.rollback_to(version)
            files = evol.memory_store.load_all()
            checksum = compute_checksum_from_memory(files)
            evol.manifest_store.update_memory_pointer(
                version=version, checksum=checksum
            )
            _record_rollback_experience(evol, from_version=state.memory_version, to=version)
    except EvolError as e:
        out.error(f"rollback failed: {e}")
        raise click.Abort() from e

    out.success(f"rolled back to v{version}")


def _record_rollback_experience(evol: Evol, *, from_version: int, to: int) -> None:
    record = {
        "id": gen_experience_id(),
        "task_kind": "system.rollback",
        "status": "closed",
        "started_at": utc_now_iso(),
        "ended_at": utc_now_iso(),
        "input": {"from_version": from_version, "to_version": to},
        "output": "completed",
        "signals": [],
        "advice_used": [],
        "anchors_applied": [],
        "metadata": {"system": True},
        "redacted": False,
    }
    evol.recorder.main.append(record, line=canonical_jsonl_dump(record))
