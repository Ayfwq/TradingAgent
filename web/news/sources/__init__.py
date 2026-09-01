"""来源适配器注册表。"""

from __future__ import annotations

from web.news.config import NewsSettings, SourceConfig
from web.news.sources.base import (
    SourceAdapter,
    SourceError,
    canonicalize_url,
    http_get_safe,
    validate_external_url,
)
from web.news.sources.china_finance import CLSFinanceSource, EastMoneyFinanceSource
from web.news.sources.feed import FeedSource
from web.news.sources.hacker_news import HackerNewsSource


def build_adapter(config: SourceConfig, settings: NewsSettings) -> SourceAdapter:
    if config.kind == "cls_finance":
        return CLSFinanceSource(config, settings)
    if config.kind == "eastmoney_finance":
        return EastMoneyFinanceSource(config, settings)
    if config.kind == "hacker_news":
        return HackerNewsSource(config, settings)
    return FeedSource(config, settings)


__all__ = [
    "SourceAdapter",
    "SourceError",
    "build_adapter",
    "canonicalize_url",
    "http_get_safe",
    "validate_external_url",
]
