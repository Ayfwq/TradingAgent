import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)


@tool
def get_news(
    ticker: Annotated[str, "股票代码"],
    start_date: Annotated[str, "开始日期，格式为 yyyy-mm-dd"],
    end_date: Annotated[str, "结束日期，格式为 yyyy-mm-dd"],
) -> str:
    """
    获取指定股票代码的新闻数据。
    使用配置的 news_data 数据供应商。
    参数：
        ticker (str)：股票代码
        start_date (str)：开始日期，格式为 yyyy-mm-dd
        end_date (str)：结束日期，格式为 yyyy-mm-dd
    返回：
        str：包含新闻数据的格式化字符串。
    """
    logger.debug(
        "调用 get_news：代码=%s，开始日期=%s，结束日期=%s",
        ticker, start_date, end_date,
    )
    try:
        result = route_to_vendor("get_news", ticker, start_date, end_date)
        logger.debug("get_news 返回 %d 个字符：%s", len(result), ticker)
        return result
    except Exception:
        logger.exception(
            "get_news 失败：代码=%s，开始日期=%s，结束日期=%s",
            ticker, start_date, end_date,
        )
        raise

@tool
def get_global_news(
    curr_date: Annotated[str, "当前日期，格式为 yyyy-mm-dd"],
    look_back_days: Annotated[int | None, "向前回看的天数；省略则使用配置默认值"] = None,
    limit: Annotated[int | None, "最多返回的文章数；省略则使用配置默认值"] = None,
) -> str:
    """
    获取全球新闻数据。
    使用配置的 news_data 数据供应商。look_back_days 和 limit 的默认值来自
    DEFAULT_CONFIG（global_news_lookback_days、global_news_article_limit）；
    传入显式值即可覆盖默认设置。

    参数：
        curr_date (str)：当前日期，格式为 yyyy-mm-dd
        look_back_days (int)：向前回看的天数；省略则继承配置
        limit (int)：最多返回的文章数；省略则继承配置

    返回：
        str：包含全球新闻数据的格式化字符串。
    """
    logger.debug(
        "调用 get_global_news：当前日期=%s，回看天数=%s，数量上限=%s",
        curr_date, look_back_days, limit,
    )
    try:
        result = route_to_vendor("get_global_news", curr_date, look_back_days, limit)
        logger.debug("get_global_news 返回 %d 个字符", len(result))
        return result
    except Exception:
        logger.exception(
            "get_global_news 失败：当前日期=%s，回看天数=%s，数量上限=%s",
            curr_date, look_back_days, limit,
        )
        raise

@tool
def get_insider_transactions(
    ticker: Annotated[str, "股票代码"],
) -> str:
    """
    获取公司内幕交易信息。
    使用配置的 news_data 数据供应商。
    参数：
        ticker (str)：公司股票代码
    返回：
        str：内幕交易数据报告。
    """
    logger.debug("调用 get_insider_transactions：代码=%s", ticker)
    try:
        result = route_to_vendor("get_insider_transactions", ticker)
        logger.debug("get_insider_transactions 返回 %d 个字符：%s", len(result), ticker)
        return result
    except Exception:
        logger.exception("get_insider_transactions 失败：代码=%s", ticker)
        raise
