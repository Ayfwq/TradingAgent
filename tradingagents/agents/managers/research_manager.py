"""研究经理：将看多/看空辩论转化为交易员可执行的结构化投资计划。"""

from __future__ import annotations

import logging

from tradingagents.agents.schemas import ResearchPlan, render_research_plan
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


def create_research_manager(llm):
    structured_llm = bind_structured(llm, ResearchPlan, "Research Manager")

    def research_manager_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)
        history = state["investment_debate_state"].get("history", "")

        investment_debate_state = state["investment_debate_state"]
        logger.debug("研究经理调用：代码=%s", state.get("company_of_interest"))

        prompt = f"""作为研究经理和辩论主持人，你需要批判性评估本轮辩论，并为交易员给出清晰、可执行的投资计划。

{instrument_context}

---

**评级尺度**（必须且只能选择一个）：
- **Buy**：强烈认同看多逻辑，建议建仓或增加仓位
- **Overweight**：观点积极，建议逐步增加敞口
- **Hold**：观点均衡，建议维持当前仓位
- **Underweight**：观点谨慎，建议减少敞口
- **Sell**：强烈认同看空逻辑，建议退出或避免持仓

当辩论中最有力的论据支持明确方向时，必须给出明确立场；只有双方证据确实均衡时才使用 Hold。

---

**辩论历史：**
{history}

{NO_EXTERNAL_TOOLS}""" + get_language_instruction()

        try:
            investment_plan = invoke_structured_or_freetext(
                structured_llm,
                llm,
                prompt,
                render_research_plan,
                "Research Manager",
            )
            logger.debug("研究经理 LLM 调用完成：输出长度=%d", len(investment_plan))
        except Exception as exc:
            logger.exception("研究经理 LLM 调用失败：%s", exc)
            raise

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }

        logger.debug("研究经理节点返回：输出长度=%d", len(investment_plan))

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }

    return research_manager_node
