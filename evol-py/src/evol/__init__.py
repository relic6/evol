"""EVOL — Where software learns to grow, and so do you.

This package is the Python reference implementation (``evol-py``) of the EVOL
framework. The user-facing API is intentionally small:

>>> from evol import Evol
>>> evol = Evol.from_config("evol.config.yaml")          # doctest: +SKIP

See README.md and the ``IMPLEMENTATION.md`` document for full documentation.
"""

from __future__ import annotations

from evol._version import PROTOCOL_VERSION, __version__
from evol.api.evol import Evol, EvolState
from evol.errors import (
    EvolChecksumError,
    EvolConfigError,
    EvolError,
    EvolLLMError,
    EvolLockError,
    EvolParseError,
    EvolProtocolMismatch,
    EvolStorageError,
)

__all__ = [
    "PROTOCOL_VERSION",
    "Evol",
    "EvolChecksumError",
    "EvolConfigError",
    "EvolError",
    "EvolLLMError",
    "EvolLockError",
    "EvolParseError",
    "EvolProtocolMismatch",
    "EvolState",
    "EvolStorageError",
    "__version__",
]
