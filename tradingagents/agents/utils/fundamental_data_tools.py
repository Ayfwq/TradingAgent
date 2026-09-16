import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)


@tool
def get_fundamentals(
    ticker: Annotated[str, "股票代码"],
    curr_date: Annotated[str, "当前交易日期，格式为 yyyy-mm-dd"],
) -> str:
    """
    获取指定股票代码的综合基本面数据。
    使用配置的 fundamental_data 数据供应商。
    参数：
        ticker (str)：公司股票代码
        curr_date (str)：当前交易日期，格式为 yyyy-mm-dd
    返回：
        str：包含综合基本面数据的格式化报告。
    """
    logger.debug("调用 get_fundamentals：代码=%s，当前日期=%s", ticker, curr_date)
    try:
        result = route_to_vendor("get_fundamentals", ticker, curr_date)
        logger.debug("get_fundamentals 返回 %d 个字符：%s", len(result), ticker)
        return result
    except Exception:
        logger.exception("get_fundamentals 失败：代码=%s，当前日期=%s", ticker, curr_date)
        raise


@tool
def get_balance_sheet(
    ticker: Annotated[str, "股票代码"],
    freq: Annotated[str, "报告频率：annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "当前交易日期，格式为 yyyy-mm-dd"] = None,
) -> str:
    """
    获取指定股票代码的资产负债表数据。
    使用配置的 fundamental_data 数据供应商。
    参数：
        ticker (str)：公司股票代码
        freq (str)：报告频率：annual/quarterly（默认 quarterly）
        curr_date (str)：当前交易日期，格式为 yyyy-mm-dd
    返回：
        str：包含资产负债表数据的格式化报告。
    """
    logger.debug(
        "调用 get_balance_sheet：代码=%s，频率=%s，当前日期=%s",
        ticker, freq, curr_date,
    )
    try:
        result = route_to_vendor("get_balance_sheet", ticker, freq, curr_date)
        logger.debug("get_balance_sheet 返回 %d 个字符：%s", len(result), ticker)
        return result
    except Exception:
        logger.exception(
            "get_balance_sheet 失败：代码=%s，频率=%s，当前日期=%s",
            ticker, freq, curr_date,
        )
        raise


@tool
def get_cashflow(
    ticker: Annotated[str, "股票代码"],
    freq: Annotated[str, "报告频率：annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "当前交易日期，格式为 yyyy-mm-dd"] = None,
) -> str:
    """
    获取指定股票代码的现金流量表数据。
    使用配置的 fundamental_data 数据供应商。
    参数：
        ticker (str)：公司股票代码
        freq (str)：报告频率：annual/quarterly（默认 quarterly）
        curr_date (str)：当前交易日期，格式为 yyyy-mm-dd
    返回：
        str：包含现金流量表数据的格式化报告。
    """
    logger.debug(
        "调用 get_cashflow：代码=%s，频率=%s，当前日期=%s",
        ticker, freq, curr_date,
    )
    try:
        result = route_to_vendor("get_cashflow", ticker, freq, curr_date)
        logger.debug("get_cashflow 返回 %d 个字符：%s", len(result), ticker)
        return result
    except Exception:
        logger.exception(
            "get_cashflow 失败：代码=%s，频率=%s，当前日期=%s",
            ticker, freq, curr_date,
        )
        raise


@tool
def get_income_statement(
    ticker: Annotated[str, "股票代码"],
    freq: Annotated[str, "报告频率：annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "当前交易日期，格式为 yyyy-mm-dd"] = None,
) -> str:
    """
    获取指定股票代码的利润表数据。
    使用配置的 fundamental_data 数据供应商。
    参数：
        ticker (str)：公司股票代码
        freq (str)：报告频率：annual/quarterly（默认 quarterly）
        curr_date (str)：当前交易日期，格式为 yyyy-mm-dd
    返回：
        str：包含利润表数据的格式化报告。
    """
    logger.debug(
        "调用 get_income_statement：代码=%s，频率=%s，当前日期=%s",
        ticker, freq, curr_date,
    )
    try:
        result = route_to_vendor("get_income_statement", ticker, freq, curr_date)
        logger.debug("get_income_statement 返回 %d 个字符：%s", len(result), ticker)
        return result
    except Exception:
        logger.exception(
            "get_income_statement 失败：代码=%s，频率=%s，当前日期=%s",
            ticker, freq, curr_date,
        )
        raise
