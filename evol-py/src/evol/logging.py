"""Structured logging for EVOL.

All EVOL log records go through ``get_logger("evol.<module>")``. Records can
optionally carry structured fields via ``extra={...}``; downstream applications
can attach a JSON formatter for production log pipelines.

By default, a NullHandler is attached so importing EVOL does not produce
output unless the host application configures logging.
"""

from __future__ import annotations

import json
import logging
from typing import Any

_BASE_NAME = "evol"
_RESERVED_LOGRECORD_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


def get_logger(name: str = _BASE_NAME) -> logging.Logger:
    """Return a logger under the ``evol.*`` namespace.

    Callers should use ``get_logger("evol.recorder")``, ``get_logger("evol.reflector")``
    etc. so users can selectively raise / lower log levels per module.
    """
    if not name.startswith(_BASE_NAME):
        name = f"{_BASE_NAME}.{name}" if name != _BASE_NAME else name
    return logging.getLogger(name)


class JsonFormatter(logging.Formatter):
    """Formatter that emits one JSON object per record.

    Useful for production log pipelines. Reserved LogRecord attributes are
    dropped; arbitrary structured fields passed via ``extra={...}`` are merged
    into the output object.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_KEYS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_default_handler(
    *,
    level: int = logging.INFO,
    json_output: bool = False,
) -> None:
    """Attach a default StreamHandler to the root EVOL logger.

    This is opt-in — applications that already configure logging should not
    call this. Useful for examples and the EVOL CLI.
    """
    root = logging.getLogger(_BASE_NAME)
    root.setLevel(level)
    handler: logging.Handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter()
        if json_output
        else logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    # Prevent duplicate handlers on re-configuration:
    root.handlers = [h for h in root.handlers if not isinstance(h, logging.StreamHandler)]
    root.addHandler(handler)


# Default: NullHandler so importing EVOL never produces stray output.
logging.getLogger(_BASE_NAME).addHandler(logging.NullHandler())


__all__ = ["JsonFormatter", "configure_default_handler", "get_logger"]
