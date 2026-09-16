# TradingAgents/graph/propagation.py：状态传播。

import logging
from typing import Any

from tradingagents.agents.utils.agent_states import (
    InvestDebateState,
    RiskDebateState,
)

logger = logging.getLogger(__name__)


class Propagator:
    """处理图中的状态初始化和传播。"""

    def __init__(self, max_recur_limit=100):
        """使用配置参数初始化。"""
        self.max_recur_limit = max_recur_limit
        logger.debug("传播器已初始化，max_recur_limit=%d", max_recur_limit)

    def create_initial_state(
        self,
        company_name: str,
        trade_date: str,
        asset_type: str = "stock",
        past_context: str = "",
        instrument_context: str = "",
    ) -> dict[str, Any]:
        """创建 Agent 图的初始状态。

        ``instrument_context`` 是运行开始时解析一次的确定性股票身份字符串（参见
        ``TradingAgentsGraph.resolve_instrument_context``）。为空时，Agent 通过
        ``get_instrument_context_from_state`` 回退到仅包含股票代码的上下文。
        """
        logger.debug(
            "创建初始状态：公司=%s 日期=%s 资产类型=%s 历史上下文=%d 字符 标的上下文=%d 字符",
            company_name, trade_date, asset_type,
            len(past_context or ""), len(instrument_context or ""),
        )
        return {
            "messages": [("human", company_name)],
            # 每位分析师的临时通道（分析师并发运行，每位都从同一个已绑定标的的
            # 提示词开始）。
            "market_messages": [("human", company_name)],
            "sentiment_messages": [("human", company_name)],
            "news_messages": [("human", company_name)],
            "fundamentals_messages": [("human", company_name)],
            # 分析师完成标记（由各自的清理节点写入，分析师屏障读取）。
            "market_done": False,
            "sentiment_done": False,
            "news_done": False,
            "fundamentals_done": False,
            "company_of_interest": company_name,
            "asset_type": asset_type,
            "instrument_context": instrument_context,
            "trade_date": str(trade_date),
            "past_context": past_context,
            "investment_debate_state": InvestDebateState(
                {
                    "bull_history": "",
                    "bear_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "aggressive_history": "",
                    "conservative_history": "",
                    "neutral_history": "",
                    "history": "",
                    "latest_speaker": "",
                    "current_aggressive_response": "",
                    "current_conservative_response": "",
                    "current_neutral_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "sentiment_report": "",
            "news_report": "",
        }

    def get_graph_args(self, callbacks: list | None = None) -> dict[str, Any]:
        """获取调用图所需的参数。

        Args:
            callbacks：可选的回调处理器列表，用于跟踪工具执行。
                       注意：LLM 回调由 LLM 构造器单独处理。
        """
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {
            "stream_mode": "values",
            "config": config,
        }
