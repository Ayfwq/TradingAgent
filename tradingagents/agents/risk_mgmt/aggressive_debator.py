import logging

from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)

logger = logging.getLogger(__name__)


def create_aggressive_debator(llm):
    def aggressive_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        aggressive_history = risk_debate_state.get("aggressive_history", "")

        current_conservative_response = risk_debate_state.get("current_conservative_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        instrument_context = get_instrument_context_from_state(state)

        trader_decision = state["trader_investment_plan"]

        logger.debug("激进风险分析师调用：代码=%s 辩论轮次=%d", state.get("company_of_interest"), state.get("risk_debate_state", {}).get("count", 0))

        prompt = f"""作为激进风险分析师，你需要积极支持高收益、高风险机会，强调大胆策略和竞争优势。评估交易员的决定或计划时，应重点关注潜在上行空间、增长潜力和创新收益，即使它们伴随更高风险。请使用提供的市场数据和情绪分析加强论点并挑战相反观点。具体来说，要直接回应保守和中性分析师提出的每一点，用数据驱动的反驳和有说服力的推理进行回应。指出他们的谨慎可能错过哪些关键机会，或哪些假设过于保守。以下是交易员的决定：

{trader_decision}

你的任务是质疑并批评保守和中性立场，为交易员的决定提出有说服力的支持，说明高收益视角为何是最好的前进路径。请将以下来源的洞察融入论点：

{instrument_context}
市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新全球新闻报告：{news_report}
公司基本面报告：{fundamentals_report}
当前对话历史：{history}。保守分析师上一轮论点：{current_conservative_response}。中性分析师上一轮论点：{current_neutral_response}。如果其他视角尚未回复，请基于现有数据提出自己的论点。

请积极回应提出的具体疑虑，反驳其逻辑弱点，并说明承担风险为何有助于超越市场平均表现。重点是辩论和说服，而不是单纯展示数据。挑战每个反驳点，强调高风险方法为何更优。请以对话方式输出，不要使用特殊格式。""" + get_language_instruction()

        try:
            response = llm.invoke(prompt)
            logger.debug("激进风险分析师 LLM 调用完成（%d 字符）", len(response.content or ""))
        except Exception as exc:
            logger.exception("激进风险分析师 LLM 调用失败：%s", exc)
            raise

        argument = f"激进风险分析师：{response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": aggressive_history + "\n" + argument,
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Aggressive",
            "current_aggressive_response": argument,
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        logger.debug("激进风险分析师完成：论点长度=%d 字符", len(argument or ""))

        return {"risk_debate_state": new_risk_debate_state}

    return aggressive_node
