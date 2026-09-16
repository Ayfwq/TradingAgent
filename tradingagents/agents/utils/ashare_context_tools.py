"""A 股特色上下文工具（龙虎榜 / 北向资金 / 涨停池 / 板块 / 业绩预告）。

这些函数是 akshare 数据供应商的包装器，遵循其他数据工具的
``route_to_vendor`` 模式，让 Agent 工具调用看到统一接口。所有工具都会降级
为简短字符串（不会崩溃）：没有记录是有效答案，网络失败则返回
DATA_UNAVAILABLE。
"""

import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)


@tool
def get_lhb_context(
    ticker: Annotated[str, "公司股票代码，例如 600519.SS"],
    curr_date: Annotated[str, "当前交易日期，格式为 YYYY-mm-dd"],
    look_back_days: Annotated[int, "向前搜索龙虎榜记录的天数"] = 10,
) -> str:
    """返回该代码的 A 股龙虎榜上下文：异常波动相关的机构/席位活动（净买入、
    上榜原因、上榜后第 1/2/5 日收益）。仅对 A 股代码调用；大多数股票没有
    龙虎榜记录是正常情况。
    """
    logger.debug(
        "调用 get_lhb_context：代码=%s，当前日期=%s，回看天数=%s",
        ticker, curr_date, look_back_days,
    )
    try:
        result = route_to_vendor("get_lhb_context", ticker, curr_date, look_back_days)
        logger.debug("get_lhb_context 返回 %d 个字符：%s", len(result), ticker)
        return result
    except Exception:
        logger.exception(
            "get_lhb_context 失败：代码=%s，当前日期=%s，回看天数=%s",
            ticker, curr_date, look_back_days,
        )
        raise


@tool
def get_northbound_flow(
    curr_date: Annotated[str, "当前交易日期，格式为 YYYY-mm-dd"],
    look_back_days: Annotated[int, "显示北向资金历史的向前回看天数"] = 10,
) -> str:
    """返回 A 股北向资金流向：港股通流入 A 股的净买入，是最接近机构资金流的
    A 股指标。包含近期每日净买入和最新交易日摘要。数据为全市场范围，不针对
    单个代码。
    """
    logger.debug(
        "调用 get_northbound_flow：当前日期=%s，回看天数=%s",
        curr_date, look_back_days,
    )
    try:
        result = route_to_vendor("get_northbound_flow", curr_date, look_back_days)
        logger.debug("get_northbound_flow 返回 %d 个字符", len(result))
        return result
    except Exception:
        logger.exception(
            "get_northbound_flow 失败：当前日期=%s，回看天数=%s",
            curr_date, look_back_days,
        )
        raise


@tool
def get_limit_up_context(
    ticker: Annotated[str, "公司股票代码，例如 600519.SS"],
    curr_date: Annotated[str, "当前交易日期，格式为 YYYY-mm-dd"],
) -> str:
    """返回 A 股涨停池上下文：代码今日是否涨停（连板数/封板资金/所属行业），
    以及今日涨停池的整体广度（数量、热门板块、最高连板数），作为市场情绪信号。
    仅对 A 股代码调用。
    """
    logger.debug(
        "调用 get_limit_up_context：代码=%s，当前日期=%s",
        ticker, curr_date,
    )
    try:
        result = route_to_vendor("get_limit_up_context", ticker, curr_date)
        logger.debug("get_limit_up_context 返回 %d 个字符：%s", len(result), ticker)
        return result
    except Exception:
        logger.exception(
            "get_limit_up_context 失败：代码=%s，当前日期=%s",
            ticker, curr_date,
        )
        raise


@tool
def get_sector_context(
    ticker: Annotated[str, "公司股票代码，例如 600519.SS"],
    curr_date: Annotated[str, "当前交易日期，格式为 YYYY-mm-dd"],
) -> str:
    """返回 A 股行业板块广度：新浪当日表现最好/最差的行业板块及其龙头股。
    这是全市场上下文，同时标记该代码今日是否为板块龙头。仅对 A 股代码调用。
    """
    logger.debug(
        "调用 get_sector_context：代码=%s，当前日期=%s",
        ticker, curr_date,
    )
    try:
        result = route_to_vendor("get_sector_context", ticker, curr_date)
        logger.debug("get_sector_context 返回 %d 个字符：%s", len(result), ticker)
        return result
    except Exception:
        logger.exception(
            "get_sector_context 失败：代码=%s，当前日期=%s",
            ticker, curr_date,
        )
        raise


@tool
def get_earnings_forecast(
    ticker: Annotated[str, "公司股票代码，例如 600519.SS"],
    curr_date: Annotated[str, "当前交易日期，格式为 YYYY-mm-dd"],
) -> str:
    """返回 A 股业绩预告：公司对最近报告期的自主预测（预告类型/业绩变动/公告日期）。
    这是早于正式财务报表到达的领先信号。仅对 A 股代码调用；A 股业绩预告并非
    强制披露，没有记录是正常情况。
    """
    logger.debug(
        "调用 get_earnings_forecast：代码=%s，当前日期=%s",
        ticker, curr_date,
    )
    try:
        result = route_to_vendor("get_earnings_forecast", ticker, curr_date)
        logger.debug("get_earnings_forecast 返回 %d 个字符：%s", len(result), ticker)
        return result
    except Exception:
        logger.exception(
            "get_earnings_forecast 失败：代码=%s，当前日期=%s",
            ticker, curr_date,
        )
        raise
