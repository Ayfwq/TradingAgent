import logging

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_global_news,
    get_insider_transactions,
    get_instrument_context_from_state,
    get_language_instruction,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
)

logger = logging.getLogger(__name__)


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = get_instrument_context_from_state(state)
        logger.debug("新闻分析师节点调用：代码=%s 日期=%s", state.get("company_of_interest"), state.get("trade_date"))

        tools = [
            get_news,
            get_global_news,
            get_macro_indicators,
            get_prediction_markets,
        ]
        if asset_type == "stock":
            tools.append(get_insider_transactions)

        insider_instruction = ""
        if asset_type == "stock":
            insider_instruction = (
                "当内幕交易或董事、监事、高级管理人员的交易可能影响投资逻辑时，"
                "请使用 `get_insider_transactions(ticker)`；对于 A 股，该工具代表董监高交易。"
            )

        system_message = (
            f"你是一名新闻研究员，负责分析过去一周的最新新闻和趋势。请撰写全面报告，"
            f"说明与交易和宏观经济相关的当前世界状态。可用工具包括："
            f"`get_news(ticker, start_date, end_date)`，按代码获取{asset_label}相关新闻；"
            "`get_global_news(curr_date, look_back_days, limit)`，获取更广泛的宏观新闻；"
            "`get_macro_indicators(indicator, curr_date, look_back_days)`，用 FRED 的实际数据支撑宏观分析"
            "（例如 'cpi'、'core_pce'、'unemployment'、'fed_funds_rate'、'10y_treasury'、'yield_curve'）；"
            "以及 `get_prediction_markets(topic, limit)`，获取市场对未来事件的实时隐含概率"
            "（例如“美联储降息”“2026 年衰退”以及地缘政治或行业事件）。"
            "请用有证据支持的具体、可执行洞察帮助交易员做出决策。"
            + insider_instruction
            + """ 请在报告末尾追加 Markdown 表格，整理关键要点，使报告结构清晰、易于阅读。"""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一名乐于协作的 AI 助手，正在与其他助手共同工作。"
                    "请使用提供的工具推进问题的解答。"
                    "如果无法完全回答也没关系，其他拥有不同工具的助手会从你停下的地方继续。"
                    "请尽可能推进任务。"
                    "如果你或其他助手已经给出 FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** 或完成交付，"
                    "请在回复前加上 FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**，以便团队停止继续调用。"
                    "你可以使用以下工具：{tool_names}。"
                    "今天是 {current_date}；所有分析和工具调用日期范围都以它作为当前日期。{instrument_context}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        # 分析师并行运行时使用独立通道；直接调用或旧 checkpoint 使用共享
        # ``messages`` 作为兼容回退。
        channel = state.get("news_messages", state.get("messages", []))
        try:
            result = chain.invoke(channel)
            logger.debug("新闻分析师 LLM 调用完成（%d 个工具调用）", len(getattr(result, "tool_calls", []) or []))
        except Exception as exc:
            logger.exception("新闻分析师 LLM 调用失败：%s", exc)
            raise

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        logger.debug("新闻分析师完成：报告长度=%d 字符", len(report or ""))

        return {
            "news_messages": [result],
            "news_report": report,
        }

    return news_analyst_node
