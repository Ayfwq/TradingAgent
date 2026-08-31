"""Hacker News（Algolia API）适配器，作为热点发现备用源。"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone

import requests

from web.news.models import FetchOutcome, RawEntry
from web.news.sources.base import (
    SourceAdapter,
    SourceError,
    default_resolver,
    http_get_safe,
)


class HackerNewsSource(SourceAdapter):
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
        try:
            payload = json.loads(response.body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise SourceError(f"JSON 解析失败：{exc}") from exc
        hits = payload.get("hits", [])
        if not isinstance(hits, list):
            raise SourceError("Algolia 响应缺少 hits 列表")
        outcome = FetchOutcome()
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            title = str(hit.get("title") or "").strip()
            if not title:
                continue
            external_url = str(hit.get("url") or "").strip()
            url = external_url or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            points = hit.get("points") or 0
            created = hit.get("created_at_i")
            published = (
                datetime.fromtimestamp(int(created), tz=timezone.utc)
                if isinstance(created, (int, float))
                else None
            )
            summary = f"Hacker News 热帖（{points} 分）。" if external_url else title
            outcome.entries.append(
                RawEntry(
                    title=title[:300],
                    url=url[:2000],
                    summary=summary[:2000],
                    published_at=published,
                    language="en",
                )
            )
        outcome.entries = outcome.entries[: self.settings.max_entries_per_fetch]
        return outcome
