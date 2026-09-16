import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.market_data_validator import build_verified_market_snapshot

logger = logging.getLogger(__name__)


@tool
def get_verified_market_snapshot(
    symbol: Annotated[str, "公司股票代码"],
    curr_date: Annotated[str, "当前交易日期，格式为 YYYY-mm-dd"],
    look_back_days: Annotated[
        int, "用于合理性检查的近期交易行数"
    ] = 30,
) -> str:
    """用于验证精确市场数据引用的确定性快照。

    返回 curr_date 当日或之前最近一行 OHLCV、常见技术指标和近期收盘价。在准确
    陈述价格水平、布林带、RSI、MACD、移动平均线、支撑/阻力或历史比较前应调用
    此工具，并将其作为事实来源。
    """
    logger.debug(
        "调用 get_verified_market_snapshot：代码=%s，当前日期=%s，回看天数=%s",
        symbol, curr_date, look_back_days,
    )
    try:
        result = build_verified_market_snapshot(symbol, curr_date, look_back_days)
        logger.debug(
            "get_verified_market_snapshot 返回 %d 个字符：%s",
            len(result), symbol,
        )
        return result
    except Exception:
        logger.exception(
            "get_verified_market_snapshot 失败：代码=%s，当前日期=%s，回看天数=%s",
            symbol, curr_date, look_back_days,
        )
        raise
