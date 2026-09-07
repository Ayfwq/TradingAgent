"""定时调度器：抓取、重试、来源隔离、心跳与保留期清理。"""

from __future__ import annotations

import logging
import random
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from web.metrics import (
    NEWS_AI_SUMMARIES_TOTAL,
    NEWS_ENABLED_SOURCES,
    NEWS_FETCH_DURATION_SECONDS,
    NEWS_FETCH_RUNS_TOTAL,
    NEWS_ITEMS_IN_DB,
    NEWS_ITEMS_TOTAL,
    NEWS_SOURCE_DURATION_SECONDS,
    NEWS_SOURCE_RESULTS_TOTAL,
    NEWS_WORKER_HEARTBEAT_AGE_SECONDS,
)
from web.news.config import NewsSettings, SourceConfig
from web.news.models import FetchRunStats, utc_now
from web.news.pipeline import AISummarizer, build_item, persist_item
from web.news.repository import NewsRepository
from web.news.sources import SourceAdapter, SourceError, build_adapter

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3          # 1 次初始 + 2 次重试
JITTER_SECONDS = 3.0
HEARTBEAT_KEY = "worker_heartbeat"


class NewsScheduler:
    def __init__(
        self,
        settings: NewsSettings,
        repo: NewsRepository,
        sources: list[SourceConfig] | None = None,
        adapter_factory=None,
        summarizer: AISummarizer | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.sources = sources or []
        self._adapter_factory = adapter_factory or build_adapter
        self.summarizer = summarizer or AISummarizer(settings)
        self._stop_event = threading.Event()
        for source in self.sources:
            self.repo.upsert_source(
                source.source_id, source.name, source.url,
                source.enabled, source.interval_minutes,
            )
        # 记录启用的来源数量
        NEWS_ENABLED_SOURCES.set(len([s for s in self.sources if s.enabled]))

    # ------------------------------------------------------------------

    def heartbeat(self) -> None:
        self.repo.set_kv(HEARTBEAT_KEY, utc_now().isoformat())

    def heartbeat_age_seconds(self) -> float | None:
        value = self.repo.get_kv(HEARTBEAT_KEY)
        if not value:
            return None
        try:
            stamp = datetime.fromisoformat(value)
        except ValueError:
            return None
        return (utc_now() - stamp).total_seconds()

    def _is_due(self, source: SourceConfig) -> bool:
        interval = source.interval_minutes or self.settings.fetch_interval_minutes
        last_attempt = self.repo.get_last_attempt_at(source.source_id)
        if last_attempt is None:
            return True
        return utc_now() - last_attempt >= timedelta(minutes=interval)

    def run_once(self) -> dict:
        """执行一轮采集：来源并发、单源失败不影响其他来源。"""
        self.heartbeat()
        started = time.monotonic()
        due_sources = [s for s in self.sources if s.enabled and self._is_due(s)]
        summary = {
            "due_sources": len(due_sources),
            "sources_ok": 0,
            "sources_failed": 0,
            "new_items": 0,
            "duplicates": 0,
            "filtered": 0,
            "ai_summaries": 0,
        }
        if not due_sources:
            NEWS_FETCH_RUNS_TOTAL.labels(status="empty").inc()
            return summary

        ai_budget = [self.settings.ai_max_items_per_run]
        with ThreadPoolExecutor(
            max_workers=min(self.settings.max_concurrency, len(due_sources))
        ) as executor:
            futures = {
                executor.submit(self._process_source, source, ai_budget): source
                for source in due_sources
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001  理论上已隔离，兜底
                    logger.exception("Source %s crashed unexpectedly", source.source_id)
                    result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                if result.get("ok"):
                    summary["sources_ok"] += 1
                else:
                    summary["sources_failed"] += 1
                summary["new_items"] += result.get("new_count", 0)
                summary["duplicates"] += result.get("duplicate_count", 0)
                summary["filtered"] += result.get("filtered_count", 0)
                summary["ai_summaries"] += result.get("ai_count", 0)

        self.repo.prune(self.settings.retention_days)
        self.heartbeat()
        duration = time.monotonic() - started
        # 更新 Prometheus 指标
        NEWS_FETCH_DURATION_SECONDS.observe(duration)
        NEWS_FETCH_RUNS_TOTAL.labels(status="ok").inc()
        NEWS_ITEMS_TOTAL.labels(disposition="new").inc(summary["new_items"])
        NEWS_ITEMS_TOTAL.labels(disposition="duplicate").inc(summary["duplicates"])
        NEWS_ITEMS_TOTAL.labels(disposition="filtered").inc(summary["filtered"])
        NEWS_AI_SUMMARIES_TOTAL.labels(status="generated").inc(summary["ai_summaries"])
        # 更新数据库中的条目数
        try:
            enabled_ids = [s.source_id for s in self.sources if s.enabled]
            NEWS_ITEMS_IN_DB.set(self.repo.count_items(True, enabled_ids))
        except Exception:  # noqa: BLE001
            pass
        logger.info(
            "News cycle done in %.1fs: %d ok / %d failed, +%d new, %d dup, %d filtered, %d AI",
            duration,
            summary["sources_ok"], summary["sources_failed"],
            summary["new_items"], summary["duplicates"], summary["filtered"],
            summary["ai_summaries"],
        )
        return summary

    # ------------------------------------------------------------------

    def _process_source(self, source: SourceConfig, ai_budget: list[int]) -> dict:
        """处理单个来源：抖动、重试（指数退避）、统计与状态记录。"""
        time.sleep(random.uniform(0, JITTER_SECONDS))
        adapter: SourceAdapter = self._adapter_factory(source, self.settings)
        etag, last_modified = self.repo.get_source_conditional(source.source_id)

        stats = FetchRunStats(source_id=source.source_id, started_at=utc_now())
        outcome = None
        last_error: str | None = None
        attempt_started = time.monotonic()
        for attempt in range(MAX_ATTEMPTS):
            try:
                outcome = adapter.fetch(etag=etag, last_modified=last_modified)
                last_error = None
                break
            except SourceError as exc:
                last_error = str(exc)
                logger.warning(
                    "Source %s attempt %d/%d failed: %s",
                    source.source_id, attempt + 1, MAX_ATTEMPTS, last_error,
                )
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(min(2**attempt, 8))
            except Exception as exc:  # noqa: BLE001  意外崩溃也计为一次失败尝试
                last_error = f"{type(exc).__name__}: {exc}"
                logger.exception(
                    "Source %s attempt %d/%d crashed", source.source_id, attempt + 1, MAX_ATTEMPTS,
                )
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(min(2**attempt, 8))
        duration_ms = int((time.monotonic() - attempt_started) * 1000)
        duration_seconds = (time.monotonic() - attempt_started)

        if outcome is None:
            stats.status = "error"
            stats.error = last_error
            stats.finished_at = utc_now()
            stats.duration_ms = duration_ms
            self.repo.mark_source_failure(source.source_id, last_error or "未知错误", duration_ms)
            self.repo.record_run(stats)
            # 更新 Prometheus 指标
            NEWS_SOURCE_RESULTS_TOTAL.labels(source_id=source.source_id, status="error").inc()
            NEWS_SOURCE_DURATION_SECONDS.labels(source_id=source.source_id).observe(duration_seconds)
            return {
                "ok": False, "error": last_error,
                "new_count": 0, "duplicate_count": 0, "filtered_count": 0, "ai_count": 0,
            }

        if outcome.not_modified:
            self.repo.mark_source_success(
                source.source_id, duration_ms, 0, etag, last_modified,
            )
            stats.status = "ok"
            stats.finished_at = utc_now()
            stats.duration_ms = duration_ms
            self.repo.record_run(stats)
            # 更新 Prometheus 指标
            NEWS_SOURCE_RESULTS_TOTAL.labels(source_id=source.source_id, status="not_modified").inc()
            NEWS_SOURCE_DURATION_SECONDS.labels(source_id=source.source_id).observe(duration_seconds)
            return {
                "ok": True, "not_modified": True,
                "new_count": 0, "duplicate_count": 0, "filtered_count": 0, "ai_count": 0,
            }

        for entry in outcome.entries:
            item, disposition = build_item(source, entry, self.summarizer, ai_budget)
            if disposition == "filtered":
                stats.filtered_count += 1
                continue
            result = persist_item(self.repo, source, item)
            if result.is_new:
                stats.new_count += 1
                if item.summary_status == "ai":
                    stats.ai_count += 1
            else:
                stats.duplicate_count += 1

        self.repo.mark_source_success(
            source.source_id,
            duration_ms,
            stats.new_count,
            outcome.etag,
            outcome.last_modified,
        )
        stats.status = "ok"
        stats.finished_at = utc_now()
        stats.duration_ms = duration_ms
        self.repo.record_run(stats)
        # 更新 Prometheus 指标
        NEWS_SOURCE_RESULTS_TOTAL.labels(source_id=source.source_id, status="ok").inc()
        NEWS_SOURCE_DURATION_SECONDS.labels(source_id=source.source_id).observe(duration_seconds)
        return {
            "ok": True,
            "new_count": stats.new_count,
            "duplicate_count": stats.duplicate_count,
            "filtered_count": stats.filtered_count,
            "ai_count": stats.ai_count,
        }

    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """常驻运行：启动立即执行一次，此后按间隔循环。"""
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self._request_stop)
        signal.signal(signal.SIGINT, self._request_stop)
        logger.info(
            "News worker started: %d source(s), interval=%dmin, db=%s",
            len(self.sources), self.settings.fetch_interval_minutes,
            self.settings.database_path,
        )
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("News cycle failed; continuing")
            sleep_seconds = (
                self.settings.fetch_interval_minutes * 60
                + random.uniform(0, 60)
            )
            if self._stop_event.wait(timeout=sleep_seconds):
                break
        logger.info("News worker stopped")

    def _request_stop(self, signum, frame) -> None:  # noqa: ARG002
        logger.info("Received signal %s, stopping after current cycle", signum)
        self._stop_event.set()
