# TradingAgents/graph/setup.py：图构建。

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import (
    create_aggressive_debator,
    create_bear_researcher,
    create_bull_researcher,
    create_conservative_debator,
    create_fundamentals_analyst,
    create_market_analyst,
    create_msg_delete,
    create_neutral_debator,
    create_news_analyst,
    create_portfolio_manager,
    create_research_manager,
    create_sentiment_analyst,
    create_trader,
)
from tradingagents.agents.utils.agent_states import AgentState

from .analyst_execution import build_analyst_execution_plan
from .conditional_logic import ConditionalLogic

logger = logging.getLogger(__name__)

# 共享条件路由器可能返回的所有目标。由路由器驱动的每条边都映射这些目标，
# 因此即使提示词/i18n 重构导致发言者标签漂移，也不会命中缺失的 path_map 项并使
# LangGraph 在运行中崩溃（#1088）。
DEBATE_PATH_MAP = {
    "Bull Researcher": "Bull Researcher",
    "Bear Researcher": "Bear Researcher",
    "Research Manager": "Research Manager",
}
RISK_ANALYSIS_PATH_MAP = {
    "Aggressive Analyst": "Aggressive Analyst",
    "Conservative Analyst": "Conservative Analyst",
    "Neutral Analyst": "Neutral Analyst",
    "Portfolio Manager": "Portfolio Manager",
}

# 分析师汇合屏障。LangGraph 1.2 的 fan-in 只会合并在同一个超级步骤（深度层）到达
# 的信号。分析师会在 Agent<->工具之间循环不同轮次，因此清理节点位于不同层：
# 直接汇入“Bull Researcher”会过早触发（辩论只看到部分报告），晚到的清理信号又会
# 再次触发，破坏辩论循环（不可归约的辩论键会产生 InvalidUpdateError）。屏障会吸收
# 这些早到信号：每次清理节点到达时重新运行，检查每位选中分析师是否完成（报告存在
# 或清理节点已标记完成），然后才进入辩论。空路由元组表示不执行操作，图会等待剩余
# 分析师（仍在等待的任务会让图保持运行）。
def _make_analyst_barrier(ready_checks: list[tuple[str, str]]):
    """``ready_checks``：每位分析师对应的（report_key、done_key）列表。"""

    def _analyst_barrier_node(state):
        # 节点本身不写入任何内容，由条件边决定下一步。
        return {}

    def _analyst_barrier_route(state):
        missing = [
            (report_key, done_key)
            for report_key, done_key in ready_checks
            if not state.get(report_key) and not state.get(done_key)
        ]
        if missing:
            # 本步骤没有目标：吸收过早到达的清理信号。
            #（返回 None 会被当作节点名称，导致 KeyError。）
            logger.debug(
                "分析师屏障等待 %s；本步骤不执行操作",
                ", ".join(f"{r}/{d}" for r, d in missing),
            )
            return ()
        logger.debug("分析师屏障：所有分析师已完成 -> 看多研究员")
        return ("Bull Researcher",)

    return _analyst_barrier_node, _analyst_barrier_route


class GraphSetup:
    """处理 Agent 图的设置和配置。"""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
    ):
        """使用必要组件初始化。"""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic

    def setup_graph(
        self, selected_analysts=("market", "social", "news", "fundamentals")
    ):
        """设置并编译 Agent 工作流图。

        Args:
            selected_analysts（list）：要包含的分析师类型列表。可选值：
                - "market"：市场分析师。
                - "social"：情绪分析师。
                - "news"：新闻分析师。
                - "fundamentals"：基本面分析师。
        """
        plan = build_analyst_execution_plan(selected_analysts)
        logger.debug(
            "Building graph with %d analyst(s): %s",
            len(plan.specs), ", ".join(spec.key for spec in plan.specs),
        )

        analyst_factories = {
            "market": lambda: create_market_analyst(self.quick_thinking_llm),
            "social": lambda: create_sentiment_analyst(self.quick_thinking_llm),
            "news": lambda: create_news_analyst(self.quick_thinking_llm),
            "fundamentals": lambda: create_fundamentals_analyst(self.quick_thinking_llm),
        }

        # 创建研究员和经理节点。
        bull_researcher_node = create_bull_researcher(self.quick_thinking_llm)
        bear_researcher_node = create_bear_researcher(self.quick_thinking_llm)
        research_manager_node = create_research_manager(self.deep_thinking_llm)
        trader_node = create_trader(self.quick_thinking_llm)

        # 创建风险分析节点。
        aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
        portfolio_manager_node = create_portfolio_manager(self.deep_thinking_llm)

        # 创建工作流。
        workflow = StateGraph(AgentState)

        # 将分析师节点加入图。
        for spec in plan.specs:
            workflow.add_node(spec.agent_node, analyst_factories[spec.key]())
            workflow.add_node(
                spec.clear_node,
                create_msg_delete(spec.messages_key, done_key=spec.done_key),
            )
            workflow.add_node(spec.tool_node, self.tool_nodes[spec.key])

        # 分析师汇合屏障（见 _make_analyst_barrier 文档字符串）：所有分析师清理节点
        # 都汇入这个节点；只有所有分析师完成后才放行辩论，并吸收跨层的早到信号。
        barrier_node, barrier_route = _make_analyst_barrier(
            [(spec.report_key, spec.done_key) for spec in plan.specs]
        )
        workflow.add_node("Analyst Barrier", barrier_node)

        # 添加其他节点。
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)

        # 定义边。
        # 并行分析师分发：START 同时进入每位选中的分析师。每位分析师在独立消息
        # 通道上运行自己的工具循环；清理节点汇入“Bull Researcher”，后者等待所有
        # 分析师完成（LangGraph fan-in），辩论因此可以看到全部报告。这取代旧的串行
        # 链（analyst1 -> ... -> analystN），是最大的延迟优化，因为四位分析师相互独立。
        for spec in plan.specs:
            workflow.add_edge(START, spec.agent_node)
            workflow.add_conditional_edges(
                spec.agent_node,
                getattr(self.conditional_logic, f"should_continue_{spec.key}"),
                [spec.tool_node, spec.clear_node],
            )
            workflow.add_edge(spec.tool_node, spec.agent_node)
            workflow.add_edge(spec.clear_node, "Analyst Barrier")

        # 屏障 -> 辩论：只有每位分析师的报告都存在时才进入；否则屏障不执行操作，
        # 图等待晚到的分析师（LangGraph 会在任务仍等待时继续运行）。
        workflow.add_conditional_edges(
            "Analyst Barrier",
            barrier_route,
            {"Bull Researcher": "Bull Researcher"},
        )

        # 两条研究辩论边共享完整的 DEBATE_PATH_MAP（#1088）。
        for debate_node in ("Bull Researcher", "Bear Researcher"):
            workflow.add_conditional_edges(
                debate_node,
                self.conditional_logic.should_continue_debate,
                DEBATE_PATH_MAP,
            )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        # 三条风险边共享完整的 RISK_ANALYSIS_PATH_MAP（#1088）。
        for risk_node in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"):
            workflow.add_conditional_edges(
                risk_node,
                self.conditional_logic.should_continue_risk_analysis,
                RISK_ANALYSIS_PATH_MAP,
            )

        workflow.add_edge("Portfolio Manager", END)

        logger.debug(
            "Workflow assembled with nodes: %s",
            ", ".join(sorted(workflow.nodes.keys())),
        )
        return workflow
