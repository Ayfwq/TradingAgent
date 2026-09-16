import logging

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_indicators,
    get_instrument_context_from_state,
    get_language_instruction,
    get_lhb_context,
    get_limit_up_context,
    get_northbound_flow,
    get_sector_context,
    get_stock_data,
    get_verified_market_snapshot,
    is_ashare_ticker,
)

logger = logging.getLogger(__name__)


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        is_ashare = is_ashare_ticker(ticker)
        instrument_context = get_instrument_context_from_state(state)
        logger.debug("市场分析师节点调用：代码=%s 日期=%s", state.get("company_of_interest"), state.get("trade_date"))

        tools = [
            get_stock_data,
            get_indicators,
            get_verified_market_snapshot,
        ]
        if is_ashare:
            tools.extend(
                [
                    get_lhb_context,
                    get_northbound_flow,
                    get_limit_up_context,
                    get_sector_context,
                ]
            )

        ashare_instruction = ""
        if is_ashare:
            ashare_instruction = """

这是 A 股。请在相关场景使用 A 股上下文工具：使用
get_northbound_flow 和 get_sector_context 评估资金流向与行业广度；使用
get_lhb_context 和 get_limit_up_context 检查异常交易、席位活动和涨停动能。
龙虎榜、涨停池或行业没有匹配结果是有效结果，不代表工具失败。没有工具数据时，
不要自行推断这些信号。
"""

        system_message = (
            """你是一名负责分析金融市场的交易助手。你的任务是根据市场状态或交易策略，从以下列表中选择
最相关的**指标**。目标是选择最多 **8 个指标**，提供互补信息且避免重复。各类别及指标如下：

移动平均线：
- close_50_sma：50 日 SMA，中期趋势指标。用途：识别趋势方向并作为动态支撑/阻力。提示：滞后于价格，应与更快指标结合以获得及时信号。
- close_200_sma：200 日 SMA，长期趋势基准。用途：确认整体市场趋势并识别金叉/死叉形态。提示：反应较慢，更适合战略性趋势确认，不宜用于频繁入场。
- close_10_ema：10 日 EMA，灵敏的短期均线。用途：捕捉动能快速变化和潜在入场点。提示：震荡市中噪声较多，应与长期均线结合过滤虚假信号。

MACD 相关：
- macd：MACD，通过 EMA 差值计算动能。用途：观察交叉和背离，识别趋势变化。提示：低波动或横盘市场需结合其他指标确认。
- macds：MACD 信号线，对 MACD 线进行 EMA 平滑。用途：与 MACD 线交叉时触发交易信号。提示：应纳入更完整策略，避免误报。
- macdh：MACD 柱状图，显示 MACD 线与信号线的差距。用途：观察动能强弱并尽早发现背离。提示：可能波动较大，快速市场中需配合额外过滤条件。

动能指标：
- rsi：RSI，衡量动能并提示超买/超卖。用途：应用 70/30 阈值并观察背离，识别反转信号。提示：强趋势中 RSI 可能长期处于极端区间，务必结合趋势分析。

波动率指标：
- boll：布林中轨，以 20 日 SMA 为基础。用途：作为价格运动的动态基准。提示：结合上下轨可更有效地发现突破或反转。
- boll_ub：布林上轨，通常位于中轨上方 2 个标准差处。用途：提示潜在超买和突破区域。提示：需结合其他工具确认，强趋势中价格可能沿上轨运行。
- boll_lb：布林下轨，通常位于中轨下方 2 个标准差处。用途：提示潜在超卖。提示：需追加分析，避免错误的反转信号。
- atr：ATR，以真实波幅均值衡量波动率。用途：设置止损位并根据当前波动率调整仓位。提示：这是反应型指标，应作为更完整风险管理策略的一部分。

成交量指标：
- vwma：VWMA，按成交量加权的移动平均线。用途：结合价格行为和成交量确认趋势。提示：成交量尖峰可能导致结果偏斜，应结合其他成交量分析。

请选择信息多样且互补的指标，避免重复（例如不要同时选择 rsi 和 stochrsi）。简要说明指标为何适合当前市场环境。
调用工具时必须使用上面列出的指标名称，因为它们是定义好的参数，否则调用会失败。请先调用
get_stock_data 获取生成指标所需的 CSV，再用具体指标名称调用 get_indicators。

撰写最终报告前，请调用 get_verified_market_snapshot 获取此代码和当前日期的快照，并将其作为所有精确 OHLCV、价格水平
或指标值的事实来源。如果其他工具输出与已验证快照冲突，请明确指出差异，不要自行编造一个调和后的数字。除非工具输出提供了
具体日期和价格，否则不要声称存在历史验证、支撑/阻力反弹或精确百分比涨跌。

请撰写非常详细、细致且有层次的趋势报告，用有证据支持的具体、可执行洞察帮助交易员做出决策。"""
            + ashare_instruction
            + """请在报告末尾附上一张 Markdown 表格，整理报告要点，确保结构清晰、易读。"""
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
        channel = state.get("market_messages", state.get("messages", []))
        try:
            result = chain.invoke(channel)
            logger.debug("市场分析师 LLM 调用完成（%d 个工具调用）", len(getattr(result, "tool_calls", []) or []))
        except Exception as exc:
            logger.exception("市场分析师 LLM 调用失败：%s", exc)
            raise

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        logger.debug("市场分析师完成：报告长度=%d 字符", len(report or ""))

        return {
            "market_messages": [result],
            "market_report": report,
        }

    return market_analyst_node
