"""使用伪 LLM 的图级冒烟测试：验证并行分析师扇出能够编译，且完整流水线
（分析师 -> 辩论 -> 研究经理 -> 交易员 -> 风险管理 -> 投资组合经理）能够
在不访问真实 LLM 网关的情况下运行到 END。

用法：uv run --quiet python scripts/verify_parallel_graph.py
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
    "FAKE_ANALYSIS：这是用于验证并行图连接的确定性伪报告。"
    "FINAL TRANSACTION PROPOSAL: **HOLD**"
)


class FakeLLM(BaseChatModel):
    """最小聊天模型：从不调用工具，始终返回 FAKE_TEXT。"""

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=FAKE_TEXT))]
        )

    def bind_tools(self, tools, **kwargs):
        # 分析师会绑定工具；忽略工具的伪模型用于测试不调用工具的路径
        #（第一轮就生成报告）。
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
            print(f"{name}：{'正常' if filled else '为空'}")
            ok = ok and filled

        decision = final_state.get("final_trade_decision", "")
        print(f"最终交易决策：{'正常' if decision.strip() else '为空'}")
        ok = ok and bool(decision.strip())
        print(f"signal: {signal}")

        debate = final_state.get("investment_debate_state", {})
        print(
            "辩论历史长度：",
            len(debate.get("history", "")),
            "| 看多：",
            len(debate.get("bull_history", "")),
            "| 看空：",
            len(debate.get("bear_history", "")),
        )
        ok = ok and debate.get("count", 0) >= 2

        risk = final_state.get("risk_debate_state", {})
        print(
            "风险历史长度：",
            len(risk.get("history", "")),
            "| 轮数：",
            risk.get("count", 0),
        )
        ok = ok and risk.get("count", 0) >= 3

        print("\n并行图冒烟测试：", "通过" if ok else "失败")
        return 0 if ok else 1
    finally:
        tg.create_llm_client = orig_create


if __name__ == "__main__":
    sys.exit(main())
