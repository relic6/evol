"""``Evol`` — the public facade.

This is what product code imports:

>>> from evol import Evol
>>> evol = Evol.from_config("evol.config.yaml")           # doctest: +SKIP

Phase 2 wires up: Config → Manifest → Memory → Snapshot → Recorder.
Reflector and Advisor come online in later phases (they will become
optional attributes of the same facade).
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from evol._version import PROTOCOL_VERSION
from evol.advisor import Advisor
from evol.config import Config, load_config, parse_anchors, write_runtime_copy
from evol.config.anchors import detect_anchor_drift
from evol.core.types import Manifest
from evol.errors import (
    EvolChecksumError,
    EvolError,
    EvolProtocolMismatch,
    EvolStorageError,
)
from evol.llm import LLMClient, detect_backend
from evol.logging import get_logger
from evol.memory import (
    ManifestStore,
    MemoryStore,
    SnapshotManager,
    build_initial_manifest,
    compute_checksum_from_memory,
)
from evol.recorder import Recorder
from evol.reflector import Reflector

_log = get_logger("evol.api")
_PAUSE_FILE = "PAUSED"


@dataclass
class EvolState:
    """Lightweight summary of the on-disk state — used by ``evol status``."""

    protocol_version: str
    product_name: str
    product_version: str
    memory_version: int
    memory_checksum: str
    experience_count: int
    reflected_experience_count: int
    paused: bool
    snapshot_versions: list[int]
    last_reflection_id: str | None
    last_reflection_at: str | None


class Evol:
    """Top-level entrypoint to the EVOL framework."""

    def __init__(
        self,
        *,
        config: Config,
        root: str | Path = ".",
        llm: LLMClient | None = None,
    ) -> None:
        self.config = config
        self.root = Path(root).resolve()
        self.evol_dir = self.root / ".evol"

        self.manifest_store = ManifestStore(self.evol_dir)
        self.memory_store = MemoryStore(self.evol_dir / "memory")
        self.snapshot_manager = SnapshotManager(self.evol_dir)
        self.recorder = Recorder(self.evol_dir, paused_marker=self.paused_marker)

        self._validate_or_initialize()
        self.recorder.ensure_initialized()
        # Crash recovery: detect any open experiences with no end_task.
        try:
            self.recorder.detect_orphans()
        except EvolError as e:
            _log.warning("orphan detection failed", extra={"err": str(e)})

        # LLM + Reflector + Advisor: built lazily so that init paths don't
        # fail when no LLM credentials are configured.
        self._llm: LLMClient | None = llm
        self._reflector: Reflector | None = None
        self._advisor: Advisor | None = None
        # Resume any deferred host-backend reflections from a previous run.
        # Best-effort — never blocks startup.
        try:
            if self._has_pending_deferred() and not self.is_paused():
                self.reflector.resume_pending()
        except EvolError as e:
            _log.warning("resume_pending failed", extra={"err": str(e)})

    # ─── factory ───

    @classmethod
    def from_config(
        cls,
        path: str | Path = "evol.config.yaml",
        *,
        root: str | Path | None = None,
        llm: LLMClient | None = None,
    ) -> Evol:
        cfg_path = Path(path)
        config = load_config(cfg_path)
        # If root not given, treat the config file's directory as the project
        # root (so .evol/ lives next to evol.config.yaml).
        proj_root = Path(root) if root else cfg_path.resolve().parent
        return cls(config=config, root=proj_root, llm=llm)

    # ─── lazy LLM & Reflector accessors ───

    @property
    def llm(self) -> LLMClient:
        """Resolve the LLM backend on first access.

        Built lazily so projects that don't reflect (e.g. only use enhance)
        don't need API credentials at startup.
        """
        if self._llm is None:
            self._llm = detect_backend(self.config, evol_root=self.evol_dir)
        return self._llm

    @property
    def reflector(self) -> Reflector:
        if self._reflector is None:
            anchors = parse_anchors(self.config.anchors)
            self._reflector = Reflector(
                config=self.config,
                evol_root=self.evol_dir,
                llm=self.llm,
                anchors=anchors,
                recorder=self.recorder,
                memory_store=self.memory_store,
                manifest_store=self.manifest_store,
                snapshot_manager=self.snapshot_manager,
            )
        return self._reflector

    @property
    def advisor(self) -> Advisor:
        if self._advisor is None:
            anchors = parse_anchors(self.config.anchors)
            self._advisor = Advisor(
                config=self.config,
                evol_root=self.evol_dir,
                llm=self.llm,
                anchors=anchors,
                memory_store=self.memory_store,
                recorder=self.recorder,
            )
        return self._advisor

    def _has_pending_deferred(self) -> bool:
        deferred_dir = self.evol_dir / "deferred"
        if not deferred_dir.is_dir():
            return False
        return any(deferred_dir.glob("*.state.json"))

    # ─── pause / resume ───

    @property
    def paused_marker(self) -> Path:
        return self.evol_dir / _PAUSE_FILE

    def pause(self) -> None:
        self.paused_marker.touch()

    def resume(self) -> None:
        if self.paused_marker.exists():
            self.paused_marker.unlink()

    def is_paused(self) -> bool:
        return self.paused_marker.exists()

    # ─── state inspection ───

    def state(self) -> EvolState:
        manifest = self.manifest_store.read()
        experience_count = self.recorder.count()
        reflected_experience_count = int(
            manifest.experiences.get("reflected_count", manifest.experiences.get("count", 0))
        ) if manifest.experiences else 0
        return EvolState(
            protocol_version=manifest.protocol_version,
            product_name=str(manifest.product.get("name", "")),
            product_version=str(manifest.product.get("version", "")),
            memory_version=int(manifest.memory.get("current_version", 0)),
            memory_checksum=str(manifest.memory.get("checksum", "")),
            experience_count=experience_count,
            reflected_experience_count=reflected_experience_count,
            paused=self.is_paused(),
            snapshot_versions=self.snapshot_manager.list_versions(),
            last_reflection_id=(manifest.last_reflection or {}).get("id") if manifest.last_reflection else None,
            last_reflection_at=(manifest.last_reflection or {}).get("performed_at") if manifest.last_reflection else None,
        )

    # ─── private: bootstrap & validation ───

    def _validate_or_initialize(self) -> None:
        """Ensure ``.evol/`` is initialized and consistent.

        - If ``.evol/`` is missing or empty: bootstrap with empty memory + snapshot v0.
        - Otherwise: validate protocol_version + checksum (CONTRACT §11).
        """
        if not self.evol_dir.exists() or not self.manifest_store.exists():
            self._bootstrap_fresh()
            return

        manifest = self.manifest_store.read()
        self._check_protocol_version(manifest)
        self._check_checksum(manifest)
        self._check_anchor_drift(manifest)

    def _bootstrap_fresh(self) -> None:
        self.evol_dir.mkdir(parents=True, exist_ok=True)
        # Step 1: create empty memory files on disk.
        self.memory_store.ensure_initialized()
        self.snapshot_manager.ensure_initialized()

        # Step 2: build the initial manifest. Its precomputed checksum is a
        # placeholder — we recompute below over the actually-persisted files
        # so timestamps line up.
        anchors = parse_anchors(self.config.anchors)
        manifest = build_initial_manifest(
            product_name=self.config.product.name,
            product_version=self.config.product.version,
            product_domain=self.config.product.domain,
            anchors=anchors,
        )

        # Step 3: recompute checksum from disk so it matches what was written.
        files = self.memory_store.load_all()
        manifest.memory = {
            **manifest.memory,
            "checksum": compute_checksum_from_memory(files),
        }
        self.manifest_store.write(manifest)

        # Step 4: take initial snapshot at v0.
        with suppress(EvolStorageError):
            self.snapshot_manager.create(0)
        # Mirror config to .evol/config.yaml
        write_runtime_copy(self.config, self.evol_dir)
        _log.info(
            "bootstrapped fresh .evol/",
            extra={"root": str(self.root), "product": self.config.product.name},
        )

    def _check_protocol_version(self, manifest: Manifest) -> None:
        if manifest.protocol_version != PROTOCOL_VERSION:
            raise EvolProtocolMismatch(
                f"this SDK speaks protocol {PROTOCOL_VERSION}, but .evol/ "
                f"manifest declares {manifest.protocol_version!r}; please run "
                "`evol migrate` (not yet available in v0.1)"
            )

    def _check_checksum(self, manifest: Manifest) -> None:
        files = self.memory_store.load_all()
        actual = compute_checksum_from_memory(files)
        recorded = str(manifest.memory.get("checksum") or "")
        if recorded and actual != recorded:
            raise EvolChecksumError(
                f"memory checksum mismatch: disk={actual} manifest={recorded}; "
                "freezing writes — investigate before continuing"
            )

    def _check_anchor_drift(self, manifest: Manifest) -> None:
        current = parse_anchors(self.config.anchors)
        drift = detect_anchor_drift(current, manifest.anchors)
        if not drift:
            return
        _log.warning(
            "anchor drift detected — taking forced snapshot",
            extra={"drifted_indices": drift},
        )
        # Take a snapshot of current memory before the new anchors take effect
        # (CONTRACT §13 A-4).
        latest = self.snapshot_manager.latest_version() or 0
        with suppress(EvolStorageError):
            self.snapshot_manager.create(latest + 1)
        # Update manifest's anchor view to current.
        manifest.anchors = current
        self.manifest_store.write(manifest)


__all__ = ["Evol", "EvolState"]
