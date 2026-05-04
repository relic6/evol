"""Load and write ``evol.config.yaml``.

Loader is fail-fast: malformed YAML, schema-violating fields, or unsupported
``schema_version`` all raise :class:`EvolConfigError` so callers cannot
proceed with a half-configured EVOL.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from evol.config.schema import Config
from evol.errors import EvolConfigError


def load_config(path: str | Path) -> Config:
    """Read, parse, and validate an ``evol.config.yaml`` file.

    Raises:
        EvolConfigError: if the file is missing, malformed, or fails schema
            validation. The original cause is chained via ``__cause__``.
    """
    p = Path(path)
    if not p.exists():
        raise EvolConfigError(f"config file not found: {p}")
    if not p.is_file():
        raise EvolConfigError(f"config path is not a regular file: {p}")

    try:
        raw_text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise EvolConfigError(f"unable to read config file {p}: {e}") from e

    try:
        raw_data = yaml.safe_load(raw_text)
    except yaml.YAMLError as e:
        raise EvolConfigError(f"invalid YAML in {p}: {e}") from e

    if not isinstance(raw_data, dict):
        raise EvolConfigError(
            f"config file {p} must contain a YAML mapping at the top level"
        )

    try:
        return Config.model_validate(raw_data)
    except ValidationError as e:
        raise EvolConfigError(f"config validation failed for {p}:\n{e}") from e


def write_runtime_copy(config: Config, evol_dir: str | Path) -> Path:
    """Write a runtime copy of the validated config to ``.evol/config.yaml``.

    CONTRACT §9 requires SDKs to maintain a runtime copy that mirrors the
    user-supplied config. Returns the destination path.
    """
    dest_dir = Path(evol_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "config.yaml"

    payload = config.model_dump(exclude_none=False)
    text = yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=80,
        indent=2,
    )
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(dest)
    return dest


__all__ = ["load_config", "write_runtime_copy"]
