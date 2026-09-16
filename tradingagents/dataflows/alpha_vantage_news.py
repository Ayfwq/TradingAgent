import logging

from .alpha_vantage_common import _make_api_request, format_datetime_for_api

logger = logging.getLogger(__name__)


def get_news(ticker, start_date, end_date) -> dict[str, str] | str:
    """返回全球主要新闻机构的实时及历史市场新闻与情绪数据。

    覆盖股票、加密货币、外汇以及财政政策、并购、IPO 等主题。

    Args:
        ticker：新闻文章对应的股票代码。
        start_date：新闻搜索开始日期。
        end_date：新闻搜索结束日期。

    Returns:
        包含新闻情绪数据的字典或 JSON 字符串。
    """
    logger.debug("已调用 get_news：%s，范围 %s..%s", ticker, start_date, end_date)
    params = {
        "tickers": ticker,
        "time_from": format_datetime_for_api(start_date),
        "time_to": format_datetime_for_api(end_date),
    }

    result = _make_api_request("NEWS_SENTIMENT", params)
    logger.debug("Alpha Vantage 为 %s 返回 %d 字节的新闻（%s..%s）", ticker, len(result), start_date, end_date)
    return result

def get_global_news(curr_date, look_back_days: int = 7, limit: int = 50) -> dict[str, str] | str:
    """返回不按股票代码过滤的全球市场新闻与情绪数据。

    覆盖金融市场、经济等广泛市场主题。

    Args:
        curr_date：yyyy-mm-dd 格式的当前日期。
        look_back_days：回溯天数（默认 7 天）。
        limit：最大文章数量（默认 50）。

    Returns:
        包含全球新闻情绪数据的字典或 JSON 字符串。
    """
    logger.debug("已调用 get_global_news：%s，look_back_days=%d，limit=%d", curr_date, look_back_days, limit)
    from datetime import datetime, timedelta

    # 计算开始日期。
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - timedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    params = {
        "topics": "financial_markets,economy_macro,economy_monetary",
        "time_from": format_datetime_for_api(start_date),
        "time_to": format_datetime_for_api(curr_date),
        "limit": str(limit),
    }

    result = _make_api_request("NEWS_SENTIMENT", params)
    logger.debug("Alpha Vantage 为 %s..%s 返回 %d 字节的全球新闻", start_date, curr_date, len(result))
    return result


def get_insider_transactions(symbol: str) -> dict[str, str] | str:
    """返回主要利益相关者的最新及历史内幕交易记录。

    覆盖创始人、高管、董事会成员等人的交易。

    Args:
        symbol：股票代码，例如 "IBM"。

    Returns:
        包含内幕交易数据的字典或 JSON 字符串。
    """
    logger.debug("已调用 get_insider_transactions：%s", symbol)
    params = {
        "symbol": symbol,
    }

    result = _make_api_request("INSIDER_TRANSACTIONS", params)
    logger.debug("Alpha Vantage 为 %s 返回 %d 字节的内部人交易数据", symbol, len(result))
    return result
