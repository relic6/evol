"""Shared pytest fixtures for unit / integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_evol_dir(tmp_path: Path) -> Iterator[Path]:
    """Provide a clean ``.evol/`` directory under ``tmp_path``."""
    d = tmp_path / ".evol"
    d.mkdir()
    yield d


@pytest.fixture()
def minimal_config_yaml() -> str:
    """Smallest valid evol.config.yaml content as a string."""
    return (
        "schema_version: 1\n"
        "product:\n"
        "  name: test-cli\n"
        "  version: 0.0.1\n"
    )
