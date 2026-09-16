"""回归测试：带工具轮次的并行分析师必须到达 END。

通过的冒烟测试（verify_parallel_graph.py）使用从不调用工具的伪 LLM，
因此分析师不会进入工具循环，扇入连接节点始终位于同一深度层。真实 LLM
会执行可变轮数的工具调用，因此其清理节点会落在不同深度层；这曾导致图崩溃：

  InvalidUpdateError：键 'investment_debate_state' 每步只能接收一个值。

该问题由分析师屏障修复：扇入节点吸收跨层清理信号，只有在每个分析师都完成
（报告存在，或其清理节点已标记完成）后才路由到辩论阶段。

本脚本让每个分析师在报告前调用一次真实工具（通过 akshare 获取
get_stock_data——线程锁定且速度快），复现多层扇入，并断言完整流水线能够
到达投资组合经理。

用法：uv run --quiet python scripts/repro_tool_rounds_graph.py
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
    """伪 LLM：在分析师轮次的第一次调用中（messages 只有一条启动 Human 消息）
    调用 get_stock_data，迫使分析师经历一轮工具调用；之后的每次调用都直接报告。
    情绪分析师的提示词从一开始就带有系统消息（至少 2 条消息），因此会立即报告，
    复现真实场景中部分分析师进入工具循环、部分不进入的混合情况（清理节点位于
    不同深度层）。"""

    @property
    def _llm_type(self) -> str:
        return "fake-tool"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        # 只有分析师通道中唯一的 HumanMessage 种子（content == ticker）才调用工具。
        # 提示词字符串阶段（交易员/风险管理/投资组合经理）以一条很长的
        # HumanMessage 到达，必须直接报告，否则会对未绑定的工具发出 get_stock_data 调用。
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
        # values 模式：每个块都携带完整状态，因此最后一个块包含流水线生成的全部内容。
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
        print(f"报告是否完整：{reports}")
        print(f"辩论轮数：{debate.get('count', 0)} | "
              f"风险辩论轮数：{risk.get('count', 0)}")
        print(f"最终交易决策是否存在：{bool(decision.strip())}")
        print("带工具轮次的并行图：", "通过" if ok else "失败")
        return 0 if ok else 1
    finally:
        tg.create_llm_client = orig_create


if __name__ == "__main__":
    sys.exit(main())
