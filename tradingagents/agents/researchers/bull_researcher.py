import logging

from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)

logger = logging.getLogger(__name__)


def create_bull_researcher(llm):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

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

        logger.debug("看多研究员调用：代码=%s 辩论轮次=%d", state.get("company_of_interest"), state.get("investment_debate_state", {}).get("count", 0))

        prompt = f"""你是一名主张投资该{target_label}的看多分析师。你的任务是构建有力且基于证据的论点，强调增长潜力、竞争优势和积极的市场指标。请利用提供的研究和数据有效回应疑虑、反驳看空观点。

需要重点关注：
- 增长潜力：突出公司的市场机会、收入预测和规模化能力。
- 竞争优势：强调独特产品、强势品牌或主导性市场地位等因素。
- 积极指标：用财务健康度、行业趋势和近期利好新闻作为证据。
- 看空反驳点：使用具体数据和严谨推理批判看空论点，充分回应疑虑并说明看多观点为何更有说服力。
- 互动辩论：以对话方式陈述观点，直接回应看空分析师的论点并有效辩论，不要只罗列数据。

可用资料：
{instrument_context}
市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新全球新闻：{news_report}
{fundamentals_label}：{fundamentals_report}
辩论对话历史：{history}
看空方上一轮论点：{current_response}
请利用这些信息提出有说服力的看多论点，回应看空方疑虑，并参与动态辩论，展现看多立场的优势。
""" + get_language_instruction()

        try:
            response = llm.invoke(prompt)
            logger.debug("看多研究员 LLM 调用完成（%d 字符）", len(response.content or ""))
        except Exception as exc:
            logger.exception("看多研究员 LLM 调用失败：%s", exc)
            raise

        argument = f"看多分析师：{response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        logger.debug("看多研究员完成：论点长度=%d 字符", len(argument or ""))

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
