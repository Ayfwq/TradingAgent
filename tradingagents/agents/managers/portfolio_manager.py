"""投资组合经理：将风险分析师辩论综合为最终决策。

使用 LangChain 的 ``with_structured_output``，让 LLM 在单次调用中直接生成类型化的
``PortfolioDecision``。结果会重新渲染为 Markdown 并写入 ``final_trade_decision``，
因此记忆日志、Web 展示和已保存报告仍保持相同结构。如果服务商不提供结构化输出，
则优雅回退到自由文本生成。
"""

from __future__ import annotations

import logging

from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)

logger = logging.getLogger(__name__)


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]

        logger.debug("投资组合经理调用：代码=%s", state.get("company_of_interest"))

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- 过往决策与结果中的经验：\n{past_context}\n"
            if past_context
            else ""
        )

        prompt = f"""作为投资组合经理，请综合风险分析师的辩论并给出最终交易决策。

{instrument_context}

---

**评级尺度**（必须且只能选择一个）：
- **Buy**：强烈认同，应建仓或加仓
- **Overweight**：前景有利，逐步增加敞口
- **Hold**：维持当前仓位，无需操作
- **Underweight**：减少敞口，部分止盈
- **Sell**：退出持仓或避免入场

**上下文：**
- 研究经理的投资计划：**{research_plan}**
- 交易员的交易提案：**{trader_plan}**
{lessons_line}
**风险分析师辩论历史：**
{history}

---

请明确决策，并让每个结论都有分析师提供的具体证据支撑。

{NO_EXTERNAL_TOOLS}{get_language_instruction()}"""

        try:
            final_trade_decision = invoke_structured_or_freetext(
                structured_llm,
                llm,
                prompt,
                render_pm_decision,
                "Portfolio Manager",
            )
            logger.debug("投资组合经理 LLM 调用完成：输出长度=%d", len(final_trade_decision))
        except Exception as exc:
            logger.exception("投资组合经理 LLM 调用失败：%s", exc)
            raise

        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        logger.debug("投资组合经理节点返回：输出长度=%d", len(final_trade_decision))

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
        }

    return portfolio_manager_node
