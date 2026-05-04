"""``manifest.yaml`` read / write / migration.

The manifest is the single source of truth for "current state":

- which Memory version is active
- the canonical checksum of that Memory
- product identity & EVOL protocol version
- experiences counters
- last reflection metadata
- runtime view of anchors (with rule_hash)

CONTRACT §10.1 specifies the schema; this module is the executable form.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from evol._version import PROTOCOL_VERSION
from evol.concurrency import atomic_write_text
from evol.core.time_utils import utc_now_iso
from evol.core.types import Anchor, Manifest
from evol.errors import EvolStorageError


class ManifestStore:
    """Read / write the ``manifest.yaml`` file at the root of ``.evol/``."""

    FILENAME = "manifest.yaml"

    def __init__(self, evol_root: str | Path) -> None:
        self.evol_root = Path(evol_root)
        self.path = self.evol_root / self.FILENAME

    # ─── read / write ───

    def exists(self) -> bool:
        return self.path.is_file()

    def read(self) -> Manifest:
        if not self.path.is_file():
            raise EvolStorageError(f"manifest not found: {self.path}")
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise EvolStorageError(f"manifest YAML invalid: {e}") from e
        if not isinstance(raw, dict):
            raise EvolStorageError(f"manifest must be a mapping at top-level: {self.path}")
        try:
            return Manifest.model_validate(raw)
        except ValidationError as e:
            raise EvolStorageError(f"manifest schema invalid: {e}") from e

    def write(self, manifest: Manifest) -> None:
        text = yaml.safe_dump(
            manifest.model_dump(exclude_none=False),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=80,
            indent=2,
        )
        atomic_write_text(self.path, text)

    # ─── focused mutators ───

    def update_memory_pointer(
        self,
        *,
        version: int,
        checksum: str,
        last_updated: str | None = None,
    ) -> Manifest:
        """Update only the ``memory`` block, write atomically, and return the
        updated manifest."""
        m = self.read()
        m.memory = {
            **m.memory,
            "current_version": version,
            "checksum": checksum,
            "last_updated": last_updated or utc_now_iso(),
        }
        self.write(m)
        return m

    def update_experiences_pointer(
        self,
        *,
        count: int,
        last_id: str | None = None,
        oldest_kept: str | None = None,
    ) -> Manifest:
        m = self.read()
        m.experiences = {
            **m.experiences,
            "count": count,
        }
        if last_id is not None:
            m.experiences["last_id"] = last_id
        if oldest_kept is not None:
            m.experiences["oldest_kept"] = oldest_kept
        self.write(m)
        return m

    def update_last_reflection(
        self,
        *,
        reflection_id: str,
        performed_at: str | None = None,
    ) -> Manifest:
        m = self.read()
        m.last_reflection = {
            "id": reflection_id,
            "performed_at": performed_at or utc_now_iso(),
        }
        self.write(m)
        return m


# ─── factory: build a fresh manifest for a brand-new .evol/ ───


def build_initial_manifest(
    *,
    product_name: str,
    product_version: str,
    product_domain: str | None = None,
    anchors: list[Anchor] | None = None,
) -> Manifest:
    """Build a Manifest representing a freshly-initialized ``.evol/``.

    Memory is at version 0 (no entries yet, but checksum corresponds to the
    canonical empty state). Experiences count is 0.
    """
    from evol.memory.checksum import compute_checksum_from_files  # noqa: PLC0415

    empty_memory = {
        kind: {
            "schema_version": 1,
            "memory_kind": kind,
            "version": 0,
            "last_updated": utc_now_iso(),
            "entries": [],
        }
        for kind in ("user_profile", "domain_knowledge", "self_awareness")
    }
    checksum = compute_checksum_from_files(empty_memory)
    now = utc_now_iso()

    product: dict[str, str] = {"name": product_name, "version": product_version}
    if product_domain is not None:
        product["domain"] = product_domain

    return Manifest(
        schema_version=1,
        protocol_version=PROTOCOL_VERSION,
        product=product,
        memory={
            "current_version": 0,
            "checksum": checksum,
            "last_updated": now,
        },
        experiences={
            "count": 0,
            "last_id": None,
            "oldest_kept": None,
        },
        last_reflection=None,
        anchors=list(anchors or []),
        metadata={},
    )


__all__ = ["ManifestStore", "build_initial_manifest"]
