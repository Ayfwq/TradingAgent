"""AI 资讯模块的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class RawEntry:
    """源适配器返回的标准化条目（未去重、未分类）。"""

    title: str
    url: str
    summary: str = ""
    published_at: datetime | None = None
    language: str = "en"


@dataclass
class FetchOutcome:
    """一次源抓取的原始结果。"""

    entries: list[RawEntry] = field(default_factory=list)
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


@dataclass
class NewsItem:
    """待入库的资讯条目。"""

    source_id: str
    source_name: str
    title: str
    url: str
    canonical_url: str
    id: int = 0  # 入库后由仓储回填
    original_summary: str = ""
    summary: str = ""
    published_at: datetime | None = None
    fetched_at: datetime = field(default_factory=utc_now)
    category: str = "other"
    tags: list[str] = field(default_factory=list)
    language: str = "en"
    title_hash: str = ""
    content_hash: str = ""
    importance_score: int = 0
    summary_status: str = "rss"          # ai / rss / title
    source_count: int = 1
    duplicate_of_id: int | None = None


@dataclass
class SourceHealth:
    source_id: str
    name: str
    url: str
    enabled: bool
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_duration_ms: int | None = None
    consecutive_failures: int = 0
    last_error: str | None = None
    last_items_count: int | None = None


@dataclass
class FetchRunStats:
    source_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str = "running"              # ok / error
    new_count: int = 0
    duplicate_count: int = 0
    filtered_count: int = 0
    ai_count: int = 0
    error: str | None = None
    duration_ms: int | None = None
