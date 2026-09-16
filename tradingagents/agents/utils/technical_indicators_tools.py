import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)


@tool
def get_indicators(
    symbol: Annotated[str, "公司股票代码"],
    indicator: Annotated[str, "要分析并生成报告的技术指标"],
    curr_date: Annotated[str, "当前交易日期，格式为 YYYY-mm-dd"],
    look_back_days: Annotated[int, "向前回看的天数"] = 30,
) -> str:
    """
    获取指定股票代码的单个技术指标。
    使用配置的 technical_indicators 数据供应商。
    参数：
        symbol (str)：公司股票代码，例如 AAPL、TSM
        indicator (str)：单个技术指标名称，例如 'rsi'、'macd'。每个指标调用一次工具。
        curr_date (str)：当前交易日期，格式为 YYYY-mm-dd
        look_back_days (int)：向前回看的天数，默认为 30
    返回：
        str：包含指定代码和指标技术数据的格式化数据表。
    """
    # LLM 有时会把多个指标作为逗号分隔字符串传入，因此拆分后逐个处理。
    logger.debug(
        "调用 get_indicators：代码=%s，指标=%s，当前日期=%s，回看天数=%s",
        symbol, indicator, curr_date, look_back_days,
    )
    indicators = [i.strip().lower() for i in indicator.split(",") if i.strip()]
    results = []
    for ind in indicators:
        try:
            result = route_to_vendor("get_indicators", symbol, ind, curr_date, look_back_days)
            logger.debug("get_indicators 返回 %d 个字符：%s / %s", len(result), symbol, ind)
            results.append(result)
        except ValueError as e:
            logger.exception("get_indicators 失败：%s / %s", symbol, ind)
            results.append(str(e))
    logger.debug("get_indicators 为 %s 汇总了 %d 个结果区块", symbol, len(results))
    return "\n\n".join(results)
