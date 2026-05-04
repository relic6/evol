"""``evol memory show`` / ``evol memory edit``."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import click

from evol.api import Evol
from evol.cli import output as out
from evol.config import load_config
from evol.core.types import MemoryKind
from evol.errors import EvolError

_VALID_KINDS = ("user_profile", "domain_knowledge", "self_awareness")


def _open_evol(ctx: click.Context, config_path: Path) -> Evol:
    root: Path = ctx.obj["root"]
    try:
        config = load_config(config_path)
        return Evol(config=config, root=root)
    except EvolError as e:
        out.error(str(e))
        raise click.Abort() from e


@click.group(help="Inspect or edit Memory directly.")
def cmd() -> None:
    pass


@cmd.command("show", help="Display Memory contents (all kinds, or a single kind).")
@click.argument("kind", required=False)
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
    default=Path("evol.config.yaml"),
    show_default=True,
)
@click.pass_context
def show(ctx: click.Context, kind: str | None, config_path: Path) -> None:
    evol = _open_evol(ctx, config_path)
    kinds: tuple[MemoryKind, ...] = _VALID_KINDS if kind is None else (_validated_kind(kind),)

    for k in kinds:
        memfile = evol.memory_store.load(k)
        rows = [
            [
                e.key,
                _short(_value_str(e.value), 60),
                f"{e.confidence:.2f}",
                len(e.evidence_ids),
                e.revision_count,
                e.status,
            ]
            for e in memfile.entries
        ]
        title = f"memory / {k}  (v{memfile.version}, {len(memfile.entries)} entries)"
        if not rows:
            out.info(f"{title}: (empty)")
            continue
        out.list_table(
            title,
            ["key", "value", "confidence", "evidence", "revs", "status"],
            rows,
        )


@cmd.command("edit", help="Open the YAML for a Memory kind in $EDITOR.")
@click.argument(
    "kind",
    type=click.Choice(_VALID_KINDS, case_sensitive=False),
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
def edit(ctx: click.Context, kind: str, config_path: Path) -> None:
    evol = _open_evol(ctx, config_path)
    typed_kind: MemoryKind = _validated_kind(kind)
    path = evol.memory_store._path(typed_kind)  # noqa: SLF001 — well-known internal helper

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or _default_editor()
    if not shutil.which(editor.split()[0]):
        out.error(f"editor {editor!r} not found; set EDITOR or VISUAL env var")
        raise click.Abort()

    try:
        subprocess.run([*editor.split(), str(path)], check=False)
    except OSError as e:
        out.error(f"failed to launch editor: {e}")
        raise click.Abort() from e

    # After edit: re-load to validate and surface schema errors before the
    # next reflection blows up on it.
    try:
        evol.memory_store.load(typed_kind)
    except EvolError as e:
        out.warn(f"warning: edited file failed validation — {e}")
        return
    out.success(f"saved edits to {path}")


# ─── helpers ───


def _validated_kind(s: str) -> MemoryKind:
    if s not in _VALID_KINDS:
        raise click.BadParameter(
            f"unknown kind {s!r}; expected one of: {', '.join(_VALID_KINDS)}"
        )
    return s  # type: ignore[return-value]


def _value_str(v: object) -> str:
    if isinstance(v, str):
        return v
    if v is None:
        return "—"
    import json  # noqa: PLC0415

    return json.dumps(v, ensure_ascii=False)


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _default_editor() -> str:
    return "notepad" if os.name == "nt" else "nano"
