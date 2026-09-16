import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)


@tool
def get_stock_data(
    symbol: Annotated[str, "公司股票代码"],
    start_date: Annotated[str, "开始日期，格式为 yyyy-mm-dd"],
    end_date: Annotated[str, "结束日期，格式为 yyyy-mm-dd"],
) -> str:
    """
    获取指定股票代码的价格数据（OHLCV）。
    使用配置的 core_stock_apis 数据供应商。
    参数：
        symbol (str)：公司股票代码，例如 AAPL、TSM
        start_date (str)：开始日期，格式为 yyyy-mm-dd
        end_date (str)：结束日期，格式为 yyyy-mm-dd
    返回：
        str：包含指定股票代码和日期范围价格数据的格式化数据表。
    """
    logger.debug(
        "调用 get_stock_data：代码=%s，开始日期=%s，结束日期=%s",
        symbol, start_date, end_date,
    )
    try:
        result = route_to_vendor("get_stock_data", symbol, start_date, end_date)
        logger.debug("get_stock_data 返回 %d 个字符：%s", len(result), symbol)
        return result
    except Exception:
        logger.exception(
            "get_stock_data 失败：代码=%s，开始日期=%s，结束日期=%s",
            symbol, start_date, end_date,
        )
        raise
