"""AI 资讯只读 API 与页面路由（挂载到现有 FastAPI 应用）。"""

from __future__ import annotations

import asyncio
import re
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from web.news.config import (
    CATEGORY_LABELS,
    NewsSettings,
    source_metadata,
    sources_for_settings,
)
from web.news.models import NewsItem
from web.news.repository import NewsRepository

router = APIRouter()

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_repo_cache: dict[str, NewsRepository] = {}
_repo_lock = threading.Lock()


def get_news_repository() -> NewsRepository:
    """按当前配置的数据库路径获取仓储单例（路径变化时重建）。"""
    settings = NewsSettings.from_env()
    key = str(settings.database_path)
    with _repo_lock:
        repo = _repo_cache.get(key)
        if repo is None:
            repo = NewsRepository(settings.database_path)
            _repo_cache[key] = repo
        return repo


def _serialize_item(item: NewsItem) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "summary": item.summary,
        "source_id": item.source_id,
        "source_name": item.source_name,
        "url": item.url,
        "published_at": item.published_at.isoformat(),
        "fetched_at": item.fetched_at.isoformat(),
        "category": item.category,
        "category_label": CATEGORY_LABELS.get(item.category, item.category),
        "tags": item.tags,
        "importance_score": item.importance_score,
        "source_count": item.source_count,
        "summary_status": item.summary_status,
        **source_metadata(item.source_id),
    }


def _enabled_source_ids(settings: NewsSettings | None = None) -> list[str]:
    settings = settings or NewsSettings.from_env()
    return [source.source_id for source in sources_for_settings(settings)]


def _limit_daily_source_share(items: list[dict], per_source_limit: int) -> list[dict]:
    """日报中限制单一来源的最大占比，保留各源最新的条目。"""
    counts: dict[str, int] = {}
    selected: list[dict] = []
    for item in sorted(items, key=lambda row: row["published_at"], reverse=True):
        source_id = item["source_id"]
        if counts.get(source_id, 0) >= per_source_limit:
            continue
        counts[source_id] = counts.get(source_id, 0) + 1
        selected.append(item)
    return selected


def _select_featured(items: list[dict], limit: int = 10) -> list[dict]:
    """精选优先交叉验证与高信誉源，且每个来源最多两条。"""
    ranked = sorted(
        items,
        key=lambda item: (
            item["source_count"] > 1,
            item["a_share_relevance"],
            item["authority_score"],
            item["source_count"],
            item["importance_score"],
            item["published_at"],
        ),
        reverse=True,
    )
    counts: dict[str, int] = {}
    selected: list[dict] = []
    for item in ranked:
        source_id = item["source_id"]
        if counts.get(source_id, 0) >= 2:
            continue
        counts[source_id] = counts.get(source_id, 0) + 1
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _parse_since(raw: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="since 参数需要 ISO 8601 时间格式") from exc
    return parsed


class NewsListResponse(BaseModel):
    items: list[dict]
    next_cursor: str | None = None


@router.get("/news", include_in_schema=False)
async def news_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "news.html")


@router.get("/api/news")
async def list_news(
    category: str = Query(default="", max_length=40),
    source: str = Query(default="", max_length=40),
    q: str = Query(default="", max_length=100),
    since: str = Query(default="", max_length=40),
    limit: int = Query(default=30, ge=1, le=100),
    cursor: str = Query(default="", max_length=200),
) -> NewsListResponse:
    if category and category not in CATEGORY_LABELS:
        raise HTTPException(status_code=400, detail="未知的资讯分类")
    repo = get_news_repository()
    enabled_source_ids = _enabled_source_ids()
    try:
        items, next_cursor = await asyncio.to_thread(
            repo.list_items,
            category=category or None,
            source=source or None,
            query=q or None,
            since=_parse_since(since) if since else None,
            cursor=cursor or None,
            limit=limit,
            source_ids=enabled_source_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = [_serialize_item(item) for item in items]
    return NewsListResponse(items=payload, next_cursor=next_cursor)


@router.get("/api/news/categories")
async def news_categories() -> dict:
    repo = get_news_repository()
    stats = {
        row["category"]: row
        for row in await asyncio.to_thread(repo.category_stats, _enabled_source_ids())
    }
    categories = [
        {
            "key": key,
            "label": label,
            "count": int(stats[key]["count"]) if key in stats else 0,
            "latest_published_at": stats[key]["latest"] if key in stats else None,
        }
        for key, label in CATEGORY_LABELS.items()
        if key != "other"
    ]
    other = stats.get("other")
    categories.append(
        {
            "key": "other",
            "label": CATEGORY_LABELS["other"],
            "count": int(other["count"]) if other else 0,
            "latest_published_at": other["latest"] if other else None,
        }
    )
    return {"categories": categories}


@router.get("/api/news/days")
async def news_days(limit: int = Query(default=30, ge=1, le=60)) -> dict:
    """近 N 个有数据的天（北京时间），用于日报日期选择条。"""
    repo = get_news_repository()
    days = await asyncio.to_thread(repo.day_stats, limit, _enabled_source_ids())
    return {"days": days}


@router.get("/api/news/digest")
async def news_digest(
    date: str = Query(..., max_length=10, description="北京时间日期 YYYY-MM-DD"),
) -> dict:
    """某天的 AI 日报：精选条目（热度 top）+ 按分类全量。"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
        raise HTTPException(status_code=400, detail="date 参数格式应为 YYYY-MM-DD")
    repo = get_news_repository()
    settings = NewsSettings.from_env()
    try:
        items = await asyncio.to_thread(repo.list_day_items, date, _enabled_source_ids(settings))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    serialized = _limit_daily_source_share(
        [_serialize_item(item) for item in items],
        settings.max_items_per_source_per_day,
    )
    featured = _select_featured(serialized)
    by_category: dict[str, list[dict]] = {}
    for item in serialized:
        by_category.setdefault(item["category"], []).append(item)

    return {
        "date": date,
        "total": len(serialized),
        "featured": featured,
        "by_category": by_category,
    }


@router.get("/api/news/sources")
async def news_sources() -> dict:
    """公开的来源健康信息（不含内部堆栈或敏感配置）。"""
    repo = get_news_repository()
    rows = await asyncio.to_thread(repo.list_source_health)
    enabled_source_ids = set(_enabled_source_ids())
    sources = [
        {
            "source_id": s.source_id,
            "name": s.name,
            "enabled": s.enabled,
            "last_success_at": s.last_success_at,
            "last_attempt_at": s.last_attempt_at,
            "last_duration_ms": s.last_duration_ms,
            "consecutive_failures": s.consecutive_failures,
            "last_error": s.last_error,
            **source_metadata(s.source_id),
        }
        for s in rows
        if s.source_id in enabled_source_ids
    ]
    return {"sources": sources}


@router.get("/api/news/health")
async def news_health() -> dict:
    settings = NewsSettings.from_env()
    repo = get_news_repository()
    enabled_source_ids = _enabled_source_ids(settings)
    heartbeat = await asyncio.to_thread(repo.get_kv, "worker_heartbeat")
    heartbeat_age: float | None = None
    if heartbeat:
        try:
            heartbeat_age = (
                datetime.now().astimezone() - datetime.fromisoformat(heartbeat)
            ).total_seconds()
        except ValueError:
            heartbeat_age = None
    tolerance = max(settings.fetch_interval_minutes * 60 * 3, 900)
    worker_alive = heartbeat_age is not None and heartbeat_age <= tolerance
    latest_run = await asyncio.to_thread(repo.latest_run)
    items_total = await asyncio.to_thread(repo.count_items, True, enabled_source_ids)
    last_fetched = await asyncio.to_thread(repo.latest_item_time, enabled_source_ids)
    return {
        "enabled": settings.enabled,
        "database": "ok",
        "items_total": items_total,
        "last_fetched_at": last_fetched,
        "last_run": latest_run,
        "worker_heartbeat": heartbeat,
        "worker_heartbeat_age_seconds": heartbeat_age,
        "worker_alive": worker_alive,
        "status": "ok" if worker_alive or latest_run else "degraded",
    }
