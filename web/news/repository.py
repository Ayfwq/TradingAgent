"""SQLite 持久化（WAL 模式）：news_items / news_sources / fetch_runs / news_kv。

设计要点（AI_NEWS_MODULE_PLAN.md 第 6、12 节）：
- 单 Worker 写、Web 进程读：WAL + busy_timeout 保证并发不炸；
- canonical_url 唯一索引做第一级去重；
- title_hash + 时间窗做第二级事件合并；
- 游标分页（published_at, id）。
"""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from web.news.models import FetchRunStats, NewsItem, SourceHealth, utc_now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    original_summary TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    published_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    tags_json TEXT NOT NULL DEFAULT '[]',
    language TEXT NOT NULL DEFAULT 'en',
    title_hash TEXT NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',
    importance_score INTEGER NOT NULL DEFAULT 0,
    summary_status TEXT NOT NULL DEFAULT 'rss',
    source_count INTEGER NOT NULL DEFAULT 1,
    duplicate_of_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_items_category ON news_items(category);
CREATE INDEX IF NOT EXISTS idx_news_items_published ON news_items(published_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_news_items_source ON news_items(source_id);
CREATE INDEX IF NOT EXISTS idx_news_items_title_hash ON news_items(title_hash);

CREATE TABLE IF NOT EXISTS news_sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    interval_minutes INTEGER,
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_duration_ms INTEGER,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    etag TEXT,
    last_modified TEXT,
    last_items_count INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fetch_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    new_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    filtered_count INTEGER NOT NULL DEFAULT 0,
    ai_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS news_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class InsertResult:
    item_id: int
    is_new: bool
    merged_into_id: int | None = None


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


class NewsRepository:
    """线程安全的 SQLite 存取层。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # kv（Worker 心跳等）
    # ------------------------------------------------------------------

    def set_kv(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO news_kv(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self._conn.commit()

    def get_kv(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM news_kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    # ------------------------------------------------------------------
    # 来源健康
    # ------------------------------------------------------------------

    def upsert_source(self, source_id: str, name: str, url: str, enabled: bool, interval_minutes: int | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO news_sources(source_id, name, url, enabled, interval_minutes, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source_id) DO UPDATE SET name=excluded.name, url=excluded.url, "
                "enabled=excluded.enabled, interval_minutes=excluded.interval_minutes, "
                "updated_at=excluded.updated_at",
                (source_id, name, url, int(enabled), interval_minutes, _iso(utc_now())),
            )
            self._conn.commit()

    def get_source_conditional(self, source_id: str) -> tuple[str | None, str | None]:
        with self._lock:
            row = self._conn.execute(
                "SELECT etag, last_modified FROM news_sources WHERE source_id=?", (source_id,)
            ).fetchone()
        return (row["etag"], row["last_modified"]) if row else (None, None)

    def get_last_attempt_at(self, source_id: str) -> datetime | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_attempt_at FROM news_sources WHERE source_id=?", (source_id,)
            ).fetchone()
        if row is None or not row["last_attempt_at"]:
            return None
        try:
            return datetime.fromisoformat(row["last_attempt_at"])
        except ValueError:
            return None

    def mark_source_success(
        self,
        source_id: str,
        duration_ms: int,
        items_count: int,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE news_sources SET last_attempt_at=?, last_success_at=?, last_duration_ms=?, "
                "consecutive_failures=0, last_error=NULL, etag=?, last_modified=?, "
                "last_items_count=?, updated_at=? WHERE source_id=?",
                (_iso(utc_now()), _iso(utc_now()), duration_ms, etag, last_modified,
                 items_count, _iso(utc_now()), source_id),
            )
            self._conn.commit()

    def mark_source_failure(self, source_id: str, error: str, duration_ms: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE news_sources SET last_attempt_at=?, last_duration_ms=?, "
                "consecutive_failures=consecutive_failures+1, last_error=?, updated_at=? "
                "WHERE source_id=?",
                (_iso(utc_now()), duration_ms, error[:500], _iso(utc_now()), source_id),
            )
            self._conn.commit()

    def list_source_health(self) -> list[SourceHealth]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM news_sources ORDER BY source_id"
            ).fetchall()
        return [
            SourceHealth(
                source_id=row["source_id"],
                name=row["name"],
                url=row["url"],
                enabled=bool(row["enabled"]),
                last_attempt_at=row["last_attempt_at"],
                last_success_at=row["last_success_at"],
                last_duration_ms=row["last_duration_ms"],
                consecutive_failures=row["consecutive_failures"],
                last_error=row["last_error"],
                last_items_count=row["last_items_count"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # 采集运行记录
    # ------------------------------------------------------------------

    def record_run(self, stats: FetchRunStats) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO fetch_runs(source_id, started_at, finished_at, status, new_count, "
                "duplicate_count, filtered_count, ai_count, error, duration_ms) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    stats.source_id,
                    _iso(stats.started_at),
                    _iso(stats.finished_at) if stats.finished_at else None,
                    stats.status,
                    stats.new_count,
                    stats.duplicate_count,
                    stats.filtered_count,
                    stats.ai_count,
                    stats.error,
                    stats.duration_ms,
                ),
            )
            self._conn.commit()

    def latest_run(self) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM fetch_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # 条目写入与去重
    # ------------------------------------------------------------------

    def insert_item(self, item: NewsItem) -> InsertResult:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "INSERT INTO news_items(source_id, source_name, title, summary, original_summary, "
                    "url, canonical_url, published_at, fetched_at, category, tags_json, language, "
                    "title_hash, content_hash, importance_score, summary_status, source_count, "
                    "duplicate_of_id, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.source_id, item.source_name, item.title, item.summary,
                        item.original_summary, item.url, item.canonical_url,
                        _iso(item.published_at), _iso(item.fetched_at), item.category,
                        json.dumps(item.tags, ensure_ascii=False), item.language,
                        item.title_hash, item.content_hash, item.importance_score,
                        item.summary_status, item.source_count, item.duplicate_of_id,
                        _iso(utc_now()),
                    ),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                # canonical_url 已存在：第一级去重命中
                return InsertResult(item_id=0, is_new=False)
            new_id = int(cursor.lastrowid)
        # 第二级去重：同标题指纹 + 时间窗接近 -> 合并事件
        primary_id = self._find_title_primary(item, exclude_id=new_id)
        if primary_id:
            with self._lock:
                self._conn.execute(
                    "UPDATE news_items SET duplicate_of_id=? WHERE id=?", (primary_id, new_id)
                )
                self._conn.execute(
                    "UPDATE news_items SET source_count=source_count+1 WHERE id=?", (primary_id,)
                )
                self._conn.commit()
            return InsertResult(item_id=new_id, is_new=True, merged_into_id=primary_id)
        return InsertResult(item_id=new_id, is_new=True)

    def _find_title_primary(self, item: NewsItem, exclude_id: int) -> int | None:
        window = timedelta(hours=72)
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, published_at FROM news_items "
                "WHERE title_hash=? AND duplicate_of_id IS NULL AND id<>?",
                (item.title_hash, exclude_id),
            ).fetchall()
        for row in rows:
            try:
                published = datetime.fromisoformat(row["published_at"])
                if abs(published - item.published_at) <= window:
                    return int(row["id"])
            except ValueError:
                continue
        return None

    def get_item(self, item_id: int) -> NewsItem | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM news_items WHERE id=?", (item_id,)
            ).fetchone()
        return self._row_to_item(row) if row else None

    def update_item(self, item_id: int, **fields) -> None:
        if not fields:
            return
        columns = ", ".join(f"{key}=?" for key in fields)
        values = list(fields.values()) + [item_id]
        with self._lock:
            self._conn.execute(f"UPDATE news_items SET {columns} WHERE id=?", values)
            self._conn.commit()

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> NewsItem:
        return NewsItem(
            source_id=row["source_id"],
            source_name=row["source_name"],
            title=row["title"],
            url=row["url"],
            canonical_url=row["canonical_url"],
            id=int(row["id"]),
            original_summary=row["original_summary"],
            summary=row["summary"],
            published_at=datetime.fromisoformat(row["published_at"]),
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            category=row["category"],
            tags=json.loads(row["tags_json"] or "[]"),
            language=row["language"],
            title_hash=row["title_hash"],
            content_hash=row["content_hash"],
            importance_score=row["importance_score"],
            summary_status=row["summary_status"],
            source_count=row["source_count"],
            duplicate_of_id=row["duplicate_of_id"],
        )

    # ------------------------------------------------------------------
    # 查询（游标分页）
    # ------------------------------------------------------------------

    def list_items(
        self,
        category: str | None = None,
        source: str | None = None,
        query: str | None = None,
        since: datetime | None = None,
        before: datetime | None = None,
        cursor: str | None = None,
        limit: int = 30,
        include_duplicates: bool = False,
    ) -> tuple[list[NewsItem], str | None]:
        clauses = []
        params: list = []
        if not include_duplicates:
            clauses.append("duplicate_of_id IS NULL")
        if category:
            clauses.append("category=?")
            params.append(category)
        if source:
            clauses.append("source_id=?")
            params.append(source)
        if query:
            clauses.append("(title LIKE ? OR summary LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like])
        if since:
            clauses.append("published_at>=?")
            params.append(_iso(since))
        if before:
            clauses.append("published_at<?")
            params.append(_iso(before))
        if cursor:
            cursor_published, cursor_id = _decode_cursor(cursor)
            clauses.append("(published_at<? OR (published_at=? AND id<?))")
            params.extend([cursor_published, cursor_published, cursor_id])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT * FROM news_items "
            f"{where} ORDER BY published_at DESC, id DESC LIMIT ?"
        )
        with self._lock:
            rows = self._conn.execute(sql, params + [limit + 1]).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [self._row_to_item(row) for row in rows]
        next_cursor = (
            _encode_cursor(rows[-1]["published_at"], rows[-1]["id"])
            if has_more and rows
            else None
        )
        return items, next_cursor

    def category_stats(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT category, COUNT(*) AS count, MAX(published_at) AS latest "
                "FROM news_items WHERE duplicate_of_id IS NULL GROUP BY category"
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # 日报：按北京时间日期统计与查询
    # ------------------------------------------------------------------

    def day_stats(self, limit: int = 30) -> list[dict]:
        """近 N 个有数据的天（北京时间）：day / count / 当日热度 top 标题。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT date(published_at, '+8 hours') AS day, COUNT(*) AS count "
                "FROM news_items WHERE duplicate_of_id IS NULL "
                "GROUP BY day ORDER BY day DESC LIMIT ?",
                (limit,),
            ).fetchall()
            days = [dict(row) for row in rows]
            for entry in days:
                top = self._conn.execute(
                    "SELECT title FROM news_items "
                    "WHERE duplicate_of_id IS NULL "
                    "AND date(published_at, '+8 hours') = ? "
                    "ORDER BY importance_score DESC, source_count DESC LIMIT 1",
                    (entry["day"],),
                ).fetchone()
                entry["top_title"] = top["title"] if top else None
        return days

    def list_day_items(self, day: str) -> list[NewsItem]:
        """某北京时间日期（YYYY-MM-DD）的全部可见条目，按分类+时间排序。"""
        try:
            start = datetime.fromisoformat(day + "T00:00:00+08:00")
        except ValueError:
            raise ValueError("日期格式应为 YYYY-MM-DD") from None
        end = start + timedelta(days=1)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM news_items "
                "WHERE duplicate_of_id IS NULL "
                "AND published_at >= ? AND published_at < ? "
                "ORDER BY category, published_at DESC, id DESC",
                (_iso(start.astimezone(timezone.utc)), _iso(end.astimezone(timezone.utc))),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def count_items(self, include_duplicates: bool = True) -> int:
        where = "" if include_duplicates else " WHERE duplicate_of_id IS NULL"
        with self._lock:
            row = self._conn.execute(f"SELECT COUNT(*) AS c FROM news_items{where}").fetchone()
        return int(row["c"])

    def latest_item_time(self) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(fetched_at) AS latest FROM news_items"
            ).fetchone()
        return row["latest"] if row else None

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------

    def prune(self, retention_days: int) -> int:
        cutoff = utc_now() - timedelta(days=retention_days)
        with self._lock:
            deleted = self._conn.execute(
                "DELETE FROM news_items WHERE fetched_at<?", (_iso(cutoff),)
            ).rowcount
            self._conn.execute("DELETE FROM fetch_runs WHERE started_at<?", (_iso(cutoff),))
            self._conn.commit()
        return int(deleted)


def _encode_cursor(published_at: str, item_id: int) -> str:
    raw = f"{published_at}|{item_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, int]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        published_at, item_id = base64.urlsafe_b64decode(padded).decode().split("|")
        return published_at, int(item_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("分页游标无效") from exc
