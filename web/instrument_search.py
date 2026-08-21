from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Literal

import requests

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client

logger = logging.getLogger(__name__)

Market = Literal["auto", "a_share", "hk", "us"]

_SINA_SUGGEST_URL = "https://suggest3.sinajs.cn/suggest/"
_SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": "Mozilla/5.0 TradingAgents/1.0",
}
_MARKET_TYPES = {
    "11": ("a_share", "A股"),
    "31": ("hk", "港股"),
    "41": ("us", "美股"),
}
_CORP_WORDS = re.compile(
    r"(?:股份有限公司|有限责任公司|集团控股|控股集团|集团|控股|公司|incorporated|corporation|corp\.?|inc\.?|limited|ltd\.?)",
    re.IGNORECASE,
)
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class InstrumentCandidate:
    ticker: str
    company_name: str
    market: str
    market_code: str
    exchange: str
    match_reason: str
    match_score: int
    verified: bool = True
    source: str = "新浪证券目录"


@dataclass
class _CacheEntry:
    expires_at: float
    value: list[dict]


class InstrumentSearchService:
    """Resolve descriptions to tickers, with a market directory as truth.

    The configured quick model only expands natural-language descriptions into
    lookup terms. A model suggestion is never returned until Sina's security
    directory confirms the listing.
    """

    def __init__(self, cache_ttl_seconds: int = 900):
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._cache_lock = threading.Lock()

    def search(
        self,
        query: str,
        market: Market = "auto",
        *,
        use_ai: bool = True,
        limit: int = 8,
    ) -> dict:
        query = " ".join(query.strip().split())
        logger.debug(
            "Instrument search: query=%r market=%s use_ai=%s limit=%s",
            query, market, use_ai, limit,
        )
        if not query:
            raise ValueError("请输入公司名称、股票代码或公司描述")
        if len(query) > 300:
            raise ValueError("公司描述不能超过 300 个字符")

        direct = self._directory_search(query, market)
        ranked = self._rank(query, direct, "direct")
        ai_used = False
        ai_available = True
        ai_message = ""

        if use_ai and not self._has_strong_match(ranked):
            ai_used = True
            try:
                expansions = self._expand_with_configured_model(query, market)
            except Exception as exc:  # noqa: BLE001
                ai_available = False
                ai_message = "AI 描述理解暂不可用，已保留证券目录的直接搜索结果。"
                logger.warning("Instrument search AI expansion unavailable: %s", exc)
                expansions = []

            for index, term in enumerate(expansions):
                if self._normalize(term) == self._normalize(query):
                    continue
                matches = self._directory_search(term, market)
                ranked.extend(self._rank(query, matches, "ai", term, index))

        results = [
            item for item in self._deduplicate_and_sort(ranked) if item.match_score >= 45
        ][:limit]
        if results:
            status = "matched"
            message = ai_message or f"找到 {len(results)} 个经过证券目录验证的候选结果。"
        elif ai_used and not ai_available:
            status = "ai_unavailable"
            message = "没有直接匹配结果，且 AI 描述理解暂不可用。充值后可直接重试。"
        else:
            status = "not_found"
            message = "未找到可验证的公开上市主体。该公司可能尚未上市，也可能使用了其他正式名称。"

        logger.debug(
            "Instrument search result: query=%r status=%s results=%d ai_used=%s",
            query, status, len(results), ai_used,
        )
        return {
            "query": query,
            "market": market,
            "status": status,
            "message": message,
            "ai_used": ai_used,
            "ai_available": ai_available,
            "results": [asdict(item) for item in results],
        }

    def _directory_search(self, query: str, market: Market) -> list[dict]:
        key = (query.casefold(), market)
        now = time.monotonic()
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry and entry.expires_at > now:
                logger.debug("Directory cache hit for %r (%s)", query, market)
                return entry.value

        try:
            response = requests.get(
                _SINA_SUGGEST_URL,
                params={"type": "", "key": query},
                headers=_SINA_HEADERS,
                timeout=(3.05, 8),
            )
            response.raise_for_status()
        except requests.RequestException:
            logger.warning("Sina directory request failed for %r (%s)", query, market)
            raise
        response.encoding = "gbk"
        parsed = self._parse_sina_response(response.text, market)
        logger.debug("Sina directory returned %d row(s) for %r (%s)", len(parsed), query, market)
        with self._cache_lock:
            self._cache[key] = _CacheEntry(now + self.cache_ttl_seconds, parsed)
        return parsed

    @staticmethod
    def _parse_sina_response(text: str, market: Market) -> list[dict]:
        payload_match = re.search(r'="(.*)";?$', text.strip())
        if not payload_match or not payload_match.group(1):
            return []

        results = []
        for row in payload_match.group(1).split(";"):
            fields = row.split(",")
            if len(fields) < 5 or fields[1] not in _MARKET_TYPES:
                continue
            market_code, market_label = _MARKET_TYPES[fields[1]]
            if market != "auto" and market != market_code:
                continue
            ticker = InstrumentSearchService._canonical_ticker(fields[1], fields[2], fields[3])
            if not ticker:
                continue
            name = (fields[4] or fields[0] or ticker).strip()
            results.append(
                {
                    "ticker": ticker,
                    "company_name": name,
                    "market": market_label,
                    "market_code": market_code,
                    "exchange": InstrumentSearchService._exchange_label(fields[1], fields[3]),
                    "raw_names": [fields[0].strip(), name, fields[6].strip() if len(fields) > 6 else ""],
                }
            )
        return results

    @staticmethod
    def _canonical_ticker(type_code: str, code: str, symbol: str) -> str | None:
        code = code.strip().upper()
        symbol = symbol.strip().lower()
        if type_code == "11":
            if symbol.startswith("sh"):
                return f"{code}.SS"
            if symbol.startswith("sz"):
                return f"{code}.SZ"
            if symbol.startswith("bj"):
                return f"{code}.BJ"
            return None
        if type_code == "31" and code.isdigit():
            return f"{str(int(code)).zfill(4)}.HK"
        if type_code == "41":
            return code.upper()
        return None

    @staticmethod
    def _exchange_label(type_code: str, symbol: str) -> str:
        lowered = symbol.lower()
        if type_code == "11":
            if lowered.startswith("sh"):
                return "上海证券交易所"
            if lowered.startswith("sz"):
                return "深圳证券交易所"
            if lowered.startswith("bj"):
                return "北京证券交易所"
            return "中国内地证券市场"
        if type_code == "31":
            return "香港交易所"
        return "美国证券市场"

    def _rank(
        self,
        original_query: str,
        rows: list[dict],
        mode: str,
        expansion: str = "",
        expansion_index: int = 0,
    ) -> list[InstrumentCandidate]:
        ranked = []
        query_norm = self._normalize(original_query)
        for position, row in enumerate(rows):
            names = [self._normalize(value) for value in row["raw_names"] if value]
            ticker_norm = self._normalize(row["ticker"])
            if query_norm in names or query_norm == ticker_norm:
                score = 100
            elif any(query_norm and (query_norm in name or name in query_norm) for name in names):
                score = 91
            elif mode == "direct":
                similarities = [SequenceMatcher(None, query_norm, name).ratio() for name in names]
                score = int(max(similarities or [0]) * 82) - position
            else:
                score = 80 - expansion_index * 4 - position
            if mode == "direct" and position == 0:
                # Sina already ranks its own exact/security-name matches. Keep
                # that signal so an English query such as NVIDIA returns NVDA
                # before ETFs whose longer names merely contain "Nvidia".
                score = max(score, 98)
            reason = (
                "公司名称或股票代码与输入直接匹配"
                if mode == "direct"
                else f"AI 从描述中识别出“{expansion}”，并经证券目录验证"
            )
            ranked.append(
                InstrumentCandidate(
                    ticker=row["ticker"],
                    company_name=row["company_name"],
                    market=row["market"],
                    market_code=row["market_code"],
                    exchange=row["exchange"],
                    match_reason=reason,
                    match_score=max(1, min(100, score)),
                )
            )
        return ranked

    @staticmethod
    def _deduplicate_and_sort(items: list[InstrumentCandidate]) -> list[InstrumentCandidate]:
        best: dict[str, InstrumentCandidate] = {}
        for item in items:
            previous = best.get(item.ticker)
            if previous is None or item.match_score > previous.match_score:
                best[item.ticker] = item
        return sorted(best.values(), key=lambda item: (-item.match_score, item.ticker))

    @staticmethod
    def _has_strong_match(items: list[InstrumentCandidate]) -> bool:
        return bool(items and items[0].match_score >= 90)

    @staticmethod
    def _normalize(value: str) -> str:
        value = _CORP_WORDS.sub("", value.casefold())
        return re.sub(r"[^\w\u4e00-\u9fff]", "", value)

    @staticmethod
    def _expand_with_configured_model(query: str, market: Market) -> list[str]:
        logger.debug(
            "Expanding query with configured model: query=%r market=%s",
            query, market,
        )
        config = DEFAULT_CONFIG.copy()
        client = create_llm_client(
            provider=config["llm_provider"],
            model=config["quick_think_llm"],
            base_url=config.get("backend_url"),
            timeout=25,
            max_retries=0,
            temperature=0,
        )
        llm = client.get_llm()
        market_hint = {
            "auto": "A股、港股或美股",
            "a_share": "A股",
            "hk": "港股",
            "us": "美股",
        }[market]
        prompt = f"""你是上市公司名称检索助手。用户可能忘记股票代码，只记得公司产品、行业、创始人或简称。

用户描述：{query}
目标市场：{market_hint}

请只做关键词提炼，不要断言公司已经上市。输出严格 JSON：
{{"queries": ["最多5个适合证券目录检索的公司正式名、常用中文名、英文名或可能的ticker"]}}

要求：queries 每项必须简短且不超过40字符；不要输出解释或 Markdown；不确定时给出最可能的公司关键词，但不能编造冷门股票代码。
"""
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        match = _JSON_BLOCK.search(content or "")
        if not match:
            return []
        data = json.loads(match.group(0))
        queries = data.get("queries", [])
        if not isinstance(queries, list):
            return []
        cleaned = []
        for item in queries:
            value = " ".join(str(item).strip().split())[:40]
            if value and value not in cleaned:
                cleaned.append(value)
        logger.debug("Model expansion produced %d term(s) for %r", len(cleaned[:5]), query)
        return cleaned[:5]


instrument_search_service = InstrumentSearchService()
