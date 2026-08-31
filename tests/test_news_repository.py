"""SQLite 仓储层测试：去重、事件合并、分页、健康状态、保留期清理。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from web.news.models import FetchRunStats, NewsItem, utc_now
from web.news.pipeline import title_fingerprint
from web.news.repository import NewsRepository, _decode_cursor, _encode_cursor


def make_item(
    source_id="qbitai",
    source_name="量子位",
    title="OpenAI 发布 GPT-5.5",
    url="https://example.com/a",
    published_at=None,
    fetched_at=None,
    **overrides,
) -> NewsItem:
    from web.news.sources import canonicalize_url

    item = NewsItem(
        source_id=source_id,
        source_name=source_name,
        title=title,
        url=url,
        canonical_url=canonicalize_url(url),
        published_at=published_at or utc_now(),
        fetched_at=fetched_at or utc_now(),
        title_hash=title_fingerprint(title),
        category="model_tech",
        summary="摘要",
    )
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


@pytest.fixture()
def repo(tmp_path):
    repository = NewsRepository(tmp_path / "news.db")
    yield repository
    repository.close()


class TestSchemaAndKv:
    def test_kv_roundtrip(self, repo):
        repo.set_kv("worker_heartbeat", "2026-08-30T00:00:00+00:00")
        assert repo.get_kv("worker_heartbeat") == "2026-08-30T00:00:00+00:00"
        assert repo.get_kv("missing") is None

    def test_wal_mode_enabled(self, repo):
        mode = repo._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_upsert_and_read_source(self, repo):
        repo.upsert_source("qbitai", "量子位", "https://www.qbitai.com/feed", True, None)
        health = repo.list_source_health()
        assert len(health) == 1
        assert health[0].source_id == "qbitai"
        assert health[0].consecutive_failures == 0


class TestInsertAndDedup:
    def test_insert_new_item(self, repo):
        result = repo.insert_item(make_item())
        assert result.is_new and result.item_id > 0
        assert repo.count_items() == 1

    def test_same_canonical_url_is_duplicate(self, repo):
        first = repo.insert_item(make_item(url="https://example.com/a?utm_source=x"))
        second = repo.insert_item(make_item(url="https://example.com/a"))
        assert first.is_new
        assert not second.is_new
        assert repo.count_items() == 1

    def test_title_merge_within_window(self, repo):
        published = utc_now()
        first = repo.insert_item(
            make_item(title="NVIDIA 发布新 GPU", url="https://a.com/1", published_at=published)
        )
        second = repo.insert_item(
            make_item(
                source_id="techcrunch_ai", source_name="TechCrunch AI",
                title="NVIDIA 发布新 GPU！", url="https://b.com/2",
                published_at=published + timedelta(hours=1),
            )
        )
        assert second.is_new
        assert second.merged_into_id == first.item_id
        primary = repo.get_item(first.item_id)
        assert primary.source_count == 2
        # 合并副本不出现在默认列表
        items, _ = repo.list_items()
        assert len(items) == 1
        assert items[0].id == first.item_id

    def test_title_outside_window_not_merged(self, repo):
        published = utc_now()
        repo.insert_item(make_item(title="同标题旧闻", url="https://a.com/1", published_at=published))
        second = repo.insert_item(
            make_item(
                title="同标题旧闻",
                url="https://b.com/2",
                published_at=published + timedelta(days=5),
            )
        )
        assert second.merged_into_id is None
        items, _ = repo.list_items()
        assert len(items) == 2

    def test_merged_primary_importance_recomputed(self, repo):
        published = utc_now()
        first = repo.insert_item(
            make_item(title="芯片出口新规", url="https://a.com/1", published_at=published)
        )
        before = repo.get_item(first.item_id).importance_score
        repo.insert_item(
            make_item(
                source_id="infoq", source_name="InfoQ",
                title="芯片出口新规", url="https://b.com/2",
                published_at=published + timedelta(minutes=30),
            )
        )
        after = repo.get_item(first.item_id)
        assert after.importance_score >= before
        assert after.source_count == 2


class TestQueries:
    @pytest.fixture()
    def filled_repo(self, repo):
        base = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        for index in range(5):
            repo.insert_item(
                make_item(
                    title=f"AI 新闻 {index}",
                    url=f"https://example.com/{index}",
                    published_at=base - timedelta(hours=index),
                    category="model_tech" if index % 2 == 0 else "company_capital",
                    source_id="qbitai" if index % 2 == 0 else "ithome",
                )
            )
        return repo

    def test_order_and_limit(self, filled_repo):
        items, next_cursor = filled_repo.list_items(limit=3)
        assert [item.title for item in items] == ["AI 新闻 0", "AI 新闻 1", "AI 新闻 2"]
        assert next_cursor is not None

    def test_cursor_pagination(self, filled_repo):
        page1, cursor = filled_repo.list_items(limit=3)
        page2, cursor2 = filled_repo.list_items(limit=3, cursor=cursor)
        assert [item.id for item in page2] != [item.id for item in page1]
        assert len(page2) == 2
        assert cursor2 is None
        all_ids = [item.id for item in page1] + [item.id for item in page2]
        assert len(set(all_ids)) == 5

    def test_invalid_cursor_raises(self, filled_repo):
        with pytest.raises(ValueError):
            filled_repo.list_items(cursor="!!!not-a-cursor!!!")

    def test_category_filter(self, filled_repo):
        items, _ = filled_repo.list_items(category="company_capital")
        assert items and all(item.category == "company_capital" for item in items)

    def test_source_filter(self, filled_repo):
        items, _ = filled_repo.list_items(source="ithome")
        assert items and all(item.source_id == "ithome" for item in items)

    def test_query_filter(self, filled_repo):
        items, _ = filled_repo.list_items(query="AI 新闻 3")
        assert len(items) == 1

    def test_since_filter(self, filled_repo):
        cutoff = datetime(2026, 8, 30, 9, 30, 0, tzinfo=timezone.utc)
        items, _ = filled_repo.list_items(since=cutoff)
        assert all(item.published_at >= cutoff for item in items)

    def test_category_stats(self, filled_repo):
        stats = {row["category"]: row for row in filled_repo.category_stats()}
        assert stats["model_tech"]["count"] == 3
        assert stats["company_capital"]["count"] == 2


class TestSourceHealthAndRuns:
    def test_success_then_failure_tracking(self, repo):
        repo.upsert_source("qbitai", "量子位", "https://www.qbitai.com/feed", True, None)
        repo.mark_source_success("qbitai", 250, 10, '"etag-1"', "Mon, 01 Jan 2026 00:00:00 GMT")
        health = repo.list_source_health()[0]
        assert health.last_success_at is not None
        assert health.last_items_count == 10
        assert health.consecutive_failures == 0

        repo.mark_source_failure("qbitai", "HTTP 503", 900)
        repo.mark_source_failure("qbitai", "timeout", 400)
        health = repo.list_source_health()[0]
        assert health.consecutive_failures == 2
        assert health.last_error == "timeout"

    def test_conditional_headers_persisted(self, repo):
        repo.upsert_source("qbitai", "量子位", "https://www.qbitai.com/feed", True, None)
        repo.mark_source_success("qbitai", 100, 5, '"v2"', "Last-Mod")
        etag, last_modified = repo.get_source_conditional("qbitai")
        assert etag == '"v2"'
        assert last_modified == "Last-Mod"

    def test_fetch_runs_recorded(self, repo):
        stats = FetchRunStats(
            source_id="qbitai",
            started_at=utc_now(),
            finished_at=utc_now(),
            status="ok",
            new_count=3,
            duplicate_count=1,
            filtered_count=2,
            ai_count=1,
            duration_ms=512,
        )
        repo.record_run(stats)
        latest = repo.latest_run()
        assert latest["source_id"] == "qbitai"
        assert latest["new_count"] == 3
        assert latest["ai_count"] == 1
        assert latest["status"] == "ok"


class TestPrune:
    def test_old_items_deleted(self, repo):
        old = make_item(
            title="旧新闻", url="https://example.com/old",
            fetched_at=utc_now() - timedelta(days=30),
        )
        fresh = make_item(
            title="新新闻", url="https://example.com/fresh", fetched_at=utc_now()
        )
        repo.insert_item(old)
        repo.insert_item(fresh)
        deleted = repo.prune(retention_days=7)
        assert deleted == 1
        assert repo.count_items() == 1


class TestCursorCodec:
    def test_roundtrip(self):
        cursor = _encode_cursor("2026-08-30T12:00:00+00:00", 42)
        published, item_id = _decode_cursor(cursor)
        assert published == "2026-08-30T12:00:00+00:00"
        assert item_id == 42
