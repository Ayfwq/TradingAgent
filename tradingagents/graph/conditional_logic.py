# TradingAgents/graph/conditional_logic.py：图条件逻辑。

import logging

from tradingagents.agents.utils.agent_states import AgentState

logger = logging.getLogger(__name__)


class ConditionalLogic:
    """处理用于确定图流转的条件逻辑。"""

    def __init__(
        self,
        max_debate_rounds=1,
        max_risk_discuss_rounds=1,
        max_tool_rounds: int = 3,
    ):
        """使用配置参数初始化。

        ``max_tool_rounds`` 限制每个调用工具的分析师在被强制输出报告前可以执行的
        LLM->工具->LLM 迭代次数。否则健谈的模型可能无限循环调用工具（唯一限制是
        整个图的递归上限），反复获取已有数据并消耗 Token。
        """
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds
        self.max_tool_rounds = max_tool_rounds

    def _tool_rounds(self, state: AgentState, messages_key: str) -> int:
        """统计当前分析师片段已完成的工具调用轮次。

        每个分析师拥有独立消息通道（由自己的清理节点清空），因此通道只包含该
        分析师的回合：每轮一个带 tool_calls 的 AIMessage。
        """
        return sum(
            1 for m in state.get(messages_key, []) if getattr(m, "tool_calls", None)
        )

    def _cap_reached(self, state: AgentState, messages_key: str, tools_node: str, clear_node: str) -> str:
        """路由分析师：请求工具且未达到轮次上限时进入工具节点，否则清理消息并输出报告。"""
        last_message = state.get(messages_key, [])[-1] if state.get(messages_key) else None
        if (
            last_message is not None
            and getattr(last_message, "tool_calls", None)
            and self._tool_rounds(state, messages_key) < self.max_tool_rounds
        ):
            logger.debug(
                "分析师 %s 请求更多工具（第 %d/%d 轮）-> %s",
                messages_key, self._tool_rounds(state, messages_key),
                self.max_tool_rounds, tools_node,
            )
            return tools_node
        logger.debug("分析师 %s 已完成工具轮次 -> %s", messages_key, clear_node)
        return clear_node

    def should_continue_market(self, state: AgentState):
        """判断市场分析是否继续。"""
        return self._cap_reached(state, "market_messages", "tools_market", "Msg Clear Market")

    def should_continue_social(self, state: AgentState):
        """判断情绪分析师的工具轮次是否继续。

        方法名保留旧的 ``social`` 后缀，以匹配 ``AnalystType.SOCIAL = "social"``
        线路值（兼容已保存配置）；返回的 ``clear_node`` 标签使用 v0.2.5 的重命名，
        与执行计划注册的节点一致。
        """
        return self._cap_reached(state, "sentiment_messages", "tools_social", "Msg Clear Sentiment")

    def should_continue_news(self, state: AgentState):
        """判断新闻分析是否继续。"""
        return self._cap_reached(state, "news_messages", "tools_news", "Msg Clear News")

    def should_continue_fundamentals(self, state: AgentState):
        """判断基本面分析是否继续。"""
        return self._cap_reached(state, "fundamentals_messages", "tools_fundamentals", "Msg Clear Fundamentals")

    def should_continue_debate(self, state: AgentState) -> str:
        """判断投资辩论是否继续。"""

        if (
            state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds
        ):  # 两位 Agent 往返 3 轮。
            logger.debug(
                "投资辩论在 %d 次响应后完成（上限=%d）-> 研究经理",
                state["investment_debate_state"]["count"], 2 * self.max_debate_rounds,
            )
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            logger.debug(
                "看多方发言（第 %d/%d 轮）-> 看空研究员",
                state["investment_debate_state"]["count"], 2 * self.max_debate_rounds,
            )
            return "Bear Researcher"
        logger.debug(
            "看空方发言（第 %d/%d 轮）-> 看多研究员",
            state["investment_debate_state"]["count"], 2 * self.max_debate_rounds,
        )
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """判断风险分析是否继续。"""
        if (
            state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds
        ):  # 三位 Agent 往返 3 轮。
            logger.debug(
                "风险辩论在 %d 次响应后完成（上限=%d）-> 投资组合经理",
                state["risk_debate_state"]["count"], 3 * self.max_risk_discuss_rounds,
            )
            return "Portfolio Manager"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            logger.debug(
                "激进方发言（第 %d/%d 轮）-> 保守分析师",
                state["risk_debate_state"]["count"], 3 * self.max_risk_discuss_rounds,
            )
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            logger.debug(
                "保守方发言（第 %d/%d 轮）-> 中性分析师",
                state["risk_debate_state"]["count"], 3 * self.max_risk_discuss_rounds,
            )
            return "Neutral Analyst"
        logger.debug(
            "中性方发言（第 %d/%d 轮）-> 激进分析师",
            state["risk_debate_state"]["count"], 3 * self.max_risk_discuss_rounds,
        )
        return "Aggressive Analyst"
