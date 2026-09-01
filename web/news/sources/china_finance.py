"""国内 A 股财经快讯适配器：财联社电报 / 东方财富 7×24。"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from web.news.models import FetchOutcome, RawEntry
from web.news.sources.base import (
    SourceAdapter,
    SourceError,
    default_resolver,
    http_get_safe,
)


def _json_body(body: bytes) -> dict:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError("来源返回非法 JSON") from exc
    if not isinstance(payload, dict):
        raise SourceError("来源 JSON 根节点不是对象")
    return payload


class CLSFinanceSource(SourceAdapter):
    """财联社电报。签名算法与其公开 Web 客户端请求保持一致。"""

    def fetch(
        self,
        etag: str | None = None,
        last_modified: str | None = None,
        session: requests.Session | None = None,
        resolver: Callable[[str], list[str]] = default_resolver,
    ) -> FetchOutcome:
        params = {
            "app": "CailianpressWeb",
            "category": "",
            "last_time": int(time.time()),
            "os": "web",
            "refresh_type": "1",
            # 该端点对 Web 客户端固定返回 20 条，rn 过大会返回空列表。
            "rn": 20,
            "sv": "8.4.6",
        }
        query = urlencode(params)
        params["sign"] = hashlib.md5(
            hashlib.sha1(query.encode("utf-8")).hexdigest().encode("utf-8")
        ).hexdigest()
        url = f"{self.config.url}?{urlencode(params)}"
        response = http_get_safe(
            url,
            self.settings,
            session=session,
            resolver=resolver,
        )
        if response.status_code >= 400:
            raise SourceError(f"来源返回 HTTP {response.status_code}")
        payload = _json_body(response.body)
        rows = payload.get("data", {}).get("roll_data", [])
        if not isinstance(rows, list):
            raise SourceError("财联社 JSON 缺少 roll_data")

        entries: list[RawEntry] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            item_id = row.get("id")
            if not title or not item_id:
                continue
            timestamp = row.get("ctime")
            published_at = None
            with suppress(TypeError, ValueError, OSError):
                published_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
            entries.append(
                RawEntry(
                    title=title[:300],
                    url=f"https://www.cls.cn/detail/{item_id}",
                    summary=str(row.get("content") or row.get("brief") or "")[:2000],
                    published_at=published_at,
                    language="zh",
                )
            )
        return FetchOutcome(entries=entries[: self.settings.max_entries_per_fetch])


class EastMoneyFinanceSource(SourceAdapter):
    """东方财富 7×24 A 股财经快讯。"""

    def fetch(
        self,
        etag: str | None = None,
        last_modified: str | None = None,
        session: requests.Session | None = None,
        resolver: Callable[[str], list[str]] = default_resolver,
    ) -> FetchOutcome:
        params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": min(self.settings.max_entries_per_fetch, 200),
            "req_trace": int(time.time() * 1000),
        }
        response = http_get_safe(
            f"{self.config.url}?{urlencode(params)}",
            self.settings,
            session=session,
            resolver=resolver,
        )
        if response.status_code >= 400:
            raise SourceError(f"来源返回 HTTP {response.status_code}")
        payload = _json_body(response.body)
        rows = payload.get("data", {}).get("fastNewsList", [])
        if not isinstance(rows, list):
            raise SourceError("东方财富 JSON 缺少 fastNewsList")

        entries: list[RawEntry] = []
        shanghai = ZoneInfo("Asia/Shanghai")
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            code = str(row.get("code") or "").strip()
            if not title or not code:
                continue
            published_at = None
            with suppress(ValueError):
                published_at = (
                    datetime.fromisoformat(str(row.get("showTime")))
                    .replace(tzinfo=shanghai)
                    .astimezone(timezone.utc)
                )
            entries.append(
                RawEntry(
                    title=title[:300],
                    url=f"https://finance.eastmoney.com/a/{code}.html",
                    summary=str(row.get("summary") or "")[:2000],
                    published_at=published_at,
                    language="zh",
                )
            )
        return FetchOutcome(entries=entries[: self.settings.max_entries_per_fetch])
