"""获取与股票代码相关的 Reddit 讨论帖。

默认路径是 Reddit 的公开 Atom/RSS 搜索源
（``reddit.com/r/{sub}/search.rss``）。功能更丰富的 JSON 搜索端点
（``/search.json``）对公开客户端通常会被 WAF 拦截（``HTTP 403``），
每次调用都探测它还会使请求量翻倍，触发 Reddit 的单 IP 速率限制，
导致 RSS 备用路径收到 ``429``，因此保留（``_fetch_subreddit_json``）
但默认不使用。收到 429 时会退避一次（遵循 ``Retry-After``）。
RSS 不提供得分和评论数，因此会标记这些帖子，格式化器也会省略相应指标，
避免显示虚假的零值。

无需 API 密钥。函数返回可直接注入提示词的格式化纯文本块，并以占位文本
优雅处理异常，而不是抛出错误，让调用方无需专门处理缺失数据。
"""

from __future__ import annotations

import html
import http.client
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .symbol_utils import crypto_base

logger = logging.getLogger(__name__)

_API = "https://www.reddit.com/r/{sub}/search.json?{qs}"
_RSS = "https://www.reddit.com/r/{sub}/search.rss?{qs}"
# 按照 Reddit API 规范设置可识别的 User-Agent。Reddit 会拦截裸的
# “Mozilla/5.0”或“curl/…”等通用匿名标识，但两个端点都接受此标识；
# 即使 JSON 搜索端点返回 403，RSS 源仍可使用，因此无需伪装浏览器。
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# 按股票讨论信号密度大致排序的默认 subreddit。wallstreetbets 数量最多但噪声
# 也最大；stocks / investing 的趋势更稳健。调用方可以覆盖此配置。
DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")


def _search_qs(ticker: str, limit: int) -> str:
    return urlencode({
        "q": ticker,
        "restrict_sr": "on",
        "sort": "new",
        "t": "week",  # 最近 7 天
        "limit": limit,
    })


def _iso_to_timestamp(iso_str: str | None) -> float | None:
    """将 Atom 的 ``published`` 时间戳解析为 UTC 时间戳，失败时返回 None。"""
    if not iso_str:
        return None
    try:
        normalized = iso_str[:-1] + "+00:00" if iso_str.endswith("Z") else iso_str
        return datetime.fromisoformat(normalized).timestamp()
    except (ValueError, TypeError):
        return None


def _strip_html(content: str) -> str:
    """将 Reddit 嵌入 Atom 条目的 HTML 正文转换为纯文本。"""
    if not content:
        return ""
    # Reddit 会将真正的 selftext 放在 SC_OFF / SC_ON 标记之间。
    if "<!-- SC_OFF -->" in content and "<!-- SC_ON -->" in content:
        content = content.split("<!-- SC_OFF -->")[1].split("<!-- SC_ON -->")[0]
    text = re.sub(r"<[^>]+>", " ", content)
    return " ".join(html.unescape(text).split())


def _retry_after_seconds(exc: HTTPError) -> float | None:
    """读取 429 的 ``Retry-After`` 标头确定等待秒数，最多等待 30 秒。"""
    try:
        val = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
        return min(float(val), 30.0) if val else None
    except (ValueError, TypeError, AttributeError):
        return None


def _fetch_subreddit_rss(
    ticker: str,
    sub: str,
    limit: int,
    timeout: float,
    _retry: bool = True,
) -> list[dict]:
    """默认路径：解析某个 subreddit 的公开 Atom 搜索源。

    该源不包含得分和评论数，因此这些字段保持为 None，并以
    ``source="rss"`` 标记帖子以便如实展示。收到 429（Reddit 的单 IP
    速率限制）时会退避一次；如果存在 ``Retry-After`` 则遵循其值，
    然后再放弃，避免短暂请求突发导致信息源为空。
    """
    url = _RSS.format(sub=sub, qs=_search_qs(ticker, limit))
    req = Request(url, headers={"User-Agent": _UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            root = ET.fromstring(resp.read())
    except HTTPError as exc:
        if exc.code == 429 and _retry:
            wait = _retry_after_seconds(exc) or 5.0
            logger.warning(
                "r/%s 的 Reddit RSS 返回 429 · %s —— 退避 %.1f 秒后重试一次",
                sub, ticker, wait,
            )
            time.sleep(wait)
            return _fetch_subreddit_rss(ticker, sub, limit, timeout, _retry=False)
        logger.warning("获取 r/%s 的 Reddit RSS 失败 · %s：%s", sub, ticker, exc)
        return []
    except (OSError, http.client.HTTPException, ET.ParseError) as exc:
        # OSError 覆盖 URLError、TimeoutError 和连接重置；HTTPException 覆盖
        # 分块传输错误（IncompleteRead/BadStatusLine，#1024）。
        logger.warning("获取 r/%s 的 Reddit RSS 失败 · %s：%s", sub, ticker, exc)
        return []

    posts = []
    for entry in root.findall("atom:entry", _ATOM_NS)[:limit]:
        title_el = entry.find("atom:title", _ATOM_NS)
        published_el = entry.find("atom:published", _ATOM_NS)
        content_el = entry.find("atom:content", _ATOM_NS)
        posts.append({
            "title": (title_el.text if title_el is not None else "") or "",
            "score": None,
            "num_comments": None,
            "created_utc": _iso_to_timestamp(
                published_el.text if published_el is not None else None
            ),
            "selftext": _strip_html(content_el.text if content_el is not None else ""),
            "source": "rss",
        })
    return posts


def _fetch_subreddit_json(
    ticker: str,
    sub: str,
    limit: int,
    timeout: float,
) -> list[dict]:
    """功能更丰富的 JSON 搜索路径（包含得分和评论数）。

    Reddit 的 WAF 目前会对非 OAuth 客户端在此端点返回 ``403 Blocked``
   （问题 #862），因此默认不使用——每次请求调用它只会使单 IP 速率限制下
    的请求量翻倍，并触发 RSS 备用路径的 429。保留此路径以便将来 WAF 放宽
    限制或接入 OAuth token；失败时会降级到 RSS。
    """
    url = _API.format(sub=sub, qs=_search_qs(ticker, limit))
    req = Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
        children = (payload.get("data") or {}).get("children") or []
        return [c.get("data", {}) for c in children if isinstance(c, dict)]
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        logger.warning(
            "获取 r/%s 的 Reddit JSON 失败 · %s：%s —— 回退到 RSS 源。",
            sub, ticker, exc,
        )
        return _fetch_subreddit_rss(ticker, sub, limit, timeout)


def _fetch_subreddit(
    ticker: str,
    sub: str,
    limit: int,
    timeout: float,
) -> list[dict]:
    """获取一个 subreddit，优先使用 RSS。

    JSON 搜索端点对公开客户端通常会被 WAF 拦截（403），因此直接使用
    RSS 源；该源能稳定接受可识别的 User-Agent，也能将 Reddit 单 IP
    速率限制下的请求量减半。
    """
    return _fetch_subreddit_rss(ticker, sub, limit, timeout)


def fetch_reddit_posts(
    ticker: str,
    subreddits: Iterable[str] = DEFAULT_SUBREDDITS,
    limit_per_sub: int = 5,
    timeout: float = 10.0,
    inter_request_delay: float = 1.0,
) -> str:
    """获取金融类 subreddit 中提及 ``ticker`` 的最新 Reddit 帖子，
    并将其返回为格式化纯文本块。

    ``inter_request_delay`` 用于控制（目前仅 RSS）各 subreddit 请求的间隔，
    使其低于 Reddit 公开的单 IP 速率限制；结合 RSS 优先路径，即使连续运行
    多次分析，也能降低触发 429 的概率。
    """
    # 加密货币以 Yahoo 交易对（BTC-USD）的形式传入；搜索基础代码
    #（“BTC”）才能真正匹配讨论内容，而不是几乎搜不到结果。
    ticker = crypto_base(ticker) or ticker
    blocks = []
    total_posts = 0
    for i, sub in enumerate(subreddits):
        if i > 0:
            time.sleep(inter_request_delay)
        posts = _fetch_subreddit(ticker, sub, limit_per_sub, timeout)
        total_posts += len(posts)
        if not posts:
            blocks.append(f"r/{sub}：<过去 7 天未找到提及 {ticker.upper()} 的帖子>")
            continue

        via_rss = any(p.get("source") == "rss" for p in posts)
        header = f"r/{sub} —— 最近有 {len(posts)} 条提及 {ticker.upper()} 的帖子"
        header += "（来自 RSS 源；得分和评论数不可用）：" if via_rss else "："
        lines = [header]
        for p in posts:
            title = (p.get("title") or "").replace("\n", " ").strip()
            score = p.get("score")
            comments = p.get("num_comments")
            created = p.get("created_utc")
            created_str = (
                time.strftime("%Y-%m-%d", time.gmtime(created)) if created else "?"
            )
            # RSS 备用路径没有得分和评论数；只有存在时才显示，避免打印虚假零值。
            meta = created_str
            if score is not None and comments is not None:
                meta += f" · {score:>4}↑ · {comments:>3}c"
            selftext = (p.get("selftext") or "").replace("\n", " ").strip()
            if len(selftext) > 240:
                selftext = selftext[:240] + "…"
            lines.append(
                f"  [{meta}] {title}"
                + (f"\n    正文摘录：{selftext}" if selftext else "")
            )
        blocks.append("\n".join(lines))

    if total_posts == 0:
        return (
            f"<过去 7 天在 {', '.join(f'r/{s}' for s in subreddits)} 中未找到"
            f"提及 {ticker.upper()} 的 Reddit 帖子>"
        )
    return "\n\n".join(blocks)
