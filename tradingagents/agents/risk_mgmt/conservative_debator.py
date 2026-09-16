import logging

from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)

logger = logging.getLogger(__name__)


def create_conservative_debator(llm):
    def conservative_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        conservative_history = risk_debate_state.get("conservative_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        instrument_context = get_instrument_context_from_state(state)

        trader_decision = state["trader_investment_plan"]

        logger.debug("保守风险分析师调用：代码=%s 辩论轮次=%d", state.get("company_of_interest"), state.get("risk_debate_state", {}).get("count", 0))

        prompt = f"""作为保守风险分析师，你的首要目标是保护资产、降低波动并确保稳定可靠的增长。你应优先考虑稳定性、安全性和风险缓释，仔细评估潜在损失、经济下行和市场波动。评估交易员的决定或计划时，要批判性检查高风险因素，指出该决定可能使公司暴露于不必要风险的地方，以及更谨慎的替代方案如何保障长期收益。以下是交易员的决定：

{trader_decision}

你的任务是积极反驳激进和中性分析师的论点，指出他们的观点可能忽略了哪些潜在威胁，或没有优先考虑可持续性。请直接回应他们的观点，并利用以下数据源，为调整交易员决定、采用低风险方法建立有说服力的论证：

{instrument_context}
市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新全球新闻报告：{news_report}
公司基本面报告：{fundamentals_report}
当前对话历史：{history}。激进分析师上一轮回复：{current_aggressive_response}。中性分析师上一轮回复：{current_neutral_response}。如果其他视角尚未回复，请基于现有数据提出自己的论点。

请质疑他们的乐观态度，强调其可能忽视的潜在下行风险。逐一回应他们的反驳点，说明保守立场为何最终是保护公司资产最安全的路径。重点是辩论和批评其论点，展示低风险策略相较于其他方法的优势。请以对话方式输出，不要使用特殊格式。""" + get_language_instruction()

        try:
            response = llm.invoke(prompt)
            logger.debug("保守风险分析师 LLM 调用完成（%d 字符）", len(response.content or ""))
        except Exception as exc:
            logger.exception("保守风险分析师 LLM 调用失败：%s", exc)
            raise

        argument = f"保守风险分析师：{response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": conservative_history + "\n" + argument,
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Conservative",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": argument,
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        logger.debug("保守风险分析师完成：论点长度=%d 字符", len(argument or ""))

        return {"risk_debate_state": new_risk_debate_state}

    return conservative_node
