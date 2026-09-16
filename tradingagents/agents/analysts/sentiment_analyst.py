"""情绪分析师：针对目标代码进行多来源情绪分析。

该模块以前名为 ``social_media_analyst``。由于旧提示词要求进行社交媒体分析，
但实际只有 Yahoo Finance 新闻工具，LLM 在提示压力下会虚构 Reddit、X 和
StockTwits 内容（已通过实际运行验证），因此重新命名并设计。

新版 Agent 在调用 LLM 前预取三个互补数据源，并以结构化区块注入提示词：

  1. 新闻标题       —— Yahoo Finance（机构视角）
  2. StockTwits 消息 —— 按 cashtag 索引的散户帖子，带有用户标注的看多/看空情绪标签
  3. Reddit 帖子    —— r/wallstreetbets、r/stocks、r/investing

该 Agent 不进行工具调用，数据从第 0 轮开始就已写入提示词。输出采用结构化输出模式
（OpenAI/xAI 使用 json_schema，Gemini 使用 response_schema，Anthropic 使用 tool-use），
不支持原生结构化输出的服务商则回退到自由文本生成。这样情绪标题（区间、分数、置信度）
在不同运行和服务商之间保持确定性，而不是依赖各模型自由发挥的文本。

See: https://github.com/TauricResearch/TradingAgents/issues/557
See: https://github.com/TauricResearch/TradingAgents/issues/796
"""

import logging
from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import SentimentReport, render_sentiment_report
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_news,
)
from tradingagents.agents.utils.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages

logger = logging.getLogger(__name__)


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def create_sentiment_analyst(llm):
    """为交易图创建情绪分析师节点。

    预取新闻、StockTwits 和 Reddit 数据，以结构化区块注入提示词，并通过结构化
    输出生成确定性的情绪报告；不支持该能力的服务商回退到自由文本生成。
    """
    structured_llm = bind_structured(llm, SentimentReport, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        instrument_context = get_instrument_context_from_state(state)
        logger.debug("情绪分析师节点调用：代码=%s 日期=%s", state.get("company_of_interest"), state.get("trade_date"))

        # 预取三个数据源。每个抓取器都会优雅降级并返回字符串（异常不会从这里
        # 冒出），因此 LLM 始终能看到实际数据或明确的占位说明。
        news_block = get_news.func(ticker, start_date, end_date)
        stocktwits_block = fetch_stocktwits_messages(ticker, limit=30)
        reddit_block = fetch_reddit_posts(ticker)

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            stocktwits_block=stocktwits_block,
            reddit_block=reddit_block,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一名乐于协作的 AI 助手，正在与其他助手共同工作。"
                    "如果你或其他助手已经给出 FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** 或完成交付，"
                    "请在回复前加上 FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**，以便团队停止继续调用。"
                    # 这里不进行工具调用：数据已经预取并写入提示词，加入工具范围描述
                    # 只会诱导模型虚构工具调用（#1130）。
                    "今天是 {current_date}；所有分析都以它作为当前日期。{instrument_context}"
                    " " + NO_EXTERNAL_TOOLS +
                    "\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        # 将模板格式化为具体消息列表，确保结构化输出和自由文本路径接收相同输入。
        # 不使用 bind_tools，因为数据已经在提示词中。
        # 图并行运行分析师时从其独立通道读取；直接调用（单元测试、旧 checkpoint）
        # 时回退到旧的共享 ``messages`` 通道。
        channel = state.get("sentiment_messages", state.get("messages", []))
        formatted_messages = prompt.format_messages(messages=channel)

        try:
            report_text = invoke_structured_or_freetext(
                structured_llm,
                llm,
                formatted_messages,
                render_sentiment_report,
                "Sentiment Analyst",
            )
            logger.debug("情绪分析师 LLM 调用完成")
        except Exception as exc:
            logger.exception("情绪分析师 LLM 调用失败：%s", exc)
            raise

        logger.debug("情绪分析师完成：报告长度=%d 字符", len(report_text or ""))

        return {
            "sentiment_messages": [AIMessage(content=report_text)],
            # 同步写入共享通道：直接调用方和旧图消费者仍会读取 result["messages"]。
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        }

    return sentiment_analyst_node


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
) -> str:
    """组装带结构化数据区块的情绪分析师系统消息。"""
    return f"""你是一名金融市场情绪分析师。你的任务是为 {ticker} 撰写覆盖 {start_date} 至 {end_date} 的全面情绪报告，
并使用已经为你收集好的三个互补数据源。

## 数据源（已预取并写入本提示词）

### 新闻标题 —— Yahoo Finance，过去 7 天
机构视角，以事实为基础、变化较慢的信号。

<start_of_news>
{news_block}
<end_of_news>

### StockTwits 消息 —— 按 cashtag 索引的散户社交平台
变化快速的信号。每条消息包含用户标注的情绪标签（看多/看空/无标签）和正文。

<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>

### Reddit 帖子 —— r/wallstreetbets、r/stocks、r/investing（过去 7 天）
社区讨论。通过赞成票和评论数衡量参与度。要考虑子版块特征（r/wallstreetbets 往往更逆向、
更热烈；r/stocks 更克制；r/investing 更关注长期）。

<start_of_reddit>
{reddit_block}
<end_of_reddit>

## 数据分析方法（最佳实践）

1. **把 StockTwits 看多/看空比例视为领先的散户情绪信号。** 70/30 的看多/看空比例代表温和看多；≥90/10 可能代表过度延伸和逆向风险；50/50 表示不确定。样本量很重要，必须基于实际消息数判断，不能只看百分比。

2. **寻找跨来源分歧。** 如果新闻视角看空但 StockTwits 压倒性看多，这种错配本身就是信号——可能表示散户正在押注新闻流尚未反映的逻辑，也可能表示散户追涨而机构保持谨慎。

3. **按参与度为 Reddit 帖子加权。** 获得 400 个赞、200 条评论的帖子代表社区关注；只有 3 个赞的帖子可能只是噪声。阅读正文摘录以了解上下文，因为仅看标题经常会误导。

4. **区分观点与事件。** 新闻标题（“Nvidia 宣布与 Corning 达成 5 亿美元交易”）是事件；StockTwits 帖子（“买入 NVDA，它要起飞了”）是观点。二者都可作为输入，但在结论中应采用不同权重。

5. **识别反复出现的叙事主题。** 哪个话题在多个来源中不断出现？它就是推动当前情绪的主导叙事。

6. **诚实说明数据限制。** 如果 StockTwits 只有少量消息，或某个数据源返回了“<unavailable>”占位符，情绪判断就不够稳健，必须在 `confidence` 字段和叙述中明确标注。如果某个来源没有覆盖指定子版块，也要如实说明。

7. **识别跨来源出现的催化剂和风险**，例如即将公布的业绩、产品发布、竞争威胁和宏观新闻等。

8. **历史情绪不具有预测性。** 应把结论表述为交易员需要结合基本面和技术面权衡的信号，而不是对价格的直接判断。

## 输出字段

请填写以下字段：

- **overall_band**：只能填写 Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish 之一。当来源明确指向不同方向时使用 Mixed；只有所有来源确实没有明确观点时才使用 Neutral。
- **overall_score**：0（极度看空）到 10（极度看多）的数字，5 表示中性。分数必须与 overall_band 一致。
- **confidence**：根据数据质量和样本量填写 low / medium / high。
- **narrative**：完整说明各来源、分歧、主导叙事主题、催化剂和风险，并用 Markdown 表格总结关键情绪信号（方向、来源、支持证据）。

{get_language_instruction()}"""


# ---------------------------------------------------------------------------
# 向后兼容适配层
# ---------------------------------------------------------------------------
def create_social_media_analyst(llm):
    """已弃用的 :func:`create_sentiment_analyst` 别名。

    保留该别名，以便仍然导入 ``create_social_media_analyst`` 的现有代码继续工作。

    .. deprecated::
        请直接导入 :func:`create_sentiment_analyst`。
    """
    logger.debug("调用情绪分析师的已弃用别名 create_social_media_analyst")
    import warnings
    warnings.warn(
        "create_social_media_analyst 已弃用，并将在未来版本移除。请改用 "
        "create_sentiment_analyst。",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)
