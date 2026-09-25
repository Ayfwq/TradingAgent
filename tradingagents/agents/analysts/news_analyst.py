import logging
from datetime import datetime, timedelta

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


def create_news_analyst(llm, max_tool_rounds: int = 3):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        asset_type = state.get("asset_type", "stock")
        asset_label = "company" if asset_type == "stock" else "asset"
        instrument_context = get_instrument_context_from_state(state)
        logger.debug("新闻分析师节点调用：代码=%s 日期=%s", state.get("company_of_interest"), state.get("trade_date"))

        # 公司新闻属于本分析面的必要输入，不应依赖模型是否主动选择工具。
        # 在调用 LLM 前固定预取一次，并将真实结果/不可用原因放进提示词。
        news_start_date = (
            datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=7)
        ).strftime("%Y-%m-%d")
        try:
            ticker_news_block = get_news.func(
                state["company_of_interest"], news_start_date, current_date
            )
        except Exception as exc:
            logger.exception("新闻分析师预取 %s 新闻失败：%s", state.get("company_of_interest"), exc)
            ticker_news_block = (
                f"NEWS_UNAVAILABLE：无法获取 {state.get('company_of_interest')} 的新闻"
                f"（{type(exc).__name__}）。请说明新闻不可用，不要编造内容。"
            )

        tools = [
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
            f"说明与交易和宏观经济相关的当前世界状态。目标{asset_label}的新闻已由系统通过"
            f"`get_news(ticker, start_date, end_date)` 自动预取；其他可用工具包括："
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
        system_message += (
            f"\n\n## 已自动获取的目标标的新闻（{news_start_date} 至 {current_date}）\n"
            "此区块由系统在模型分析前强制预取，来源名称由抓取工具标注。优先基于实际标题和摘要分析；"
            "若内容为 `NEWS_UNAVAILABLE`，请如实说明各数据源失败/无新闻，不得臆测新闻。\n\n"
            f"{ticker_news_block}"
        )

        # When the graph reaches its tool-call cap, it routes back here once. The
        # final pass deliberately has no bound tools so the analyst must summarize
        # what it already retrieved instead of being cleared with an empty report.
        channel = state.get("news_messages", state.get("messages", []))
        tool_rounds = sum(
            1 for message in channel if getattr(message, "tool_calls", None)
        )
        force_final = tool_rounds >= max_tool_rounds
        finalization_instruction = (
            "工具调用轮次已达到上限。现在必须立即根据已有工具返回内容完成新闻分析，"
            "不要再调用工具；资料不足时明确列出缺失信息和来源限制，不得编造新闻或数据。"
        ) if force_final else ""

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
                    "你可以使用以下工具：{tool_names}。{finalization_instruction}"
                    "今天是 {current_date}；所有分析和工具调用日期范围都以它作为当前日期。{instrument_context}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(finalization_instruction=finalization_instruction)
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        try:
            chain = prompt | (llm if force_final else llm.bind_tools(tools))
            result = chain.invoke(channel)
            logger.debug("新闻分析师 LLM 调用完成（%d 个工具调用）", len(getattr(result, "tool_calls", []) or []))
        except Exception as exc:
            logger.exception("新闻分析师 LLM 调用失败：%s", exc)
            raise

        report = ""
        if not getattr(result, "tool_calls", None):
            content = result.content
            if isinstance(content, str):
                report = content.strip()
            elif isinstance(content, list):
                report = "\n".join(
                    str(block.get("text", ""))
                    for block in content
                    if isinstance(block, dict) and block.get("text")
                ).strip()

        if not report and not getattr(result, "tool_calls", None):
            logger.warning(
                "新闻分析师没有返回最终正文；保留空报告供报告界面明确标记为未生成"
            )

        logger.debug("新闻分析师完成：报告长度=%d 字符", len(report or ""))

        return {
            "news_messages": [result],
            "news_report": report,
        }

    return news_analyst_node
