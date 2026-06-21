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
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog

from app.config import get_settings


def _force_utf8_streams() -> None:
    """
    Make stdout/stderr UTF-8.

    structlog prints to stdout, and prompts/labels contain non-ASCII characters
    (e.g. "≤", the "–" en dash in enrollment buckets). On Windows the default
    console encoding is cp1252, which raises UnicodeEncodeError on those — which
    would otherwise surface as a request failure. Reconfiguring is a no-op on
    platforms/streams that are already UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


def _make_timestamper(tz_name: str):
    """Stamp each record with a localized ISO-8601 timestamp."""
    tz = ZoneInfo(tz_name)

    def timestamper(_logger, _method_name, event_dict):
        event_dict["timestamp"] = datetime.now(tz).isoformat(timespec="milliseconds")
        return event_dict

    return timestamper


def configure_logging() -> None:
    settings = get_settings()
    _force_utf8_streams()
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
