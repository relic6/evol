"""Cross-platform advisory file lock.

CONTRACT §9 / §12 require SDKs to use OS-level advisory file locks for
``experiences.jsonl`` writes and ``locks/reflection.lock``. We wrap
``portalocker`` to provide a uniform context manager that works on POSIX
(via ``fcntl``) and Windows (via ``msvcrt``).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import portalocker
from portalocker.exceptions import LockException

from evol.errors import EvolLockError


@contextmanager
def file_lock(
    path: str | Path,
    *,
    exclusive: bool = True,
    timeout: float = 5.0,
) -> Iterator[None]:
    """Acquire an advisory lock on ``path``, yield, release.

    Args:
        path: lock file path. The file is created if missing; its content
            is irrelevant — only the lock matters.
        exclusive: ``True`` for an exclusive (write) lock; ``False`` for a
            shared (read) lock.
        timeout: seconds to wait before raising :class:`EvolLockError`.

    Raises:
        EvolLockError: if the lock could not be acquired within ``timeout``,
            or if a lower-level OS error occurred. Original exception is
            chained via ``__cause__``.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch(exist_ok=True)

    flags = portalocker.LOCK_EX if exclusive else portalocker.LOCK_SH

    try:
        with p.open("a+b") as fh:
            try:
                portalocker.lock(fh, flags | portalocker.LOCK_NB)
            except LockException:
                # Fall back to a polling acquire with overall timeout.
                import time  # noqa: PLC0415

                deadline = time.monotonic() + timeout
                acquired = False
                while time.monotonic() < deadline:
                    try:
                        portalocker.lock(fh, flags | portalocker.LOCK_NB)
                        acquired = True
                        break
                    except LockException:
                        time.sleep(0.05)
                if not acquired:
                    raise EvolLockError(
                        f"timed out acquiring lock on {p} after {timeout}s"
                    ) from None
            try:
                yield
            finally:
                with suppress(OSError, LockException):
                    portalocker.unlock(fh)
    except (OSError, LockException) as e:
        raise EvolLockError(f"unable to acquire lock on {p}: {e}") from e


__all__ = ["file_lock"]
