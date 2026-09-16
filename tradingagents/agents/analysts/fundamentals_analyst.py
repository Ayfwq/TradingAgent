import logging

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_balance_sheet,
    get_cashflow,
    get_earnings_forecast,
    get_fundamentals,
    get_income_statement,
    get_instrument_context_from_state,
    get_language_instruction,
    is_ashare_ticker,
)

logger = logging.getLogger(__name__)


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        is_ashare = is_ashare_ticker(ticker)
        instrument_context = get_instrument_context_from_state(state)
        logger.debug("基本面分析师节点调用：代码=%s 日期=%s", state.get("company_of_interest"), state.get("trade_date"))

        tools = [
            get_fundamentals,
            get_balance_sheet,
            get_cashflow,
            get_income_statement,
        ]
        if is_ashare:
            tools.append(get_earnings_forecast)

        ashare_instruction = ""
        if is_ashare:
            ashare_instruction = (
                "这是 A 股：调用 `get_earnings_forecast(ticker, curr_date)`，"
                "并将业绩预告作为重要领先信号。没有业绩预告是正常结果，严禁虚构。"
            )

        system_message = (
            "你是一名研究员，负责分析公司过去一周的基本面信息。请撰写全面的基本面报告，"
            "涵盖财务文件、公司概况、核心财务数据和历史财务表现，以完整了解公司并为交易员提供依据。"
            "尽可能提供详细内容，并用有证据支持的具体、可执行洞察帮助交易员做出决策。"
            + "请在报告末尾附上一张 Markdown 表格，整理报告要点，确保结构清晰、易读。"
            + "可用工具包括：`get_fundamentals` 用于综合公司分析；`get_balance_sheet`、"
            "`get_cashflow` 和 `get_income_statement` 用于查询具体财务报表。"
            + ashare_instruction
            + get_language_instruction(),
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
        channel = state.get("fundamentals_messages", state.get("messages", []))
        try:
            result = chain.invoke(channel)
            logger.debug("基本面分析师 LLM 调用完成（%d 个工具调用）", len(getattr(result, "tool_calls", []) or []))
        except Exception as exc:
            logger.exception("基本面分析师 LLM 调用失败：%s", exc)
            raise

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        logger.debug("基本面分析师完成：报告长度=%d 字符", len(report or ""))

        return {
            "fundamentals_messages": [result],
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
