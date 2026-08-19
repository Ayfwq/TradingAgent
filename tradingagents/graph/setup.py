# TradingAgents/graph/setup.py

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

# Every target a shared conditional router can return. Each edge driven by the
# router maps all of them, so a fall-through return (e.g. under prompt/i18n/
# refactor drift in the speaker labels) can never hit a missing path_map entry
# and crash LangGraph mid-run (#1088).
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

# Analyst fan-in barrier. LangGraph 1.2 fan-in only joins signals that arrive
# in the SAME super-step (depth layer). Analysts loop agent<->tools for a
# variable number of rounds, so their clear nodes land in different layers:
# a naive join into "Bull Researcher" fires early (debate starts with partial
# reports) and then re-fires when the late clears arrive — corrupting the
# debate loop (InvalidUpdateError on the non-reducer debate key). The barrier
# absorbs those early signals: it re-runs whenever a clear arrives, checks
# that every selected analyst has finished (report present OR its clear node
# marked it done), and only then routes into the debate. An empty route tuple
# falls through to no-op, so the graph simply waits for the remaining
# analysts (still-pending tasks keep it alive).
def _make_analyst_barrier(ready_checks: list[tuple[str, str]]):
    """``ready_checks``: list of (report_key, done_key) per analyst."""

    def _analyst_barrier_node(state):
        # The node itself writes nothing; its conditional edge decides.
        return {}

    def _analyst_barrier_route(state):
        missing = [
            (report_key, done_key)
            for report_key, done_key in ready_checks
            if not state.get(report_key) and not state.get(done_key)
        ]
        if missing:
            # No destination this step: absorbs the early clear signal.
            # (Returning None would be treated as a node name -> KeyError.)
            return ()
        return ("Bull Researcher",)

    return _analyst_barrier_node, _analyst_barrier_route


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic

    def setup_graph(
        self, selected_analysts=("market", "social", "news", "fundamentals")
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst
                - "social": Social media analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
        """
        plan = build_analyst_execution_plan(selected_analysts)

        analyst_factories = {
            "market": lambda: create_market_analyst(self.quick_thinking_llm),
            "social": lambda: create_sentiment_analyst(self.quick_thinking_llm),
            "news": lambda: create_news_analyst(self.quick_thinking_llm),
            "fundamentals": lambda: create_fundamentals_analyst(self.quick_thinking_llm),
        }

        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(self.quick_thinking_llm)
        bear_researcher_node = create_bear_researcher(self.quick_thinking_llm)
        research_manager_node = create_research_manager(self.deep_thinking_llm)
        trader_node = create_trader(self.quick_thinking_llm)

        # Create risk analysis nodes
        aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
        portfolio_manager_node = create_portfolio_manager(self.deep_thinking_llm)

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add analyst nodes to the graph
        for spec in plan.specs:
            workflow.add_node(spec.agent_node, analyst_factories[spec.key]())
            workflow.add_node(
                spec.clear_node,
                create_msg_delete(spec.messages_key, done_key=spec.done_key),
            )
            workflow.add_node(spec.tool_node, self.tool_nodes[spec.key])

        # Analyst fan-in barrier (see _make_analyst_barrier docstring): the
        # single node every analyst clear fans into; it gates the debate on
        # all analysts being finished, absorbing cross-layer early signals.
        barrier_node, barrier_route = _make_analyst_barrier(
            [(spec.report_key, spec.done_key) for spec in plan.specs]
        )
        workflow.add_node("Analyst Barrier", barrier_node)

        # Add other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)

        # Define edges
        # Parallel analyst fan-out: START enters every selected analyst at
        # once. Each analyst runs its own tools loop on its private message
        # channel; the clear node fans back into "Bull Researcher", whose
        # execution waits for ALL analysts to finish (LangGraph fan-in) — the
        # debate then sees every report. This replaces the old serial chain
        # (analyst1 -> ... -> analystN) and is the single biggest latency win:
        # the four analysts are data-independent.
        for spec in plan.specs:
            workflow.add_edge(START, spec.agent_node)
            workflow.add_conditional_edges(
                spec.agent_node,
                getattr(self.conditional_logic, f"should_continue_{spec.key}"),
                [spec.tool_node, spec.clear_node],
            )
            workflow.add_edge(spec.tool_node, spec.agent_node)
            workflow.add_edge(spec.clear_node, "Analyst Barrier")

        # Barrier -> debate: only when every analyst report exists; otherwise
        # the barrier falls through (no-op) and the graph waits for the late
        # analysts (LangGraph keeps running while tasks are still pending).
        workflow.add_conditional_edges(
            "Analyst Barrier",
            barrier_route,
            {"Bull Researcher": "Bull Researcher"},
        )

        # Both research-debate edges share the complete DEBATE_PATH_MAP (#1088).
        for debate_node in ("Bull Researcher", "Bear Researcher"):
            workflow.add_conditional_edges(
                debate_node,
                self.conditional_logic.should_continue_debate,
                DEBATE_PATH_MAP,
            )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        # All three risk edges share the complete RISK_ANALYSIS_PATH_MAP (#1088).
        for risk_node in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"):
            workflow.add_conditional_edges(
                risk_node,
                self.conditional_logic.should_continue_risk_analysis,
                RISK_ANALYSIS_PATH_MAP,
            )

        workflow.add_edge("Portfolio Manager", END)

        return workflow
