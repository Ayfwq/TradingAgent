"""RSS / Atom 通用适配器（基于 feedparser）。"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import datetime, timezone
from html import unescape

import feedparser
import requests

from web.news.models import FetchOutcome, RawEntry
from web.news.sources.base import (
    SourceAdapter,
    SourceError,
    default_resolver,
    http_get_safe,
)


def _entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, key, None)
        if parsed:
            try:
                from time import struct_time

                if isinstance(parsed, struct_time):
                    # feedparser 的 *_parsed 分量是 UTC 日历时间，必须用
                    # timegm 按 UTC 解释；mktime 会按本地时区解释，导致
                    # 入库时间整体偏移（东八区差 8 小时，页面显得"不新鲜"）
                    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
            except (OverflowError, ValueError, OSError):
                continue
    return None


def _strip_tags(text: str) -> str:
    """去掉 HTML 标签并解码实体，得到纯文本摘要。"""
    import re

    if not text:
        return ""
    cleaned = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = unescape(cleaned)
    return " ".join(cleaned.split())


def _entry_url(entry) -> str:
    for key in ("link", "guid"):
        value = getattr(entry, key, None)
        if isinstance(value, str) and value.startswith("http"):
            return value.strip()
    for link in getattr(entry, "links", []) or []:
        href = link.get("href")
        if isinstance(href, str) and href.startswith("http"):
            return href.strip()
    return ""


class FeedSource(SourceAdapter):
    """RSS 2.0 / RSS 1.0 / Atom 通用适配器。"""

    def fetch(
        self,
        etag: str | None = None,
        last_modified: str | None = None,
        session: requests.Session | None = None,
        resolver: Callable[[str], list[str]] = default_resolver,
    ) -> FetchOutcome:
        response = http_get_safe(
            self.config.url,
            self.settings,
            etag=etag,
            last_modified=last_modified,
            session=session,
            resolver=resolver,
        )
        if response.status_code == 304:
            return FetchOutcome(not_modified=True, etag=etag, last_modified=last_modified)
        if response.status_code >= 400:
            raise SourceError(f"来源返回 HTTP {response.status_code}")
        body = response.body.decode("utf-8", errors="replace")
        parsed = feedparser.parse(body)
        entries = parsed.get("entries", []) or []
        if not entries and parsed.get("bozo"):
            reason = getattr(parsed.get("bozo_exception"), "message", "") or "非法 XML"
            raise SourceError(f"Feed 解析失败：{reason}")
        outcome = FetchOutcome(
            etag=response.etag,
            last_modified=response.last_modified,
        )
        for entry in entries:
            title = _strip_tags(getattr(entry, "title", "") or "")
            url = _entry_url(entry)
            if not title or not url:
                continue  # 缺少标题或原文链接的条目无法展示/去重，跳过
            summary = _strip_tags(
                getattr(entry, "summary", "")
                or getattr(entry, "description", "")
                or ""
            )
            outcome.entries.append(
                RawEntry(
                    title=title[:300],
                    url=url[:2000],
                    summary=summary[:2000],
                    published_at=_entry_datetime(entry),
                    language=self.config.language,
                )
            )
        # Feed 顺序通常为新条目在前；截断避免个别源一次返回全量历史
        outcome.entries = outcome.entries[: self.settings.max_entries_per_fetch]
        return outcome
