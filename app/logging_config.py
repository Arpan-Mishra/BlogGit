"""
Structured logging configuration for Blog Copilot.

In production (DEBUG=false) logs are emitted as JSON so they can be ingested
by Railway / Fly.io log collectors and forwarded to Datadog, Papertrail, etc.
In debug mode (DEBUG=true) a human-readable format is used instead.

Usage:
    from app.logging_config import configure_logging
    configure_logging(debug=settings.debug)   # call once at app startup
"""

import logging
import logging.config
import sys
from typing import Any


# ---------------------------------------------------------------------------
# JSON formatter (production)
# ---------------------------------------------------------------------------


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object.

    Fields emitted: timestamp, level, logger, message, and any extra kwargs
    added via the ``extra=`` parameter of the log call.
    """

    def format(self, record: logging.LogRecord) -> str:
        import json
        import traceback

        payload: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exc"] = record.exc_text

        # Attach any extra fields the caller added via extra={...}
        skip = logging.LogRecord.__dict__.keys() | {
            "message", "asctime", "args", "exc_info", "exc_text", "stack_info",
        }
        for key, value in record.__dict__.items():
            if key not in skip:
                try:
                    json.dumps(value)  # verify serialisable
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)

        return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_logging(*, debug: bool = False) -> None:
    """Configure the root logger for Blog Copilot.

    Parameters
    ----------
    debug:
        When True, use a human-readable format at DEBUG level.
        When False (production), emit JSON at INFO level.
    """
    level = logging.DEBUG if debug else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    if debug:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    else:
        handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    # Remove any handlers already attached (e.g. by uvicorn before our call)
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy third-party loggers that spam at DEBUG
    for noisy in ("httpx", "httpcore", "hpack", "langsmith"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
