import logging

from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)

logger = logging.getLogger(__name__)


def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        instrument_context = get_instrument_context_from_state(state)
        asset_type = state.get("asset_type", "stock")
        target_label = "股票" if asset_type == "stock" else "资产"
        fundamentals_label = (
            "公司基本面报告"
            if asset_type == "stock"
            else "资产基本面报告（加密资产可能没有该报告）"
        )

        logger.debug("看空研究员调用：代码=%s 辩论轮次=%d", state.get("company_of_interest"), state.get("investment_debate_state", {}).get("count", 0))

        prompt = f"""你是一名反对投资该{target_label}的看空分析师。你的目标是提出经过充分推理的论点，强调风险、挑战和负面指标。请利用提供的研究和数据突出潜在下行空间，并有效反驳看多观点。

需要重点关注：

- 风险与挑战：突出市场饱和、财务不稳定或可能阻碍股票表现的宏观经济威胁等因素。
- 竞争劣势：强调市场定位较弱、创新能力下降或竞争对手威胁等脆弱点。
- 负面指标：使用财务数据、市场趋势或近期不利新闻中的证据支持你的观点。
- 看多反驳点：用具体数据和严谨推理批判看多论点，揭示其弱点或过度乐观的假设。
- 互动辩论：以对话方式陈述观点，直接回应看多分析师并有效辩论，而不是简单罗列事实。

可用资料：

{instrument_context}
市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新全球新闻：{news_report}
{fundamentals_label}：{fundamentals_report}
辩论对话历史：{history}
看多方上一轮论点：{current_response}
请利用这些信息提出有说服力的看空论点，回应看多方主张，并参与动态辩论，展现投资该{target_label}的风险和弱点。
""" + get_language_instruction()

        try:
            response = llm.invoke(prompt)
            logger.debug("看空研究员 LLM 调用完成（%d 字符）", len(response.content or ""))
        except Exception as exc:
            logger.exception("看空研究员 LLM 调用失败：%s", exc)
            raise

        argument = f"看空分析师：{response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        logger.debug("看空研究员完成：论点长度=%d 字符", len(argument or ""))

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
