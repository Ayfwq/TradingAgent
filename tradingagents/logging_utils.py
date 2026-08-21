"""Unified logging configuration for TradingAgents.

All modules should obtain a logger via ``logging.getLogger(__name__)``
(normal Python convention). This module wires up the handlers once per
process, so logs from every layer (graph orchestration, agents, LLM
clients, data vendors, CLI) land in the same console + rolling file sink,
which is what operations needs to trace a failure back to a module.

Configuration knobs (all optional, read from environment):

- ``TRADINGAGENTS_LOG_LEVEL``: one of DEBUG/INFO/WARNING/ERROR/CRITICAL
  (default INFO).
- ``TRADINGAGENTS_LOG_DIR``: directory for the rolling log file
  (default ``~/.tradingagents/logs``, same base as results_dir).
- ``TRADINGAGENTS_LOG_FILE``: exact log file name inside the log dir
  (default ``tradingagents.log``).
- ``TRADINGAGENTS_LOG_MAX_BYTES``: per-file size cap before rotation
  (default 20 MiB).
- ``TRADINGAGENTS_LOG_BACKUP_COUNT``: rotated files kept (default 7).
- ``TRADINGAGENTS_LOG_JSON``: "1"/"true" to emit JSON lines instead of
  plain text (useful for log collectors; default off).
"""

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_DEFAULT_LOG_DIR = os.path.join(os.path.expanduser("~"), ".tradingagents", "logs")
_DEFAULT_LOG_FILE = "tradingagents.log"
_DEFAULT_MAX_BYTES = 20 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 7

_PLAIN_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
)
_PLAIN_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _JsonFormatter(logging.Formatter):
    """Minimal JSON-lines formatter: one JSON object per log record."""

    def format(self, record):
        payload = {
            "ts": self.formatTime(record, _PLAIN_DATE_FORMAT),
            "level": record.levelname,
            "logger": record.name,
            "func": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _log_level() -> int:
    raw = os.environ.get("TRADINGAGENTS_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, raw, None)
    if not isinstance(level, int):
        raise ValueError(
            f"Invalid TRADINGAGENTS_LOG_LEVEL: {raw!r} "
            f"(expected DEBUG/INFO/WARNING/ERROR/CRITICAL)"
        )
    return level


def _log_dir() -> Path:
    base = os.environ.get("TRADINGAGENTS_LOG_DIR") or _DEFAULT_LOG_DIR
    path = Path(base).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _setup_file_handler() -> logging.Handler:
    log_dir = _log_dir()
    log_file = os.environ.get("TRADINGAGENTS_LOG_FILE") or _DEFAULT_LOG_FILE
    try:
        max_bytes = int(os.environ.get("TRADINGAGENTS_LOG_MAX_BYTES", _DEFAULT_MAX_BYTES))
        backup_count = int(
            os.environ.get("TRADINGAGENTS_LOG_BACKUP_COUNT", _DEFAULT_BACKUP_COUNT)
        )
    except ValueError:
        max_bytes = _DEFAULT_MAX_BYTES
        backup_count = _DEFAULT_BACKUP_COUNT

    handler = RotatingFileHandler(
        log_dir / log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    return handler


def setup_logging() -> None:
    """Configure the root logger with console + rotating-file handlers.

    Idempotent: repeated calls (module re-import, multiple entry points)
    never stack duplicate handlers. Returns the configured level so callers
    can report it once at startup.
    """
    root = logging.getLogger()
    level = _log_level()

    if root.handlers:
        root.setLevel(level)
        for handler in root.handlers:
            if getattr(handler, "_tradingagents_configured", False):
                handler.setLevel(level)
        return level

    console = logging.StreamHandler()
    file_handler = _setup_file_handler()

    if os.environ.get("TRADINGAGENTS_LOG_JSON", "").strip().lower() in ("1", "true", "yes"):
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(_PLAIN_FORMAT, datefmt=_PLAIN_DATE_FORMAT)

    for handler in (console, file_handler):
        handler.setFormatter(formatter)
        handler.setLevel(level)
        handler._tradingagents_configured = True  # type: ignore[attr-defined]

    root.addHandler(console)
    root.addHandler(file_handler)
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return level
