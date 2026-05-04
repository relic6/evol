"""``evol export`` / ``evol import`` — bundle the whole ``.evol/`` directory."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import click

from evol.api import Evol
from evol.cli import output as out
from evol.config import load_config
from evol.errors import EvolError


# ─── export ───


@click.command(help="Export the .evol/ directory as a single archive.")
@click.argument(
    "destination",
    type=click.Path(file_okay=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--redacted/--full",
    "redacted",
    default=True,
    help="Redact PII (input/output of every Experience) before exporting. "
    "Default: --redacted (safe).",
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
def export_cmd(
    ctx: click.Context,
    destination: Path,
    redacted: bool,
    config_path: Path,
) -> None:
    root: Path = ctx.obj["root"]
    try:
        config = load_config(config_path)
        evol = Evol(config=config, root=root)
    except EvolError as e:
        out.error(str(e))
        raise click.Abort() from e

    src = evol.evol_dir
    if not src.is_dir():
        out.error(f"no .evol/ at {src}")
        raise click.Abort()

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(destination, "w:gz") as tar:
            for item in sorted(src.rglob("*")):
                rel = item.relative_to(src)
                if redacted and _should_redact(rel):
                    payload = _redact_jsonl(item.read_text(encoding="utf-8"))
                    info = tarfile.TarInfo(name=rel.as_posix())
                    info.size = len(payload.encode("utf-8"))
                    import io  # noqa: PLC0415

                    tar.addfile(info, fileobj=io.BytesIO(payload.encode("utf-8")))
                else:
                    tar.add(item, arcname=rel.as_posix())
    except (OSError, tarfile.TarError) as e:
        out.error(f"export failed: {e}")
        raise click.Abort() from e

    mode = "redacted" if redacted else "full (PII INCLUDED)"
    out.success(f"exported [{mode}] → {destination}")


def _should_redact(rel: Path) -> bool:
    name = rel.as_posix()
    return name in {"experiences.jsonl", "experiences.feedback.jsonl"}


def _redact_jsonl(text: str) -> str:
    out_lines: list[str] = []
    for raw in text.splitlines():
        if not raw.strip():
            out_lines.append("")
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            out_lines.append(raw)
            continue
        if "input" in d:
            d["input"] = "[REDACTED]"
        if "output" in d and d.get("output") is not None:
            d["output"] = "[REDACTED]"
        if isinstance(d.get("signal"), dict) and d["signal"].get("type") == "comment":
            d["signal"]["value"] = "[REDACTED]"
        d["redacted"] = True
        out_lines.append(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(out_lines) + "\n"


# ─── import ───


@click.command("import", help="Import a previously exported .evol/ archive.")
@click.argument(
    "source",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Overwrite an existing .evol/ directory.",
)
@click.pass_context
def import_cmd(ctx: click.Context, source: Path, force: bool) -> None:
    root: Path = ctx.obj["root"]
    target = root / ".evol"

    if target.exists() and any(target.iterdir()):
        if not force:
            out.error(f".evol/ already exists at {target}; use --force to overwrite")
            raise click.Abort()
        # Remove existing contents (but keep the dir itself)
        import shutil  # noqa: PLC0415

        for child in target.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    target.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(source, "r:gz") as tar:
            try:
                tar.extractall(target, filter="data")  # type: ignore[arg-type]
            except TypeError:
                tar.extractall(target)  # noqa: S202
    except (OSError, tarfile.TarError) as e:
        out.error(f"import failed: {e}")
        raise click.Abort() from e

    out.success(f"imported {source} → {target}")
