"""EVOL exception hierarchy.

All EVOL-raised exceptions inherit from :class:`EvolError`. Specific subclasses
help downstream callers (CLI, integrations) recover or surface user-facing
messages without inspecting strings.
"""

from __future__ import annotations


class EvolError(Exception):
    """Base class for all EVOL exceptions."""


class EvolConfigError(EvolError):
    """Raised when ``evol.config.yaml`` is missing, malformed, or schema-invalid."""


class EvolProtocolMismatch(EvolError):
    """Raised when a ``.evol/`` directory's ``protocol_version`` is incompatible
    with this SDK build."""


class EvolChecksumError(EvolError):
    """Raised when the on-disk Memory checksum does not match the recorded one
    in ``manifest.yaml``."""


class EvolLockError(EvolError):
    """Raised on lock contention timeout or invalid lock-file state."""


class EvolLLMError(EvolError):
    """Generic wrapper for upstream LLM provider failures (timeout, network,
    auth, malformed response, etc.)."""


class EvolParseError(EvolError):
    """Raised when LLM output (or a deferred completed_response) cannot be
    parsed into the expected schema."""


class EvolStorageError(EvolError):
    """Raised on filesystem errors that prevent EVOL from making forward
    progress (disk full, permission denied, etc.)."""


__all__ = [
    "EvolError",
    "EvolConfigError",
    "EvolProtocolMismatch",
    "EvolChecksumError",
    "EvolLockError",
    "EvolLLMError",
    "EvolParseError",
    "EvolStorageError",
]
