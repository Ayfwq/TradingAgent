"""交易员：将研究经理的投资计划转化为具体的交易提案。"""

from __future__ import annotations

import functools
import logging

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import TraderProposal, render_trader_proposal
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


def create_trader(llm):
    structured_llm = bind_structured(llm, TraderProposal, "Trader")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = get_instrument_context_from_state(state)
        investment_plan = state["investment_plan"]

        logger.debug("交易员调用：代码=%s", state.get("company_of_interest"))

        messages = [
            {
                "role": "system",
                "content": (
                    "你是一名分析市场数据并做出投资决策的交易 Agent。"
                    "请根据分析明确建议买入、卖出或持有。"
                    "你的推理必须以分析师报告和研究计划为依据。"
                    + NO_EXTERNAL_TOOLS
                    + get_language_instruction()
                ),
            },
            {
                "role": "user",
                "content": (
                    f"以下是分析师团队综合分析后为 {company_name} 制定的投资计划。{instrument_context}"
                    f"该计划综合了当前技术面趋势、宏观经济指标和社交媒体情绪。请以此计划为基础评估下一步交易决策。"
                    f"\n\n拟定投资计划：{investment_plan}\n\n"
                    f"请利用这些洞察做出有依据且具有策略性的决定。"
                ),
            },
        ]

        try:
            trader_plan = invoke_structured_or_freetext(
                structured_llm,
                llm,
                messages,
                render_trader_proposal,
                "Trader",
            )
            logger.debug("交易员 LLM 调用完成：输出长度=%d", len(trader_plan))
        except Exception as exc:
            logger.exception("交易员 LLM 调用失败：%s", exc)
            raise

        logger.debug("交易员节点返回：输出长度=%d", len(trader_plan))

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
