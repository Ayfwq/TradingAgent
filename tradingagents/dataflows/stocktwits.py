"""StockTwits 公共股票代码信息流获取器。

本模块直接请求 ``api.stocktwits.com/api/2/streams/symbol/{ticker}.json`` 按代码获取
消息流。接口是否可用取决于 StockTwits 当前的服务策略和运行环境网络。每条消息包含用户标注的情绪字段
（``Bullish``/``Bearish``/null）、正文、时间戳和发布用户。

函数特意保持自包含：超时时间较短，HTTP 或解析失败时优雅降级，并返回字符串，
让调用 Agent 无论网络请求是否成功都获得统一接口。
"""

from __future__ import annotations

import http.client
import json
import logging
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .symbol_utils import crypto_base

logger = logging.getLogger(__name__)

_API = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"
_RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}


def _error_detail(exc: Exception) -> str:
    """Return a compact diagnostic suitable for logs and the traced prompt."""
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    reason = getattr(exc, "reason", None)
    if reason is not None:
        return f"{type(exc).__name__}: {reason}"
    return f"{type(exc).__name__}: {exc}"


def _retry_delay(exc: HTTPError) -> float:
    """Honor a short numeric Retry-After value, with a bounded fallback."""
    headers = getattr(exc, "headers", None)
    value = headers.get("Retry-After") if headers else None
    try:
        return min(max(float(value), 0.0), 5.0) if value else 0.5
    except (TypeError, ValueError):
        return 0.5


def _stocktwits_symbol(ticker: str) -> str:
    """将加密货币交易对映射为 StockTwits 的 ``<BASE>.X`` 约定。

    StockTwits 使用 ``BTC.X`` 列出加密货币（Yahoo 的 ``BTC-USD`` 格式会返回 404），
    因此所有加密货币代码都解析为基础代码加 ``.X``；其他代码转为大写后透传。
    """
    base = crypto_base(ticker)
    return f"{base}.X" if base else ticker.strip().upper()


def fetch_stocktwits_messages(ticker: str, limit: int = 30, timeout: float = 10.0) -> str:
    """获取 ``ticker`` 的近期 StockTwits 消息，并返回可直接注入提示词的纯文本块。

    当接口无法访问、代码没有消息或响应结构异常时返回占位字符串，调用方无需
    为 None 或异常编写特殊处理。
    """
    url = _API.format(ticker=_stocktwits_symbol(ticker))
    req = Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    data = None
    for attempt in range(2):
        try:
            with urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            break
        except HTTPError as exc:
            if exc.code in _RETRYABLE_HTTP_CODES and attempt == 0:
                delay = _retry_delay(exc)
                logger.warning(
                    "StockTwits %s 返回 HTTP %s，%.1f 秒后重试一次",
                    ticker, exc.code, delay,
                )
                time.sleep(delay)
                continue
            detail = _error_detail(exc)
            logger.warning("获取 %s 的 StockTwits 数据失败：%s", ticker, detail)
            return f"<StockTwits 不可用：{detail}>"
        except (OSError, http.client.HTTPException) as exc:
            if attempt == 0:
                logger.warning(
                    "获取 %s 的 StockTwits 数据失败：%s；将重试一次",
                    ticker, _error_detail(exc),
                )
                time.sleep(0.5)
                continue
            detail = _error_detail(exc)
            logger.warning("获取 %s 的 StockTwits 数据失败：%s", ticker, detail)
            return f"<StockTwits 不可用：{detail}>"
        except json.JSONDecodeError as exc:
            detail = f"响应不是有效 JSON：{exc}"
            logger.warning("获取 %s 的 StockTwits 数据失败：%s", ticker, detail)
            return f"<StockTwits 不可用：{detail}>"

    messages = data.get("messages", []) if isinstance(data, dict) else []
    if not messages:
        return f"<未找到 ${ticker.upper()} 的 StockTwits 消息>"

    lines = []
    bullish = bearish = unlabeled = 0
    for m in messages[:limit]:
        created = m.get("created_at", "")
        user = (m.get("user") or {}).get("username", "?")
        entities = m.get("entities") or {}
        sentiment_obj = entities.get("sentiment") or {}
        sentiment = sentiment_obj.get("basic") if isinstance(sentiment_obj, dict) else None
        body = (m.get("body") or "").replace("\n", " ").strip()
        if len(body) > 280:
            body = body[:280] + "…"

        if sentiment == "Bullish":
            bullish += 1
            tag = "Bullish"
        elif sentiment == "Bearish":
            bearish += 1
            tag = "Bearish"
        else:
            unlabeled += 1
            tag = "未标注"
        lines.append(f"[{created} · @{user} · {tag}] {body}")

    total = bullish + bearish + unlabeled
    bull_pct = round(100 * bullish / total) if total else 0
    bear_pct = round(100 * bearish / total) if total else 0
    summary = (
        f"看多：{bullish}（{bull_pct}%）· "
        f"看空：{bearish}（{bear_pct}%）· "
        f"未标注：{unlabeled} · "
        f"总计：最近 {total} 条消息"
    )
    return summary + "\n\n" + "\n".join(lines)
