"""AI 资讯来源层测试：URL 规范化、SSRF 校验、Feed/JSON 解析（全部离线）。"""

from __future__ import annotations

import json

import pytest

from web.news.config import NewsSettings, SourceConfig
from web.news.models import FetchOutcome, RawEntry
from web.news.sources.base import (
    SourceError,
    canonicalize_url,
    http_get_safe,
    validate_external_url,
)
from web.news.sources.china_finance import CLSFinanceSource, EastMoneyFinanceSource
from web.news.sources.feed import FeedSource
from web.news.sources.hacker_news import HackerNewsSource

PUBLIC_RESOLVER = lambda host: ["93.184.216.34"]  # noqa: E731


# ---------------------------------------------------------------------------
# URL 规范化
# ---------------------------------------------------------------------------


class TestCanonicalizeUrl:
    def test_strips_utm_params(self):
        url = "https://example.com/post?id=42&utm_source=feed&utm_medium=rss"
        assert canonicalize_url(url) == "https://example.com/post?id=42"

    def test_strips_fragment_and_tracking(self):
        url = "https://example.com/a?fbclid=x&gclid=y#section"
        assert canonicalize_url(url) == "https://example.com/a"

    def test_lowercase_host(self):
        assert canonicalize_url("https://EXAMPLE.com/Path") == "https://example.com/Path"

    def test_sorts_params_for_stable_dedup(self):
        a = canonicalize_url("https://example.com/p?b=2&a=1")
        b = canonicalize_url("https://example.com/p?a=1&b=2")
        assert a == b

    def test_identical_urls_share_fingerprint(self):
        a = canonicalize_url("https://example.com/x?utm_campaign=z")
        b = canonicalize_url("https://example.com/x")
        assert a == b


# ---------------------------------------------------------------------------
# SSRF 校验
# ---------------------------------------------------------------------------


class TestValidateExternalUrl:
    def test_https_public_host_passes(self):
        assert validate_external_url("https://example.com/feed", PUBLIC_RESOLVER) == "example.com"

    def test_http_rejected(self):
        with pytest.raises(SourceError, match="HTTPS"):
            validate_external_url("http://example.com/feed", PUBLIC_RESOLVER)

    def test_localhost_hostname_rejected(self):
        with pytest.raises(SourceError):
            validate_external_url("https://localhost/feed", PUBLIC_RESOLVER)

    def test_loopback_ip_rejected(self):
        with pytest.raises(SourceError):
            validate_external_url("https://127.0.0.1/feed", lambda host: ["127.0.0.1"])

    def test_private_ip_rejected(self):
        with pytest.raises(SourceError):
            validate_external_url("https://internal.corp/feed", lambda host: ["10.1.2.3"])

    def test_metadata_address_rejected(self):
        with pytest.raises(SourceError):
            validate_external_url("https://169.254.169.254/latest", lambda host: ["169.254.169.254"])

    def test_fake_ip_proxy_range_allowed(self):
        # 代理 fake-ip 模式（198.18.0.0/15）不是内网地址，应放行
        assert validate_external_url("https://example.com/feed", lambda host: ["198.18.1.6"]) == "example.com"

    def test_empty_url_rejected(self):
        with pytest.raises(SourceError):
            validate_external_url("", PUBLIC_RESOLVER)

    def test_dns_failure_raises_source_error(self):
        def failing_resolver(host):
            raise OSError("no resolution")

        with pytest.raises(SourceError):
            validate_external_url("https://nonexistent.invalid/feed", failing_resolver)


# ---------------------------------------------------------------------------
# http_get_safe：重定向校验、大小限制、条件请求（桩会话）
# ---------------------------------------------------------------------------


class StubResponse:
    def __init__(self, status_code=200, headers=None, body=b"", redirect=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body
        self._redirect = redirect
        self.closed = False

    def iter_content(self, chunk_size=65536):
        yield self._body

    def close(self):
        self.closed = True


class StubSession:
    """按 URL 顺序返回预置响应；记录请求头用于断言。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, headers=None, timeout=None, allow_redirects=False, stream=False):
        self.requests.append({"url": url, "headers": headers or {}})
        response = self.responses.pop(0)
        return response

    def close(self):
        pass


def _settings(**overrides) -> NewsSettings:
    base = {
        "request_timeout_seconds": 5.0,
        "max_response_bytes": 1024,
    }
    base.update(overrides)
    return NewsSettings(**base)


class TestHttpGetSafe:
    def test_plain_get(self):
        session = StubSession([StubResponse(200, {"ETag": '"abc"'}, b"data")])
        response = http_get_safe("https://example.com/feed", _settings(), session=session, resolver=PUBLIC_RESOLVER)
        assert response.status_code == 200
        assert response.body == b"data"
        assert response.etag == '"abc"'

    def test_conditional_headers_forwarded(self):
        session = StubSession([StubResponse(200, {}, b"")])
        http_get_safe(
            "https://example.com/feed", _settings(),
            etag='"v1"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT",
            session=session, resolver=PUBLIC_RESOLVER,
        )
        sent = session.requests[0]["headers"]
        assert sent["If-None-Match"] == '"v1"'
        assert sent["If-Modified-Since"] == "Mon, 01 Jan 2026 00:00:00 GMT"

    def test_redirect_to_public_https_followed(self):
        redirect = StubResponse(302, {"Location": "https://cdn.example.com/feed"})
        final = StubResponse(200, {}, b"ok")
        session = StubSession([redirect, final])
        response = http_get_safe("https://example.com/feed", _settings(), session=session, resolver=PUBLIC_RESOLVER)
        assert response.body == b"ok"
        assert response.final_url == "https://cdn.example.com/feed"

    def test_redirect_to_http_rejected(self):
        redirect = StubResponse(302, {"Location": "http://example.com/feed"})
        session = StubSession([redirect])
        with pytest.raises(SourceError, match="HTTPS"):
            http_get_safe("https://example.com/feed", _settings(), session=session, resolver=PUBLIC_RESOLVER)

    def test_redirect_to_private_host_rejected(self):
        redirect = StubResponse(302, {"Location": "https://internal.corp/feed"})
        session = StubSession([redirect])
        def private_resolver(host):
            return ["10.0.0.5"] if "internal" in host else ["93.184.216.34"]
        with pytest.raises(SourceError):
            http_get_safe("https://example.com/feed", _settings(), session=session, resolver=private_resolver)

    def test_too_many_redirects(self):
        redirects = [StubResponse(302, {"Location": f"https://example.com/{i}"}) for i in range(6)]
        session = StubSession(redirects)
        with pytest.raises(SourceError, match="重定向次数"):
            http_get_safe("https://example.com/feed", _settings(), session=session, resolver=PUBLIC_RESOLVER)

    def test_response_size_limit(self):
        big = StubResponse(200, {}, b"x" * 4096)
        session = StubSession([big])
        with pytest.raises(SourceError, match="大小限制"):
            http_get_safe("https://example.com/feed", _settings(), session=session, resolver=PUBLIC_RESOLVER)

    def test_status_304_passthrough(self):
        session = StubSession([StubResponse(304, {}, b"")])
        response = http_get_safe("https://example.com/feed", _settings(), session=session, resolver=PUBLIC_RESOLVER)
        assert response.status_code == 304


# ---------------------------------------------------------------------------
# Feed 解析
# ---------------------------------------------------------------------------

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Sample Feed</title>
  <item>
    <title>OpenAI 发布新推理模型</title>
    <link>https://example.com/openai-model?utm_source=rss</link>
    <description><![CDATA[<p>新模型在推理基准上提升 <b>30%</b>。</p>]]></description>
    <pubDate>Mon, 24 Aug 2026 10:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Missing link item</title>
    <description>应被跳过</description>
  </item>
</channel></rss>"""

MILLISECOND_RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>工信部人形机器人政策</title><link>https://example.com/new</link><pubDate>1788254280000</pubDate></item>
  <item><title>旧闻</title><link>https://example.com/old</link><pubDate>1753101405039</pubDate></item>
</channel></rss>"""

ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Sample</title>
  <entry>
    <title>NVIDIA announces new GPU</title>
    <link href="https://example.com/nvidia-gpu"/>
    <summary>Datacenter GPU with 288GB HBM.</summary>
    <updated>2026-08-25T12:30:00Z</updated>
  </entry>
</feed>"""


def _feed_source(url="https://example.com/feed") -> FeedSource:
    return FeedSource(
        SourceConfig("test_feed", "测试源", url, language="zh", vertical=True),
        _settings(),
    )


class TestFeedSource:
    def test_rss_parsing(self):
        session = StubSession([StubResponse(200, {}, RSS_SAMPLE.encode())])
        outcome = _feed_source().fetch(session=session, resolver=PUBLIC_RESOLVER)
        assert len(outcome.entries) == 1
        entry = outcome.entries[0]
        assert entry.title == "OpenAI 发布新推理模型"
        assert entry.url == "https://example.com/openai-model?utm_source=rss"
        assert "新模型在推理基准上提升 30%" in entry.summary
        assert "<" not in entry.summary
        assert entry.published_at is not None

    def test_atom_parsing(self):
        session = StubSession([StubResponse(200, {}, ATOM_SAMPLE.encode())])
        outcome = _feed_source().fetch(session=session, resolver=PUBLIC_RESOLVER)
        assert len(outcome.entries) == 1
        assert outcome.entries[0].url == "https://example.com/nvidia-gpu"

    def test_millisecond_timestamp_is_parsed_and_sorted(self):
        session = StubSession([StubResponse(200, {}, MILLISECOND_RSS_SAMPLE.encode())])
        outcome = _feed_source().fetch(session=session, resolver=PUBLIC_RESOLVER)
        assert outcome.entries[0].title == "工信部人形机器人政策"
        assert outcome.entries[0].published_at is not None
        assert outcome.entries[0].published_at > outcome.entries[1].published_at

    def test_malformed_xml_raises(self):
        session = StubSession([StubResponse(200, {}, b"<broken><rss")])
        with pytest.raises(SourceError, match="解析失败"):
            _feed_source().fetch(session=session, resolver=PUBLIC_RESOLVER)

    def test_empty_feed_returns_no_entries(self):
        empty = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>'
        session = StubSession([StubResponse(200, {}, empty)])
        outcome = _feed_source().fetch(session=session, resolver=PUBLIC_RESOLVER)
        assert outcome.entries == []

    def test_http_403_raises(self):
        session = StubSession([StubResponse(403, {}, b"forbidden")])
        with pytest.raises(SourceError, match="403"):
            _feed_source().fetch(session=session, resolver=PUBLIC_RESOLVER)

    def test_not_modified_short_circuit(self):
        session = StubSession([StubResponse(304, {}, b"")])
        outcome = _feed_source().fetch(etag='"v1"', session=session, resolver=PUBLIC_RESOLVER)
        assert outcome.not_modified is True
        assert outcome.entries == []

    def test_entries_capped_per_fetch(self):
        items = "".join(
            f"<item><title>AI item {i}</title><link>https://example.com/{i}</link></item>"
            for i in range(50)
        )
        body = f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'.encode()
        session = StubSession([StubResponse(200, {}, body)])
        settings = NewsSettings(max_entries_per_fetch=10)
        source = FeedSource(
            SourceConfig("test_feed", "测试源", "https://example.com/feed", vertical=True),
            settings,
        )
        outcome = source.fetch(session=session, resolver=PUBLIC_RESOLVER)
        assert len(outcome.entries) == 10


class TestHackerNewsSource:
    def test_json_parsing_with_external_url(self):
        payload = json.dumps({
            "hits": [
                {"title": "Show HN: AI agent framework", "url": "https://example.com/agent",
                 "objectID": "42", "points": 120, "created_at_i": 1770000000},
                {"title": "No url hit", "objectID": "43", "points": 5, "created_at_i": 1770000000},
            ]
        })
        source = HackerNewsSource(
            SourceConfig("hackernews", "HN", "https://hn.algolia.com/api/v1/search_by_date"),
            _settings(),
        )
        session = StubSession([StubResponse(200, {}, payload.encode())])
        outcome = source.fetch(session=session, resolver=PUBLIC_RESOLVER)
        assert len(outcome.entries) == 2
        assert outcome.entries[0].url == "https://example.com/agent"
        assert outcome.entries[1].url == "https://news.ycombinator.com/item?id=43"
        assert outcome.entries[0].published_at is not None

    def test_invalid_json_raises(self):
        source = HackerNewsSource(
            SourceConfig("hackernews", "HN", "https://hn.algolia.com/api/v1/search_by_date"),
            _settings(),
        )
        session = StubSession([StubResponse(200, {}, b"not json")])
        with pytest.raises(SourceError, match="JSON"):
            source.fetch(session=session, resolver=PUBLIC_RESOLVER)


class TestChinaFinanceSources:
    def test_cls_finance_parsing(self):
        payload = json.dumps(
            {
                "data": {
                    "roll_data": [
                        {
                            "id": 12345,
                            "title": "科大讯飞发布 AI 新模型",
                            "content": "财联社电报摘要",
                            "ctime": 1788254280,
                        }
                    ]
                }
            }
        ).encode()
        source = CLSFinanceSource(
            SourceConfig(
                "cls_finance",
                "财联社·A股电报",
                "https://www.cls.cn/v1/roll/get_roll_list",
                kind="cls_finance",
                language="zh",
                vertical=False,
            ),
            _settings(max_entries_per_fetch=20),
        )
        outcome = source.fetch(
            session=StubSession([StubResponse(200, {}, payload)]),
            resolver=PUBLIC_RESOLVER,
        )
        assert len(outcome.entries) == 1
        assert outcome.entries[0].url == "https://www.cls.cn/detail/12345"
        assert outcome.entries[0].published_at is not None

    def test_eastmoney_finance_parsing(self):
        payload = json.dumps(
            {
                "data": {
                    "fastNewsList": [
                        {
                            "title": "寒武纪算力芯片新进展",
                            "summary": "上市公司公告摘要",
                            "showTime": "2026-09-01 17:13:24",
                            "code": "202609013861538763",
                        }
                    ]
                }
            }
        ).encode()
        source = EastMoneyFinanceSource(
            SourceConfig(
                "eastmoney_finance",
                "东方财富·7×24",
                "https://np-weblist.eastmoney.com/comm/web/getFastNewsList",
                kind="eastmoney_finance",
                language="zh",
                vertical=False,
            ),
            _settings(max_entries_per_fetch=20),
        )
        outcome = source.fetch(
            session=StubSession([StubResponse(200, {}, payload)]),
            resolver=PUBLIC_RESOLVER,
        )
        assert len(outcome.entries) == 1
        assert outcome.entries[0].url.endswith("202609013861538763.html")
        assert outcome.entries[0].published_at is not None

    def test_invalid_json_raises(self):
        source = CLSFinanceSource(
            SourceConfig(
                "cls_finance",
                "财联社",
                "https://www.cls.cn/v1/roll/get_roll_list",
                kind="cls_finance",
            ),
            _settings(),
        )
        with pytest.raises(SourceError, match="JSON"):
            source.fetch(
                session=StubSession([StubResponse(200, {}, b"not-json")]),
                resolver=PUBLIC_RESOLVER,
            )


class TestRawEntryDefaults:
    def test_default_fields(self):
        entry = RawEntry(title="t", url="https://example.com")
        assert entry.summary == ""
        assert entry.published_at is None
        assert entry.language == "en"

    def test_fetch_outcome_defaults(self):
        outcome = FetchOutcome()
        assert outcome.entries == []
        assert outcome.not_modified is False
