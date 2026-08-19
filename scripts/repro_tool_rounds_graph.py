"""Regression test: parallel analysts WITH tool rounds must reach END.

The passing smoke test (verify_parallel_graph.py) uses a fake LLM that never
calls tools, so analysts never enter the tools loop and the fan-in join stays
in one depth layer. With real LLMs analysts call tools for a variable number
of rounds, so their clear nodes land in different layers — which used to
crash the graph:

  InvalidUpdateError: At key 'investment_debate_state': Can receive only one
  value per step.

Fixed by the Analyst Barrier: a fan-in node that absorbs cross-layer clear
signals and only routes into the debate once every analyst has finished
(report present, or its clear node marked it done).

This script makes each analyst call one real tool (get_stock_data via
akshare — thread-locked and fast) before reporting, reproducing the
multi-layer fan-in, and asserts the full pipeline reaches the Portfolio
Manager.

Usage:  uv run --quiet python scripts/repro_tool_rounds_graph.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

FAKE_TEXT = (
    "FAKE_ANALYSIS: deterministic stub. FINAL TRANSACTION PROPOSAL: **HOLD**"
)

TOOL_CALL_ID = "call_fake_1"


class FakeToolLLM(BaseChatModel):
    """Fake LLM: on the FIRST call of an analyst turn (messages is just the
    single startup Human message) it calls get_stock_data, forcing the
    analyst through one tool round; on every later call it reports.
    Sentiment's prompt carries a system message (2+ messages from the start),
    so it reports immediately — reproducing the real-world mix where some
    analysts tool-loop and others do not (clear nodes land in different
    depth layers)."""

    @property
    def _llm_type(self) -> str:
        return "fake-tool"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        # Tool-call only for the lone HumanMessage analyst-channel seed
        # (content == the ticker). Prompt-string stages (Trader/RM/PM) arrive
        # as a single long HumanMessage and must report directly — otherwise
        # they'd emit a get_stock_data call against tools they don't have.
        from langchain_core.messages import HumanMessage
        if (
            len(messages) == 1
            and isinstance(messages[0], HumanMessage)
            and messages[0].content == "600519.SS"
        ):
            return ChatResult(
                generations=[ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[{
                            "name": "get_stock_data",
                            "args": {"symbol": "600519.SS",
                                     "start_date": "2026-07-01",
                                     "end_date": "2026-08-17"},
                            "id": TOOL_CALL_ID,
                        }],
                    ))]
            )
        return ChatResult(
            generations=[ChatGeneration(
                message=AIMessage(content=FAKE_TEXT))]
        )

    def bind_tools(self, tools, **kwargs):
        return self


class FakeClient:
    def __init__(self, llm):
        self._llm = llm

    def get_llm(self):
        return self._llm


def main() -> int:
    import tradingagents.graph.trading_graph as tg

    fake = FakeToolLLM()
    orig_create = tg.create_llm_client
    tg.create_llm_client = lambda provider, model, base_url=None, **kw: FakeClient(fake)

    tmp = tempfile.mkdtemp(prefix="ta_repro_")
    try:
        graph = tg.TradingAgentsGraph(
            config={
                "results_dir": os.path.join(tmp, "results"),
                "data_cache_dir": os.path.join(tmp, "cache"),
                "memory_log_path": os.path.join(tmp, "memory.md"),
                "max_debate_rounds": 1,
                "max_risk_discuss_rounds": 1,
                "max_tool_rounds": 3,
                "checkpoint_enabled": False,
                "llm_provider": "deepseek",
                "deep_think_llm": "deepseek-v4-flash",
                "quick_think_llm": "deepseek-v4-flash",
                "output_language": "English",
            },
            debug=False,
        )
        # values mode: every chunk carries the FULL state, so the final chunk
        # has everything the pipeline produced.
        final_state = graph.graph.invoke(
            graph.propagator.create_initial_state("600519.SS", "2026-08-17"),
            **graph.propagator.get_graph_args(),
        )

        reports = [
            bool(final_state.get(k))
            for k in ("market_report", "sentiment_report", "news_report",
                      "fundamentals_report")
        ]
        debate = final_state.get("investment_debate_state", {})
        risk = final_state.get("risk_debate_state", {})
        decision = final_state.get("final_trade_decision", "")

        ok = all(reports) and debate.get("count", 0) >= 2 \
            and risk.get("count", 0) >= 3 and bool(decision.strip())
        print(f"reports filled: {reports}")
        print(f"debate count: {debate.get('count', 0)} | "
              f"risk count: {risk.get('count', 0)}")
        print(f"final_trade_decision: {bool(decision.strip())}")
        print("TOOL-ROUNDS PARALLEL GRAPH:", "PASSED" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        tg.create_llm_client = orig_create


if __name__ == "__main__":
    sys.exit(main())
