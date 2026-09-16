from __future__ import annotations

import logging
import os
import time

from tradingagents.logging_utils import _DailyRetentionFileHandler


def test_daily_handler_removes_rotated_files_older_than_retention(tmp_path):
    handler = _DailyRetentionFileHandler(tmp_path / "tradingagents.log", retention_days=3)
    try:
        expired = tmp_path / "tradingagents.log.2026-01-01"
        recent = tmp_path / "tradingagents.log.2026-01-02"
        expired.write_text("expired", encoding="utf-8")
        recent.write_text("recent", encoding="utf-8")
        old_timestamp = time.time() - (4 * 24 * 60 * 60)
        os.utime(expired, (old_timestamp, old_timestamp))

        handler._remove_expired_files()

        assert not expired.exists()
        assert recent.exists()
    finally:
        handler.close()


def test_daily_handler_rotates_at_midnight_and_keeps_three_backups(tmp_path):
    handler = _DailyRetentionFileHandler(tmp_path / "tradingagents.log", retention_days=3)
    try:
        assert handler.when == "MIDNIGHT"
        assert handler.interval == 24 * 60 * 60
        assert handler.backupCount == 3
        handler.emit(logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="operation completed",
            args=(),
            exc_info=None,
        ))
        assert (tmp_path / "tradingagents.log").read_text(encoding="utf-8").endswith(
            "operation completed\n"
        )
    finally:
        handler.close()
