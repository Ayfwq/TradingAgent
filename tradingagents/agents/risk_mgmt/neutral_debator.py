import logging

from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)

logger = logging.getLogger(__name__)


def create_neutral_debator(llm):
    def neutral_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        neutral_history = risk_debate_state.get("neutral_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_conservative_response = risk_debate_state.get("current_conservative_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        instrument_context = get_instrument_context_from_state(state)

        trader_decision = state["trader_investment_plan"]

        logger.debug("中性风险分析师调用：代码=%s 辩论轮次=%d", state.get("company_of_interest"), state.get("risk_debate_state", {}).get("count", 0))

        prompt = f"""作为中性风险分析师，你的职责是提供平衡视角，权衡交易员决定或计划的潜在收益与风险。你应采用全面方法，在评估利弊的同时考虑更广泛的市场趋势、潜在经济变化和分散化策略。以下是交易员的决定：

{trader_decision}

你的任务是挑战激进和保守分析师，指出各自视角可能过度乐观或过度谨慎的地方。请利用以下数据源的洞察，支持对交易员决定进行适度、可持续的调整：

{instrument_context}
市场研究报告：{market_research_report}
社交媒体情绪报告：{sentiment_report}
最新全球新闻报告：{news_report}
公司基本面报告：{fundamentals_report}
当前对话历史：{history}。激进分析师上一轮回复：{current_aggressive_response}。保守分析师上一轮回复：{current_conservative_response}。如果其他视角尚未回复，请基于现有数据提出自己的论点。

请积极批判性分析双方，回应激进和保守论点中的弱点，倡导更加平衡的方法。挑战双方每一个观点，说明适度风险策略为何可能兼顾两者优势，在保留增长潜力的同时防范极端波动。重点是辩论而不是简单展示数据，说明平衡视角为何能带来最可靠的结果。请以对话方式输出，不要使用特殊格式。""" + get_language_instruction()

        try:
            response = llm.invoke(prompt)
            logger.debug("中性风险分析师 LLM 调用完成（%d 字符）", len(response.content or ""))
        except Exception as exc:
            logger.exception("中性风险分析师 LLM 调用失败：%s", exc)
            raise

        argument = f"中性风险分析师：{response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": neutral_history + "\n" + argument,
            "latest_speaker": "Neutral",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": argument,
            "count": risk_debate_state["count"] + 1,
        }

        logger.debug("中性风险分析师完成：论点长度=%d 字符", len(argument or ""))

        return {"risk_debate_state": new_risk_debate_state}

    return neutral_node
