"""news-worker 独立进程入口。

本地开发：
    python -m web.news_worker --once     # 抓取一轮后退出
    python -m web.news_worker            # 常驻定时采集

Docker/ECS：
    python -m web.news_worker            # 由 docker-compose 的 news-worker 服务调用
    python -m web.news_worker --health   # 容器健康检查
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from web.news.config import ALL_SOURCES, NewsSettings, sources_for_settings
from web.news.repository import NewsRepository
from web.news.scheduler import NewsScheduler

logger = logging.getLogger("web.news_worker")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TradingAgents AI 资讯采集 Worker")
    parser.add_argument("--once", action="store_true", help="执行一轮采集后退出")
    parser.add_argument("--health", action="store_true", help="健康检查模式：心跳新鲜则退出码 0")
    parser.add_argument("--db", default=None, help="覆盖 SQLite 数据库路径")
    parser.add_argument("--interval", type=int, default=None, help="覆盖抓取间隔（分钟）")
    parser.add_argument("--all-sources", action="store_true", help="启用包括备用源在内的全部来源")
    parser.add_argument("--no-ai-summary", action="store_true", help="关闭 AI 摘要调用，仅使用来源摘要降级运行")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _build_parser().parse_args(argv)

    settings = NewsSettings.from_env()
    if args.db:
        settings.database_path = __import__("pathlib").Path(args.db)
    if args.interval is not None:
        settings.fetch_interval_minutes = args.interval
    if args.no_ai_summary:
        settings.ai_summary_enabled = False

    if not settings.enabled:
        logger.warning("NEWS_ENABLED=false，Worker 保持待机")
        if args.health:
            return 0
        while True:
            time.sleep(3600)

    repo = NewsRepository(settings.database_path)
    scheduler = NewsScheduler(
        settings,
        repo,
        sources=ALL_SOURCES if args.all_sources else sources_for_settings(settings),
    )

    if args.health:
        age = scheduler.heartbeat_age_seconds()
        tolerance = max(settings.fetch_interval_minutes * 60 * 3, 900)
        repo.close()
        if age is None or age > tolerance:
            print(f"heartbeat stale: {age}", file=sys.stderr)
            return 1
        return 0

    try:
        if args.once:
            summary = scheduler.run_once()
            repo.close()
            logger.info("One-shot run finished: %s", summary)
            return 0 if summary["sources_failed"] == 0 else 1
        scheduler.run_forever()
    finally:
        repo.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
