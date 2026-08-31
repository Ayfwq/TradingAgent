"""处理管道测试：标准化、过滤、分类、标签、热度、AI 摘要与降级。"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from web.news.config import NewsSettings, SourceConfig
from web.news.models import RawEntry, utc_now
from web.news.pipeline import (
    AISummarizer,
    _validate_ai_payload,
    build_item,
    classify,
    clean_html,
    content_fingerprint,
    detect_language,
    extract_tags,
    importance_score,
    is_relevant,
    normalize_title,
    persist_item,
    title_fingerprint,
)

VERTICAL = SourceConfig("qbitai", "量子位", "https://www.qbitai.com/feed", vertical=True)
GENERAL = SourceConfig("ithome", "IT之家", "https://www.ithome.com/rss/", vertical=False)


def _entry(title="OpenAI 发布新模型", url="https://example.com/x", summary="推理提升"):
    return RawEntry(title=title, url=url, summary=summary, published_at=utc_now(), language="zh")


class TestNormalization:
    def test_clean_html_strips_script_and_style(self):
        dirty = '前<script>alert(1)</script>文<style>.x{}</style>正文 <b>加粗</b> 结尾'
        assert "script" not in clean_html(dirty)
        assert "alert" not in clean_html(dirty)
        assert "加粗" in clean_html(dirty)

    def test_clean_html_decodes_entities(self):
        assert clean_html("A&nbsp;&amp;&nbsp;B") == "A & B"

    def test_clean_html_empty(self):
        assert clean_html("") == ""
        assert clean_html(None) == ""

    def test_title_fingerprint_ignores_punctuation_and_case(self):
        assert title_fingerprint("NVIDIA 发布新 GPU！") == title_fingerprint("nvidia发布新gpu")
        assert title_fingerprint("A B") == title_fingerprint("AB")  # 空格不参与指纹
        assert title_fingerprint("模型甲") != title_fingerprint("模型乙")

    def test_content_fingerprint_stable(self):
        assert content_fingerprint("标题", "内容") == content_fingerprint("标题", "内容")
        assert content_fingerprint("标题", "内容A") != content_fingerprint("标题", "内容B")

    def test_normalize_title_fullwidth(self):
        # 全角字符 NFKC 后与半角一致
        assert normalize_title("ＡＩ") == normalize_title("AI")

    def test_detect_language(self):
        assert detect_language("OpenAI 发布新模型", "") == "zh"
        assert detect_language("OpenAI releases new model", "") == "en"


class TestRelevanceFilter:
    def test_vertical_source_always_relevant(self):
        assert is_relevant(VERTICAL, "今天天气不错", "") is True

    def test_general_source_needs_keyword(self):
        assert is_relevant(GENERAL, "新 AI 模型发布", "") is True
        assert is_relevant(GENERAL, "手机壳新品上市", "") is False

    def test_general_source_keyword_in_summary(self):
        assert is_relevant(GENERAL, "某公司消息", "涉及 GPU 供应链") is True


class TestClassification:
    def test_model_tech(self):
        assert classify("OpenAI 发布新一代推理模型", "多模态基准提升") == "model_tech"

    def test_chips_compute(self):
        assert classify("NVIDIA 新 GPU 发布", "HBM 显存提升") == "chips_compute"

    def test_company_capital(self):
        assert classify("某 AI 公司完成 B 轮融资", "估值 10 亿美元") == "company_capital"

    def test_policy_security(self):
        assert classify("网信办发布新监管政策", "合规要求") == "policy_security"

    def test_product_open_source(self):
        assert classify("开源工具发布", "GitHub 项目上线") == "product_open_source"

    def test_unknown_goes_to_other(self):
        assert classify("今天中午吃什么", "随便聊聊") == "other"


class TestTags:
    def test_company_and_ticker_tags(self):
        tags = extract_tags("NVIDIA 与 Google 合作", "GPU 厂商")
        assert "NVIDIA" in tags
        assert "NVDA" in tags
        assert "Google" in tags
        assert "GOOGL" in tags

    def test_no_tag_without_evidence(self):
        assert extract_tags("某匿名公司融资", "") == []

    def test_tag_limit(self):
        text = " ".join(["OpenAI", "Google", "微软", "苹果", "NVIDIA", "AMD", "英特尔", "Meta"])
        assert len(extract_tags(text, "", limit=6)) <= 6


class TestImportance:
    def test_fresh_item_scores_high(self):
        score = importance_score(utc_now(), 1, 0.9, "普通内容")
        assert score >= 50

    def test_old_item_scores_low(self):
        score = importance_score(utc_now() - timedelta(days=7), 1, 0.5, "普通内容")
        assert score <= 20

    def test_multi_source_and_hot_terms_boost(self):
        base = importance_score(utc_now(), 1, 0.5, "普通内容")
        boosted = importance_score(utc_now(), 5, 0.5, "NVIDIA 芯片政策")
        assert boosted > base

    def test_score_bounded(self):
        assert 0 <= importance_score(utc_now(), 99, 1.0, "NVIDIA OpenAI") <= 100


class TestBuildItem:
    def test_full_flow_with_fallback_summary(self):
        item, disposition = build_item(VERTICAL, _entry(), None, [0])
        assert disposition == "new"
        assert item.summary == "推理提升"
        assert item.summary_status == "rss"
        assert item.category == "model_tech"
        assert item.canonical_url == "https://example.com/x"
        assert item.title_hash

    def test_irrelevant_entry_from_general_source_filtered(self):
        entry = RawEntry(title="新款手机壳上市", url="https://example.com/y", published_at=utc_now())
        item, disposition = build_item(GENERAL, entry, None, [0])
        assert item is None
        assert disposition == "filtered"

    def test_missing_published_at_uses_now(self):
        entry = RawEntry(title="AI 快讯", url="https://example.com/z")
        item, _ = build_item(VERTICAL, entry, None, [0])
        assert item.published_at is not None

    def test_html_in_title_cleaned(self):
        entry = RawEntry(
            title="<script>alert(1)</script>AI 模型发布",
            url="https://example.com/h",
        )
        item, _ = build_item(VERTICAL, entry, None, [0])
        assert "<script>" not in item.title
        assert "alert" not in item.title
        assert "AI 模型发布" in item.title

    def test_empty_summary_falls_back_to_title(self):
        entry = RawEntry(title="AI 大事件", url="https://example.com/e")
        item, _ = build_item(VERTICAL, entry, None, [0])
        assert item.summary == "AI 大事件 —— 来自 量子位"


class TestAISummarizer:
    def _summarizer(self, ai_enabled=True):
        return AISummarizer(NewsSettings(ai_summary_enabled=ai_enabled, ai_request_timeout_seconds=5))

    def test_disabled_returns_none(self):
        assert self._summarizer(ai_enabled=False).summarize("t", "s") is None

    def test_valid_payload_accepted(self):
        content = '{"summary": "OpenAI 发布新一代模型，推理成本显著下降，值得关注其在企业侧的落地进展。", "category": "model_tech", "tags": ["OpenAI"]}'
        result = _validate_ai_payload(content, "t", "s")
        assert result is not None
        assert result["category"] == "model_tech"
        assert "OpenAI" in result["tags"]

    def test_fenced_payload_accepted(self):
        content = '```json\n{"summary": "' + "很长的摘要" * 10 + '", "category": "company_capital"}\n```'
        result = _validate_ai_payload(content, "t", "s")
        assert result is not None
        assert result["category"] == "company_capital"

    def test_invalid_json_returns_none(self):
        assert _validate_ai_payload("这不是 JSON", "t", "s") is None

    def test_short_summary_rejected(self):
        assert _validate_ai_payload('{"summary": "太短", "category": "other"}', "t", "s") is None

    def test_bad_category_reclassified(self):
        content = '{"summary": "' + "合规且长度足够的中文摘要内容" * 3 + '", "category": "不存在的分类", "tags": "not-a-list"}'
        result = _validate_ai_payload(content, "t", "s")
        assert result["category"] == "other"
        assert result["tags"] == []

    def test_invoke_exception_returns_none(self):
        summarizer = self._summarizer()
        summarizer._llm = SimpleNamespace(invoke=lambda prompt: (_ for _ in ()).throw(RuntimeError("boom")))
        assert summarizer.summarize("t", "s") is None

    def test_timeout_returns_none(self):
        import time

        summarizer = self._summarizer()
        summarizer.settings.ai_request_timeout_seconds = 0.05

        def slow_invoke(prompt):
            time.sleep(0.3)
            return SimpleNamespace(content="{}")

        summarizer._llm = SimpleNamespace(invoke=slow_invoke)
        assert summarizer.summarize("t", "s") is None

    def test_ai_result_used_in_build_item(self):
        summarizer = self._summarizer()
        payload = '{"summary": "OpenAI 发布新一代模型，推理成本显著下降，企业落地进展值得关注。", "category": "product_open_source", "tags": ["OpenAI"]}'
        summarizer._llm = SimpleNamespace(invoke=lambda prompt: SimpleNamespace(content=payload))
        item, disposition = build_item(VERTICAL, _entry(), summarizer, [5])
        assert disposition == "new"
        assert item.summary_status == "ai"
        assert item.category == "product_open_source"
        assert "OpenAI" in item.tags

    def test_ai_budget_exhausted_skips_call(self):
        calls = []

        summarizer = self._summarizer()

        def counting_invoke(prompt):
            calls.append(prompt)
            return SimpleNamespace(content='{"summary": "预算用尽测试摘要" * 5 + "。", "category": "other"}')

        summarizer._llm = SimpleNamespace(invoke=counting_invoke)
        build_item(VERTICAL, _entry(), summarizer, [0])
        assert calls == []

    def test_client_init_failure_disables_ai(self):
        settings = NewsSettings(ai_summary_enabled=True)
        summarizer = AISummarizer(settings)
        with patch(
            "tradingagents.llm_clients.create_llm_client",
            side_effect=ValueError("no provider"),
        ):
            assert summarizer.summarize("t", "s") is None
        assert summarizer.available is False


class TestPersistItem:
    def test_persist_and_merge(self, tmp_path):
        from web.news.repository import NewsRepository

        repo = NewsRepository(tmp_path / "news.db")
        try:
            entry1 = RawEntry(title="大模型融资事件", url="https://a.com/1", published_at=utc_now())
            entry2 = RawEntry(title="大模型融资事件", url="https://b.com/2", published_at=utc_now() + timedelta(minutes=10))
            source = SourceConfig("qbitai", "量子位", "https://www.qbitai.com/feed", vertical=True)
            item1, _ = build_item(source, entry1, None, [0])
            item2, _ = build_item(source, entry2, None, [0])
            result1 = persist_item(repo, source, item1)
            result2 = persist_item(repo, source, item2)
            assert result1.is_new
            assert result2.merged_into_id == result1.item_id
        finally:
            repo.close()
