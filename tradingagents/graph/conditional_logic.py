# TradingAgents/graph/conditional_logic.py

import logging

from tradingagents.agents.utils.agent_states import AgentState

logger = logging.getLogger(__name__)


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(
        self,
        max_debate_rounds=1,
        max_risk_discuss_rounds=1,
        max_tool_rounds: int = 3,
    ):
        """Initialize with configuration parameters.

        ``max_tool_rounds`` caps how many LLM->tools->LLM iterations each
        tool-calling analyst may perform before being forced to emit its
        report. A chatty model can otherwise loop on tool calls indefinitely
        (bounded only by the whole-graph recursion limit), burning tokens on
        repeated fetches of data it already has.
        """
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds
        self.max_tool_rounds = max_tool_rounds

    def _tool_rounds(self, state: AgentState, messages_key: str) -> int:
        """Count completed tool-call rounds in the current analyst segment.

        Each analyst owns a private message channel (cleared by its own clear
        node), so the channel only holds this analyst's turns: one AIMessage
        with tool_calls per round.
        """
        return sum(
            1 for m in state.get(messages_key, []) if getattr(m, "tool_calls", None)
        )

    def _cap_reached(self, state: AgentState, messages_key: str, tools_node: str, clear_node: str) -> str:
        """Route the analyst: tools when it asked for tools and is under the
        round cap, otherwise clear (report time)."""
        last_message = state.get(messages_key, [])[-1] if state.get(messages_key) else None
        if (
            last_message is not None
            and getattr(last_message, "tool_calls", None)
            and self._tool_rounds(state, messages_key) < self.max_tool_rounds
        ):
            logger.debug(
                "Analyst %s requesting more tools (round %d/%d) -> %s",
                messages_key, self._tool_rounds(state, messages_key),
                self.max_tool_rounds, tools_node,
            )
            return tools_node
        logger.debug("Analyst %s finished tool rounds -> %s", messages_key, clear_node)
        return clear_node

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue."""
        return self._cap_reached(state, "market_messages", "tools_market", "Msg Clear Market")

    def should_continue_social(self, state: AgentState):
        """Determine if sentiment-analyst tool round should continue.

        Method name keeps the legacy ``social`` suffix to match the
        ``AnalystType.SOCIAL = "social"`` wire value (saved-config
        back-compat); the returned ``clear_node`` label uses the v0.2.5
        rename so it matches the node registered by the execution plan.
        """
        return self._cap_reached(state, "sentiment_messages", "tools_social", "Msg Clear Sentiment")

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        return self._cap_reached(state, "news_messages", "tools_news", "Msg Clear News")

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        return self._cap_reached(state, "fundamentals_messages", "tools_fundamentals", "Msg Clear Fundamentals")

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue."""

        if (
            state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds
        ):  # 3 rounds of back-and-forth between 2 agents
            logger.debug(
                "Debate complete after %d responses (max=%d) -> Research Manager",
                state["investment_debate_state"]["count"], 2 * self.max_debate_rounds,
            )
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            logger.debug(
                "Bull spoke (round %d/%d) -> Bear Researcher",
                state["investment_debate_state"]["count"], 2 * self.max_debate_rounds,
            )
            return "Bear Researcher"
        logger.debug(
            "Bear spoke (round %d/%d) -> Bull Researcher",
            state["investment_debate_state"]["count"], 2 * self.max_debate_rounds,
        )
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        if (
            state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds
        ):  # 3 rounds of back-and-forth between 3 agents
            logger.debug(
                "Risk debate complete after %d responses (max=%d) -> Portfolio Manager",
                state["risk_debate_state"]["count"], 3 * self.max_risk_discuss_rounds,
            )
            return "Portfolio Manager"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            logger.debug(
                "Aggressive spoke (round %d/%d) -> Conservative Analyst",
                state["risk_debate_state"]["count"], 3 * self.max_risk_discuss_rounds,
            )
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            logger.debug(
                "Conservative spoke (round %d/%d) -> Neutral Analyst",
                state["risk_debate_state"]["count"], 3 * self.max_risk_discuss_rounds,
            )
            return "Neutral Analyst"
        logger.debug(
            "Neutral spoke (round %d/%d) -> Aggressive Analyst",
            state["risk_debate_state"]["count"], 3 * self.max_risk_discuss_rounds,
        )
        return "Aggressive Analyst"
