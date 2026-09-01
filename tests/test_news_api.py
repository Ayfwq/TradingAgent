"""API 与调度器测试：路由行为、分页参数、健康接口、来源隔离（全部离线）。"""

from __future__ import annotations

import os
import tempfile
import time
from datetime import timedelta

import pytest

# 在导入 web.app 之前固定数据库路径，避免测试写入真实用户目录。
_TMP_DIR = tempfile.mkdtemp(prefix="news_api_test_")
os.environ["NEWS_DATABASE_PATH"] = os.path.join(_TMP_DIR, "news.db")

from fastapi.testclient import TestClient  # noqa: E402

from web.app import app  # noqa: E402
from web.news.api import get_news_repository  # noqa: E402
from web.news.config import NewsSettings, SourceConfig  # noqa: E402
from web.news.models import FetchOutcome, RawEntry, utc_now  # noqa: E402
from web.news.pipeline import build_item  # noqa: E402
from web.news.repository import NewsRepository  # noqa: E402
from web.news.scheduler import NewsScheduler  # noqa: E402

client = TestClient(app)

SOURCE = SourceConfig("qbitai", "量子位", "https://www.qbitai.com/feed", vertical=True)


class TestDigestApi:
    """日报端点：days / digest（含精选）。"""

    def _today(self) -> str:
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc) + timedelta(hours=8)
        return now.strftime("%Y-%m-%d")

    def test_days_endpoint(self):
        response = client.get("/api/news/days")
        assert response.status_code == 200
        days = response.json()["days"]
        assert isinstance(days, list) and days
        for entry in days:
            assert "day" in entry and "count" in entry
            assert entry["count"] > 0
        # 倒序且日期格式合法
        keys = [entry["day"] for entry in days]
        assert keys == sorted(keys, reverse=True)

    def test_days_limit_param(self):
        assert client.get("/api/news/days", params={"limit": 0}).status_code == 422
        assert client.get("/api/news/days", params={"limit": 61}).status_code == 422

    def test_digest_today(self):
        day = self._today()
        response = client.get("/api/news/digest", params={"date": day})
        assert response.status_code == 200
        payload = response.json()
        assert payload["date"] == day
        # 种子条目发布于 0~4 小时前；北京时间凌晨运行时部分会落入昨天，
        # 因此只断言今天至少 1 条、且分组总和一致
        assert payload["total"] >= 1
        assert 0 < len(payload["featured"]) <= min(payload["total"], 10)
        total_grouped = sum(len(v) for v in payload["by_category"].values())
        assert total_grouped == payload["total"]

    def test_digest_featured_sorted_by_relevance(self):
        day = self._today()
        payload = client.get("/api/news/digest", params={"date": day}).json()
        featured = payload["featured"]
        # 精选应按 (source_count, importance) 降序
        keys = [(i["source_count"], i["importance_score"]) for i in featured]
        assert keys == sorted(keys, reverse=True)
        assert (
            max(
                sum(1 for item in featured if item["source_id"] == source_id)
                for source_id in {item["source_id"] for item in featured}
            )
            <= 2
        )

    def test_digest_bad_date_rejected(self):
        assert client.get("/api/news/digest", params={"date": "2026/08/29"}).status_code == 400
        assert client.get("/api/news/digest", params={"date": "not-a-date"}).status_code == 400

    def test_digest_empty_day(self):
        # 种子库没有 2020 年的数据
        payload = client.get("/api/news/digest", params={"date": "2020-01-01"}).json()
        assert payload["total"] == 0
        assert payload["featured"] == []
        assert payload["by_category"] == {}


def _insert(
    title,
    url,
    category="model_tech",
    published_offset_hours=0,
    tags=None,
    source=SOURCE,
):
    repo = get_news_repository()
    item, _ = build_item(
        source,
        RawEntry(
            title=title,
            url=url,
            summary=f"{title} 的原始摘要",
            published_at=utc_now() - timedelta(hours=published_offset_hours),
            language="zh",
        ),
        None,
        [0],
    )
    item.category = category
    if tags is not None:
        item.tags = tags
    return repo.insert_item(item)


@pytest.fixture(scope="module", autouse=True)
def seed_data():
    _insert("OpenAI 发布 GPT-5.5", "https://example.com/1", "model_tech", 0, ["OpenAI", "GPT-5"])
    _insert("NVIDIA 新 GPU 上市", "https://example.com/2", "chips_compute", 1, ["NVIDIA", "NVDA"])
    _insert("某公司完成融资", "https://example.com/3", "company_capital", 2)
    _insert("网信办新政策发布", "https://example.com/4", "policy_security", 3)
    _insert("开源工具上线", "https://example.com/5", "product_open_source", 4)
    _insert(
        "IT之家 AI 聚合稿",
        "https://example.com/ithome-hidden",
        source=SourceConfig(
            "ithome",
            "IT之家",
            "https://www.ithome.com/rss/",
            vertical=False,
        ),
    )
    yield


class TestNewsPage:
    def test_page_served(self):
        response = client.get("/news")
        assert response.status_code == 200
        assert "AI 资讯" in response.text
        assert "news.js" in response.text

    def test_home_has_news_nav(self):
        response = client.get("/")
        assert response.status_code == 200
        # 首页改为同页切换按钮（不再是 <a href="/news"> 跳转）
        assert "news-tab-trigger" in response.text
        assert "news_loader.js" in response.text


class TestListApi:
    def test_default_list(self):
        response = client.get("/api/news")
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["items"]) == 5
        first = payload["items"][0]
        assert first["title"] == "OpenAI 发布 GPT-5.5"
        assert first["category_label"] == "模型与技术"
        assert first["source_name"] == "量子位"
        assert first["authority_label"] == "专业媒体"
        assert first["authority_score"] > 0
        assert first["region_label"] == "国内来源"
        assert first["a_share_relevance"] > 0
        assert first["url"].startswith("https://")
        assert first["published_at"]

    def test_ordering_newest_first(self):
        items = client.get("/api/news").json()["items"]
        times = [item["published_at"] for item in items]
        assert times == sorted(times, reverse=True)

    def test_disabled_aggregator_history_is_hidden(self):
        payload = client.get("/api/news", params={"source": "ithome"}).json()
        assert payload["items"] == []

    def test_category_filter(self):
        payload = client.get("/api/news", params={"category": "chips_compute"}).json()
        assert len(payload["items"]) == 1
        assert payload["items"][0]["title"] == "NVIDIA 新 GPU 上市"

    def test_unknown_category_rejected(self):
        response = client.get("/api/news", params={"category": "nope"})
        assert response.status_code == 400

    def test_query_filter(self):
        payload = client.get("/api/news", params={"q": "融资"}).json()
        assert len(payload["items"]) == 1
        assert "融资" in payload["items"][0]["title"]

    def test_since_filter(self):
        # 种子数据发布于 now-0/1/2/3/4 小时；取 3.5 小时前作为分界，结果确定
        since = (utc_now() - timedelta(hours=3, minutes=30)).isoformat()
        payload = client.get("/api/news", params={"since": since}).json()
        assert len(payload["items"]) == 4

    def test_invalid_since_rejected(self):
        response = client.get("/api/news", params={"since": "not-a-date"})
        assert response.status_code == 400

    def test_limit_and_cursor(self):
        page1 = client.get("/api/news", params={"limit": 2}).json()
        assert len(page1["items"]) == 2
        assert page1["next_cursor"]
        page2 = client.get("/api/news", params={"limit": 2, "cursor": page1["next_cursor"]}).json()
        ids1 = {item["id"] for item in page1["items"]}
        ids2 = {item["id"] for item in page2["items"]}
        assert not ids1 & ids2

    def test_invalid_cursor_rejected(self):
        response = client.get("/api/news", params={"cursor": "@@@bad@@@"})
        assert response.status_code == 400

    def test_limit_bounds(self):
        assert client.get("/api/news", params={"limit": 0}).status_code == 422
        assert client.get("/api/news", params={"limit": 101}).status_code == 422

    def test_title_field_is_plain_text(self):
        # 服务端清洗在管道完成（见 test_news_pipeline），API 原样返回已清洗文本
        items = client.get("/api/news").json()["items"]
        assert all("<script>" not in item["title"] for item in items)


class TestCategoriesApi:
    def test_categories_with_counts(self):
        payload = client.get("/api/news/categories").json()
        categories = {row["key"]: row for row in payload["categories"]}
        assert categories["model_tech"]["count"] == 1
        assert categories["chips_compute"]["count"] == 1
        assert categories["policy_security"]["label"] == "政策与安全"
        assert all("latest_published_at" in row for row in payload["categories"])


class TestSourcesApi:
    def test_sources_health_shape(self):
        payload = client.get("/api/news/sources").json()
        assert isinstance(payload["sources"], list)
        for source in payload["sources"]:
            assert "source_id" in source
            assert "last_error" in source
            assert "consecutive_failures" in source
            # 不泄露内部堆栈或敏感配置
            assert "api_key" not in source


class TestHealthApi:
    def test_health_payload(self):
        payload = client.get("/api/news/health").json()
        assert payload["database"] == "ok"
        assert payload["items_total"] >= 5
        assert "worker_alive" in payload
        assert payload["status"] in {"ok", "degraded"}


# ---------------------------------------------------------------------------
# 调度器：来源隔离、失败重试、心跳、运行记录（桩适配器，完全离线）
# ---------------------------------------------------------------------------


class StubAdapter:
    def __init__(self, config, settings, outcome=None, error=None):
        self.config = config
        self.settings = settings
        self._outcome = outcome
        self._error = error
        self.calls = 0

    def fetch(self, etag=None, last_modified=None, session=None, resolver=None):
        self.calls += 1
        if self._error:
            raise self._error
        return self._outcome


def _stub_adapter_factory(outcomes, errors):
    def factory(config, settings):
        if config.source_id in errors:
            return StubAdapter(config, settings, error=errors[config.source_id])
        return StubAdapter(
            config,
            settings,
            outcome=FetchOutcome(
                entries=[
                    RawEntry(
                        title=f"AI 测试条目 {config.source_id}",
                        url=f"https://example.com/stub/{config.source_id}",
                        summary="测试摘要",
                        published_at=utc_now(),
                    )
                ]
            ),
        )

    return factory


@pytest.fixture()
def no_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)


class TestScheduler:
    def _make_scheduler(self, tmp_path, sources, errors=None):
        settings = NewsSettings(
            ai_summary_enabled=False,
            fetch_interval_minutes=15,
            database_path=tmp_path / "worker.db",
        )
        repo = NewsRepository(settings.database_path)
        scheduler = NewsScheduler(
            settings,
            repo,
            sources=sources,
            adapter_factory=_stub_adapter_factory(None, errors or {}),
            summarizer=None,
        )
        return scheduler, repo

    def test_run_once_inserts_items_and_records_runs(self, tmp_path, no_sleep):
        sources = [
            SourceConfig("qbitai", "量子位", "https://www.qbitai.com/feed", vertical=True),
            SourceConfig("openai", "OpenAI", "https://openai.com/news/rss.xml"),
        ]
        scheduler, repo = self._make_scheduler(tmp_path, sources)
        try:
            summary = scheduler.run_once()
            assert summary["sources_ok"] == 2
            assert summary["sources_failed"] == 0
            assert summary["new_items"] == 2
            assert repo.count_items() == 2
            assert repo.latest_run()["status"] == "ok"
            assert scheduler.heartbeat_age_seconds() is not None
        finally:
            repo.close()

    def test_single_source_failure_is_isolated(self, tmp_path, no_sleep):
        sources = [
            SourceConfig("good", "正常源", "https://good.example/feed", vertical=True),
            SourceConfig("bad", "故障源", "https://bad.example/feed", vertical=True),
        ]
        scheduler, repo = self._make_scheduler(
            tmp_path, sources, errors={"bad": Exception("HTTP 503")}
        )
        try:
            summary = scheduler.run_once()
            assert summary["sources_ok"] == 1
            assert summary["sources_failed"] == 1
            assert repo.count_items() == 1
            health = {s.source_id: s for s in repo.list_source_health()}
            assert health["bad"].consecutive_failures == 1
            assert "503" in health["bad"].last_error
            assert health["good"].last_success_at is not None
        finally:
            repo.close()

    def test_retry_then_success(self, tmp_path, no_sleep):
        from web.news.sources.base import SourceError

        flaky = {"calls": 0}

        class FlakyAdapter(StubAdapter):
            def fetch(self, etag=None, last_modified=None, session=None, resolver=None):
                flaky["calls"] += 1
                if flaky["calls"] < 3:  # 前两次失败，第三次成功
                    raise SourceError("temporary failure")
                return FetchOutcome(
                    entries=[
                        RawEntry(
                            title="重试成功的条目",
                            url="https://example.com/flaky",
                            published_at=utc_now(),
                        )
                    ]
                )

        settings = NewsSettings(
            ai_summary_enabled=False,
            database_path=tmp_path / "flaky.db",
        )
        repo = NewsRepository(settings.database_path)
        sources = [SourceConfig("flaky", "抖动源", "https://flaky.example/feed", vertical=True)]
        scheduler = NewsScheduler(
            settings,
            repo,
            sources=sources,
            adapter_factory=lambda config, s: FlakyAdapter(config, s),
            summarizer=None,
        )
        try:
            summary = scheduler.run_once()
            assert summary["sources_ok"] == 1
            assert summary["new_items"] == 1
            assert flaky["calls"] == 3
        finally:
            repo.close()

    def test_not_modified_updates_health_without_items(self, tmp_path, no_sleep):
        settings = NewsSettings(
            ai_summary_enabled=False,
            database_path=tmp_path / "nm.db",
        )
        repo = NewsRepository(settings.database_path)
        sources = [SourceConfig("nm", "条件源", "https://nm.example/feed", vertical=True)]
        scheduler = NewsScheduler(
            settings,
            repo,
            sources=sources,
            adapter_factory=lambda config, s: StubAdapter(
                config, s, outcome=FetchOutcome(not_modified=True)
            ),
            summarizer=None,
        )
        try:
            summary = scheduler.run_once()
            assert summary["sources_ok"] == 1
            assert summary["new_items"] == 0
            assert repo.count_items() == 0
        finally:
            repo.close()

    def test_interval_prevents_immediate_refetch(self, tmp_path, no_sleep):
        sources = [SourceConfig("qbitai", "量子位", "https://www.qbitai.com/feed", vertical=True)]
        scheduler, repo = self._make_scheduler(tmp_path, sources)
        try:
            scheduler.run_once()
            # 刚抓取过，间隔未到 -> 本轮无待抓来源
            summary = scheduler.run_once()
            assert summary["due_sources"] == 0
            assert summary["new_items"] == 0
        finally:
            repo.close()

    def test_dedup_across_sources_via_scheduler(self, tmp_path, no_sleep):
        settings = NewsSettings(
            ai_summary_enabled=False,
            database_path=tmp_path / "dedup.db",
        )
        repo = NewsRepository(settings.database_path)
        # 标题含 AI 关键词，综合源（ithome）才能通过相关性过滤
        shared_title = "OpenAI 发布 GPT-5.5 新模型"
        entries = {
            "qbitai": RawEntry(title=shared_title, url="https://a.com/1", published_at=utc_now()),
            "ithome": RawEntry(title=shared_title, url="https://b.com/2", published_at=utc_now()),
        }

        def factory(config, s):
            return StubAdapter(
                config,
                s,
                outcome=FetchOutcome(entries=[entries[config.source_id]]),
            )

        sources = [
            SourceConfig("qbitai", "量子位", "https://www.qbitai.com/feed", vertical=True),
            SourceConfig("ithome", "IT之家", "https://www.ithome.com/rss/", vertical=False),
        ]
        scheduler = NewsScheduler(
            settings,
            repo,
            sources=sources,
            adapter_factory=factory,
            summarizer=None,
        )
        try:
            scheduler.run_once()
            items, _ = repo.list_items()
            assert len(items) == 1
            assert items[0].source_count == 2
        finally:
            repo.close()
