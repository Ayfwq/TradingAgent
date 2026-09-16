import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)


@tool
def get_prediction_markets(
    topic: Annotated[
        str,
        "事件主题/关键词，例如 'Fed rate cut'、'recession 2026'、"
        "'US election'，或行业/公司事件。",
    ],
    limit: Annotated[int | None, "最多返回的市场数量；省略则默认为 6"] = None,
) -> str:
    """
    从预测市场（Polymarket）获取未来事件的实时市场隐含概率，包括美联储决策、
    衰退、选举、地缘政治和加密资产。返回与主题匹配且交易最活跃的开放市场，
    每个市场包含隐含概率、交易量、结算日期和近期变化。使用配置的
    prediction_markets 数据供应商。

    参数：
        topic (str)：要搜索的事件关键词
        limit (int)：最多返回的市场数量；省略则默认为 6

    返回：
        str：匹配预测市场的格式化 Markdown 报告。
    """
    logger.debug("调用 get_prediction_markets：主题=%s，数量上限=%s", topic, limit)
    try:
        result = route_to_vendor("get_prediction_markets", topic, limit)
        logger.debug("get_prediction_markets 返回 %d 个字符：主题=%s", len(result), topic)
        return result
    except Exception:
        logger.exception("get_prediction_markets 失败：主题=%s，数量上限=%s", topic, limit)
        raise
