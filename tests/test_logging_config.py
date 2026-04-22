"""
Tests for app/logging_config.py — configure_logging and _JsonFormatter.
"""

import json
import logging
import os
from io import StringIO
from unittest.mock import patch


class TestConfigureLogging:
    def test_debug_mode_uses_human_readable_format(self) -> None:
        from app.logging_config import configure_logging

        configure_logging(debug=True)
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert root.handlers
        formatter = root.handlers[0].formatter
        # In debug mode formatter is a plain Formatter, not _JsonFormatter
        from app.logging_config import _JsonFormatter

        assert not isinstance(formatter, _JsonFormatter)

    def test_production_mode_uses_json_formatter(self) -> None:
        from app.logging_config import _JsonFormatter, configure_logging

        configure_logging(debug=False)
        root = logging.getLogger()
        assert root.level == logging.INFO
        assert root.handlers
        assert isinstance(root.handlers[0].formatter, _JsonFormatter)

    def test_repeated_calls_do_not_accumulate_handlers(self) -> None:
        from app.logging_config import configure_logging

        configure_logging(debug=False)
        configure_logging(debug=False)
        root = logging.getLogger()
        assert len(root.handlers) == 1

    def test_noisy_loggers_silenced_at_warning(self) -> None:
        from app.logging_config import configure_logging

        configure_logging(debug=True)
        for name in ("httpx", "httpcore", "langsmith"):
            assert logging.getLogger(name).level == logging.WARNING


class TestJsonFormatter:
    def _emit(self, message: str, **extra) -> dict:
        """Emit one log record through _JsonFormatter and parse it."""
        from app.logging_config import _JsonFormatter

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(_JsonFormatter())
        logger = logging.getLogger(f"test.{__name__}.{id(self)}")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.info(message, extra=extra)
        logger.removeHandler(handler)
        return json.loads(stream.getvalue().strip())

    def test_required_fields_present(self) -> None:
        record = self._emit("hello world")
        assert "ts" in record
        assert record["level"] == "INFO"
        assert record["msg"] == "hello world"
        assert "logger" in record

    def test_extra_fields_forwarded(self) -> None:
        record = self._emit("event", session_id="abc123")
        assert record.get("session_id") == "abc123"

    def test_exception_info_included(self) -> None:
        from app.logging_config import _JsonFormatter

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(_JsonFormatter())
        logger = logging.getLogger(f"test.exc.{id(self)}")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("something failed")

        logger.removeHandler(handler)
        record = json.loads(stream.getvalue().strip())
        assert "exc" in record
        assert "ValueError" in record["exc"]

    def test_output_is_valid_json_on_every_record(self) -> None:
        for i in range(5):
            record = self._emit(f"message {i}", index=i)
            assert record["msg"] == f"message {i}"
