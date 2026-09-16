"""TradingAgents 的统一日志配置。

所有模块都应通过 ``logging.getLogger(__name__)`` 获取 logger（Python 常规约定）。
本模块每个进程只配置一次处理器，使所有层（图编排、Agent、LLM 客户端、数据供应商、
Web、脚本和后台 Worker 的日志进入同一个控制台和滚动文件，便于运维将故障追溯到具体模块。

配置项（均可选，从环境变量读取）：

- ``TRADINGAGENTS_LOG_LEVEL``: one of DEBUG/INFO/WARNING/ERROR/CRITICAL
  (default INFO).
- ``TRADINGAGENTS_LOG_DIR``: directory for the daily-rotated log file
  (default ``~/.tradingagents/logs``).
- ``TRADINGAGENTS_LOG_FILE``: exact log file name inside the log dir
  (default ``tradingagents.log``).
- ``TRADINGAGENTS_LOG_RETENTION_DAYS``: number of days of rotated files to keep
  (default 3; old files are also removed when the process starts or emits a log).
- ``TRADINGAGENTS_LOG_JSON``: "1"/"true" to emit JSON lines instead of
  plain text (useful for log collectors; default off).
"""

import json
import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_DEFAULT_LOG_DIR = os.path.join(os.path.expanduser("~"), ".tradingagents", "logs")
_DEFAULT_LOG_FILE = "tradingagents.log"
_DEFAULT_RETENTION_DAYS = 3

_PLAIN_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
)
_PLAIN_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _JsonFormatter(logging.Formatter):
    """最小 JSON Lines 格式化器：每条日志记录对应一个 JSON 对象。"""

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
            f"TRADINGAGENTS_LOG_LEVEL 无效：{raw!r} "
            f"（应为 DEBUG/INFO/WARNING/ERROR/CRITICAL）"
        )
    return level


def _log_dir() -> Path:
    base = os.environ.get("TRADINGAGENTS_LOG_DIR") or _DEFAULT_LOG_DIR
    path = Path(base).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _retention_days() -> int:
    try:
        return max(
            1,
            int(os.environ.get("TRADINGAGENTS_LOG_RETENTION_DAYS", _DEFAULT_RETENTION_DAYS)),
        )
    except ValueError:
        return _DEFAULT_RETENTION_DAYS


class _DailyRetentionFileHandler(TimedRotatingFileHandler):
    """按天轮转，并按文件实际修改时间清理过期日志。

    ``TimedRotatingFileHandler`` 只有在有新日志写入时才会触发轮转。这里额外在
    启动和每次写入前清理超过保留期的轮转文件，避免旧文件长期留在持久化卷中。
    每个服务使用独立日志目录，因此不会发生 Web 与 Worker 轮转同一个文件的问题。
    """

    def __init__(self, filename: str | os.PathLike, retention_days: int) -> None:
        self._retention_seconds = retention_days * 24 * 60 * 60
        super().__init__(
            filename,
            when="midnight",
            interval=1,
            backupCount=retention_days,
            encoding="utf-8",
            utc=False,
        )
        self._remove_expired_files()

    def _remove_expired_files(self) -> None:
        cutoff = time.time() - self._retention_seconds
        base_path = Path(self.baseFilename)
        for candidate in base_path.parent.glob(f"{base_path.name}.*"):
            try:
                if candidate.is_file() and candidate.stat().st_mtime < cutoff:
                    candidate.unlink()
            except FileNotFoundError:
                # Another cleanup or the timed rollover removed it already.
                continue
            except OSError:
                # A failed cleanup must not prevent the application from starting
                # or emitting the current log record.
                continue

    def emit(self, record: logging.LogRecord) -> None:
        self._remove_expired_files()
        try:
            super().emit(record)
        finally:
            # A rollover may have just created an old-dated backup; clean again
            # so the retention boundary is applied in the same write.
            self._remove_expired_files()


def _setup_file_handler() -> logging.Handler:
    log_dir = _log_dir()
    log_file = os.environ.get("TRADINGAGENTS_LOG_FILE") or _DEFAULT_LOG_FILE
    return _DailyRetentionFileHandler(log_dir / log_file, _retention_days())


def setup_logging() -> None:
    """为根 logger 配置控制台和按天轮转的文件处理器。

    该操作幂等：重复调用（模块重新导入或多个入口）不会堆叠重复处理器。
    返回配置的日志级别，调用方可在启动时报告一次。
    """
    root = logging.getLogger()
    level = _log_level()

    if os.environ.get("TRADINGAGENTS_LOG_JSON", "").strip().lower() in ("1", "true", "yes"):
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(_PLAIN_FORMAT, datefmt=_PLAIN_DATE_FORMAT)

    # 某些入口（例如 Uvicorn 或第三方 CLI）可能已经给 root logger 加了
    # handler。不能因为已有 handler 就跳过文件日志，否则同一个进程的日志
    # 会时有时无；同时要复用已有控制台 handler，避免重复打印。
    console = next(
        (
            handler
            for handler in root.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        ),
        None,
    )
    if console is None:
        console = logging.StreamHandler()
        root.addHandler(console)

    file_handler = next(
        (
            handler
            for handler in root.handlers
            if getattr(handler, "_tradingagents_file_handler", False)
        ),
        None,
    )
    if file_handler is None:
        file_handler = _setup_file_handler()
        file_handler._tradingagents_file_handler = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

    for handler in (console, file_handler):
        handler.setFormatter(formatter)
        handler.setLevel(level)
        handler._tradingagents_configured = True  # type: ignore[attr-defined]

    root.setLevel(level)
    # 外部 HTTP 客户端的逐请求信息，以及 Uvicorn 的访问日志（尤其是
    # /health 和 /metrics 的探活请求）不是业务操作日志，默认不写入日志。
    for noisy_logger in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    return level
