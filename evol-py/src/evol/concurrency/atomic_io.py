"""Atomic file I/O and tar-archive snapshots.

CONTRACT §9 mandates write-then-rename for ``memory/`` and ``manifest.yaml``
updates. Snapshots use POSIX tar archives (Python's ``tarfile`` is fully
cross-platform — Windows decodes them too).

These helpers are deliberately small. Anything more complex belongs in
``memory.snapshot`` or ``memory.store`` where domain knowledge lives.
"""

from __future__ import annotations

import os
import tarfile
import tempfile
from contextlib import suppress
from pathlib import Path

from evol.errors import EvolStorageError


def atomic_write_text(path: str | Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write ``content`` to ``path`` atomically.

    The strategy: write a sibling ``*.tmp`` file, fsync it, then rename over
    the destination. Power loss in the middle leaves the destination either
    untouched or fully replaced — never half-written.
    """
    atomic_write_bytes(path, content.encode(encoding))


def atomic_write_bytes(path: str | Path, content: bytes) -> None:
    """Binary variant of :func:`atomic_write_text`."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=p.name + ".",
        suffix=".tmp",
        dir=str(p.parent),
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            with suppress(OSError):
                os.fsync(f.fileno())
        os.replace(tmp, p)
    except OSError as e:
        raise EvolStorageError(f"atomic write failed for {p}: {e}") from e
    finally:
        # If we crashed before the os.replace, clean up the orphan tmp file.
        if tmp.exists() and tmp != p:
            with suppress(OSError):
                tmp.unlink()


def make_snapshot_tar(src_dir: str | Path, dst_path: str | Path) -> Path:
    """Create a tar archive of ``src_dir`` at ``dst_path``.

    Uses gzip compression for compactness. The archive contains paths relative
    to ``src_dir`` (no machine-specific absolute prefixes), which keeps
    snapshots portable across machines.
    """
    src = Path(src_dir)
    if not src.is_dir():
        raise EvolStorageError(f"snapshot source is not a directory: {src}")
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=dst.name + ".",
        suffix=".tmp",
        dir=str(dst.parent),
    )
    os.close(fd)  # tarfile.open will reopen by name
    tmp = Path(tmp_name)
    try:
        with tarfile.open(tmp, "w:gz") as tar:
            for item in sorted(src.rglob("*")):
                tar.add(item, arcname=item.relative_to(src).as_posix())
        os.replace(tmp, dst)
    except (OSError, tarfile.TarError) as e:
        raise EvolStorageError(f"snapshot creation failed for {dst}: {e}") from e
    finally:
        if tmp.exists() and tmp != dst:
            with suppress(OSError):
                tmp.unlink()
    return dst


def extract_snapshot_tar(src_path: str | Path, dst_dir: str | Path) -> Path:
    """Extract a tar archive into ``dst_dir``.

    Uses ``data`` filter (Python 3.12+) when available to reject absolute
    paths and dangerous symlinks. On older Pythons we fall back to manual
    safety checks.
    """
    src = Path(src_path)
    if not src.is_file():
        raise EvolStorageError(f"snapshot file not found: {src}")
    dst = Path(dst_dir)
    dst.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(src, "r:gz") as tar:
            for member in tar.getmembers():
                _safety_check_member(member, dst)
            try:
                tar.extractall(dst, filter="data")
            except TypeError:
                # Python < 3.12 fallback (no filter kwarg)
                tar.extractall(dst)
    except (OSError, tarfile.TarError) as e:
        raise EvolStorageError(f"snapshot extraction failed for {src}: {e}") from e
    return dst


def _safety_check_member(member: tarfile.TarInfo, dst: Path) -> None:
    """Reject absolute paths and traversal attempts before extraction."""
    name = member.name
    if name.startswith("/") or ".." in Path(name).parts:
        raise EvolStorageError(f"unsafe tar member path: {name!r}")
    if member.issym() or member.islnk():
        target = member.linkname
        if target.startswith("/") or ".." in Path(target).parts:
            raise EvolStorageError(f"unsafe tar member link: {name!r} -> {target!r}")


__all__ = [
    "atomic_write_bytes",
    "atomic_write_text",
    "extract_snapshot_tar",
    "make_snapshot_tar",
]
