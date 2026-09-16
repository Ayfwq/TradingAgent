"""基于 yfinance 的新闻数据获取函数。"""

import contextlib
import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf
from dateutil.relativedelta import relativedelta

from .config import get_config
from .stockstats_utils import yf_retry
from .symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)


def _as_utc(dt: datetime) -> datetime:
    """将 datetime 规范化为带 UTC 时区的值；无时区值视为 UTC。

    窗口边界来自无时区的 ``yyyy-mm-dd`` 解析值，而文章时间戳可能带有时区，
    因此比较前统一规范化所有操作数。否则过滤结果会依赖主机时区（#1126）。
    """
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _extract_article_data(article: dict) -> dict:
    """从 yfinance 新闻格式提取文章数据（处理嵌套的 content 结构）。"""
    # 处理嵌套的 content 结构。
    if "content" in article:
        content = article["content"]
        title = content.get("title", "No title")
        summary = content.get("summary", "")
        provider = content.get("provider", {})
        publisher = provider.get("displayName", "Unknown")

        # 从 canonicalUrl 或 clickThroughUrl 获取 URL。
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        link = url_obj.get("url", "")

        # 获取发布时间。
        pub_date_str = content.get("pubDate", "")
        pub_date = None
        if pub_date_str:
            with contextlib.suppress(ValueError, AttributeError):
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))

        return {
            "title": title,
            "summary": summary,
            "publisher": publisher,
            "link": link,
            "pub_date": pub_date,
        }
    else:
        # 平面结构的回退处理。解析 epoch 发布时间，使平面文章也能按日期过滤，
        # 否则它们会绕过历史窗口并泄漏未来新闻（#992/#1007）。
        pub_date = None
        ts = article.get("providerPublishTime")
        if ts:
            # Epoch 秒数是 UTC；解析为带 UTC 时区的值，避免过滤结果随主机时区偏移（#1126）。
            with contextlib.suppress(ValueError, OSError, TypeError):
                pub_date = datetime.fromtimestamp(ts, tz=timezone.utc)
        return {
            "title": article.get("title", "No title"),
            "summary": article.get("summary", ""),
            "publisher": article.get("publisher", "Unknown"),
            "link": article.get("link", ""),
            "pub_date": pub_date,
        }


def _in_news_window(pub_date, start_dt, end_dt) -> bool:
    """判断文章是否属于半开区间 ``[start, end + 1 day)``。

    所有操作数都会规范化为 UTC，上边界不包含在内，因此恰好标记为 end_dt 次日
    午夜的文章不会泄漏到历史运行中（#1126）。无日期文章只有在窗口到达当前时间
    （实时运行）时才保留；在历史/回测窗口中排除，因为无法证明它不是未来新闻
    （#992/#1007）。
    """
    end = _as_utc(end_dt)
    if pub_date is not None:
        return _as_utc(start_dt) <= _as_utc(pub_date) < end + timedelta(days=1)
    return end >= datetime.now(timezone.utc) - timedelta(days=1)


def get_news_yfinance(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    使用 yfinance 获取指定股票代码的新闻。

    Args:
        ticker：股票代码（例如 "AAPL"）。
        start_date：yyyy-mm-dd 格式的开始日期。
        end_date：yyyy-mm-dd 格式的结束日期。

    Returns:
        包含新闻文章的格式化字符串。
    """
    logger.debug("已调用 get_news_yfinance：%s（%s 至 %s）", ticker, start_date, end_date)
    article_limit = get_config()["news_article_limit"]
    # 与其他 yfinance 路径一样使用规范代码查询 Yahoo；否则原始经纪商/外汇/加密
    # 别名（XAUUSD、BTCUSD）可能静默返回空新闻。报告标题保留用户输入的代码。
    canonical = normalize_symbol(ticker)
    resolved = "" if canonical == ticker else f" (resolved to {canonical})"
    try:
        stock = yf.Ticker(canonical)
        news = yf_retry(lambda: stock.get_news(count=article_limit))

        if not news:
            return f"未找到 {ticker}{resolved} 的新闻。"

        # 解析日期范围以便过滤。
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        news_str = ""
        filtered_count = 0

        for article in news:
            data = _extract_article_data(article)

            # 仅保留请求窗口内的文章（防止前视）。
            if not _in_news_window(data["pub_date"], start_dt, end_dt):
                continue

            news_str += f"### {data['title']}（来源：{data['publisher']}）\n"
            if data["summary"]:
                news_str += f"{data['summary']}\n"
            if data["link"]:
                news_str += f"链接：{data['link']}\n"
            news_str += "\n"
            filtered_count += 1

        if filtered_count == 0:
            logger.warning(
                "no yfinance news for %s within %s..%s (fetched %d)",
                ticker, start_date, end_date, len(news),
            )
            return f"在 {start_date} 至 {end_date} 期间未找到 {ticker}{resolved} 的新闻。"

        logger.debug("yfinance 为 %s 返回 %d 篇新闻", ticker, filtered_count)
        return f"## {ticker}{resolved} 的新闻（{start_date} 至 {end_date}）：\n\n{news_str}"

    except Exception as e:
        logger.warning("获取 %s 的 yfinance 新闻失败：%s", ticker, e)
        return f"获取 {ticker} 的新闻失败：{str(e)}"


def get_global_news_yfinance(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """
    使用 yfinance Search 获取全球/宏观经济新闻。

    Args:
        curr_date：yyyy-mm-dd 格式的当前日期。
        look_back_days：回溯天数。``None`` 使用当前配置中的
            ``global_news_lookback_days``。
        limit：最多返回的文章数。``None`` 使用当前配置中的
            ``global_news_article_limit``。

    Returns:
        包含全球新闻文章的格式化字符串。
    """
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]
    search_queries = config["global_news_queries"]

    all_news = []
    seen_titles = set()

    try:
        for query in search_queries:
            search = yf_retry(lambda q=query: yf.Search(
                query=q,
                news_count=limit,
                enable_fuzzy_query=True,
            ))

            if search.news:
                for article in search.news:
                    # 同时处理平面和嵌套结构。
                    if "content" in article:
                        data = _extract_article_data(article)
                        title = data["title"]
                    else:
                        title = article.get("title", "")

                    # 按标题去重。
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        all_news.append(article)

            if len(all_news) >= limit:
                break

        if not all_news:
            logger.warning("yfinance 未返回 %s 的全球新闻", curr_date)
            return f"未找到 {curr_date} 的全球新闻。"

        # 计算日期范围。
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - relativedelta(days=look_back_days)
        start_date = start_dt.strftime("%Y-%m-%d")

        news_str = ""
        kept = 0
        for article in all_news[:limit]:
            # 统一提取（平面 + 嵌套）并应用相同的防前视窗口过滤，避免平面文章
            # 泄漏未来新闻（#1007）。
            data = _extract_article_data(article)
            if not _in_news_window(data["pub_date"], start_dt, curr_dt):
                continue
            news_str += f"### {data['title']}（来源：{data['publisher']}）\n"
            if data["summary"]:
                news_str += f"{data['summary']}\n"
            if data["link"]:
                news_str += f"链接：{data['link']}\n"
            news_str += "\n"
            kept += 1

        # 所有候选文章都在窗口外时明确说明，而不是返回空报告（#993）。
        if kept == 0:
            logger.warning("yfinance 在 %s..%s 内没有全球新闻（已获取 %d 条）", start_date, curr_date, len(all_news))
            return f"在 {start_date} 至 {curr_date} 期间未找到全球新闻。"

        logger.debug("yfinance 为 %s 返回 %d 篇全球新闻", curr_date, kept)
        return f"## 全球市场新闻（{start_date} 至 {curr_date}）：\n\n{news_str}"

    except Exception as e:
        logger.warning("获取 %s 的 yfinance 全球新闻失败：%s", curr_date, e)
        return f"获取全球新闻失败：{str(e)}"
