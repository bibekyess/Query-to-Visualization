"""
structlog configuration — call `configure_logging()` once at process startup.

Renderer is chosen by the `debug` setting: a human-readable ConsoleRenderer for
local development, machine-readable JSON otherwise. `log_level` gates which
records are emitted and `log_timezone` controls the timestamp on every line.

Modules log via `structlog.get_logger(__name__)`; structlog falls back to sane
defaults if `configure_logging()` was never called (e.g. in unit tests), so this
module is only required for the running app.
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog

from app.config import get_settings


def _make_timestamper(tz_name: str):
    """Stamp each record with a localized ISO-8601 timestamp."""
    tz = ZoneInfo(tz_name)

    def timestamper(_logger, _method_name, event_dict):
        event_dict["timestamp"] = datetime.now(tz).isoformat(timespec="milliseconds")
        return event_dict

    return timestamper


def configure_logging() -> None:
    settings = get_settings()
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            _make_timestamper(settings.log_timezone),
            structlog.dev.ConsoleRenderer()
            if settings.debug
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
