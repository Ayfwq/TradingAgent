"""Graph-level smoke test with a fake LLM: verifies the parallel analyst
fan-out compiles and the whole pipeline (analysts -> debate -> RM -> trader
-> risk -> PM) runs to END without touching the real LLM gateway.

Usage:  uv run --quiet python scripts/verify_parallel_graph.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from tradingagents.graph.trading_graph import TradingAgentsGraph

FAKE_TEXT = (
    "FAKE_ANALYSIS: This is a deterministic stub report used to verify the "
    "parallel graph wiring. FINAL TRANSACTION PROPOSAL: **HOLD**"
)


class FakeLLM(BaseChatModel):
    """Minimal chat model: never calls tools, always returns FAKE_TEXT."""

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=FAKE_TEXT))]
        )

    def bind_tools(self, tools, **kwargs):
        # Analysts bind tools; a fake that ignores them exercises the
        # no-tool-call path (report emitted on first turn).
        return self


class FakeClient:
    def __init__(self, llm):
        self._llm = llm

    def get_llm(self):
        return self._llm


def main() -> int:
    import tradingagents.graph.trading_graph as tg

    fake = FakeLLM()
    orig_create = tg.create_llm_client
    tg.create_llm_client = lambda provider, model, base_url=None, **kw: FakeClient(fake)

    tmp = tempfile.mkdtemp(prefix="ta_graph_smoke_")
    try:
        graph = TradingAgentsGraph(
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
        final_state, signal = graph.propagate("600519.SS", "2026-08-17")

        reports = {
            "market_report": final_state.get("market_report", ""),
            "sentiment_report": final_state.get("sentiment_report", ""),
            "news_report": final_state.get("news_report", ""),
            "fundamentals_report": final_state.get("fundamentals_report", ""),
        }
        ok = True
        for name, report in reports.items():
            filled = bool(report and report.strip())
            print(f"{name}: {'OK' if filled else 'EMPTY'}")
            ok = ok and filled

        decision = final_state.get("final_trade_decision", "")
        print(f"final_trade_decision: {'OK' if decision.strip() else 'EMPTY'}")
        ok = ok and bool(decision.strip())
        print(f"signal: {signal}")

        debate = final_state.get("investment_debate_state", {})
        print(
            "debate history length:",
            len(debate.get("history", "")),
            "| bull:",
            len(debate.get("bull_history", "")),
            "| bear:",
            len(debate.get("bear_history", "")),
        )
        ok = ok and debate.get("count", 0) >= 2

        risk = final_state.get("risk_debate_state", {})
        print(
            "risk history length:",
            len(risk.get("history", "")),
            "| count:",
            risk.get("count", 0),
        )
        ok = ok and risk.get("count", 0) >= 3

        print("\nPARALLEL GRAPH SMOKE:", "PASSED" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        tg.create_llm_client = orig_create


if __name__ == "__main__":
    sys.exit(main())
