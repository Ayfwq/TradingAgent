import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)


@tool
def get_macro_indicators(
    indicator: Annotated[
        str,
        "宏观指标：易读别名，例如 'cpi'、'core_pce'、"
        "'unemployment', 'fed_funds_rate', '10y_treasury', 'yield_curve', "
        "'real_gdp', 'vix', or a raw FRED series ID such as 'CPIAUCSL'.",
    ],
    curr_date: Annotated[str, "当前日期，格式为 yyyy-mm-dd；作为窗口结束日期"],
    look_back_days: Annotated[
        int | None, "向前回看的窗口天数；省略则使用一年窗口"
    ] = None,
) -> str:
    """
    从 FRED（Federal Reserve Economic Data）获取宏观经济指标时间序列，包括政策利率、
    国债收益率、通胀、就业和经济增长。返回序列标题、单位、频率、最新值、窗口内变化
    以及近期观测表。使用配置的 macro_data 数据供应商。

    参数：
        indicator (str)：易读别名或原始 FRED 序列 ID
        curr_date (str)：当前日期，格式为 yyyy-mm-dd
        look_back_days (int)：向前回看的窗口天数；省略则使用一年窗口

    返回：
        str：宏观序列的格式化 Markdown 报告。
    """
    logger.debug(
        "调用 get_macro_indicators：指标=%s，当前日期=%s，回看天数=%s",
        indicator, curr_date, look_back_days,
    )
    try:
        result = route_to_vendor("get_macro_indicators", indicator, curr_date, look_back_days)
        logger.debug("get_macro_indicators 返回 %d 个字符：%s", len(result), indicator)
        return result
    except Exception:
        logger.exception(
            "get_macro_indicators 失败：指标=%s，当前日期=%s，回看天数=%s",
            indicator, curr_date, look_back_days,
        )
        raise
