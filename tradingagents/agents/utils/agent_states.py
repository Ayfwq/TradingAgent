import logging
from typing import Annotated

from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


# 研究团队状态
class InvestDebateState(TypedDict):
    bull_history: Annotated[
        str, "看多方对话历史"
    ]  # 看多方对话历史
    bear_history: Annotated[
        str, "看空方对话历史"
    ]  # 看空方对话历史
    history: Annotated[str, "对话历史"]  # 对话历史
    current_response: Annotated[str, "最新回复"]  # 最新回复
    judge_decision: Annotated[str, "最终裁判决策"]  # 最新回复
    count: Annotated[int, "当前对话长度"]  # 对话长度


# 风险管理团队状态
class RiskDebateState(TypedDict):
    aggressive_history: Annotated[
        str, "激进智能体的对话历史"
    ]  # 对话历史
    conservative_history: Annotated[
        str, "保守智能体的对话历史"
    ]  # 对话历史
    neutral_history: Annotated[
        str, "中性智能体的对话历史"
    ]  # 对话历史
    history: Annotated[str, "对话历史"]  # 对话历史
    latest_speaker: Annotated[str, "最近发言的分析师"]
    current_aggressive_response: Annotated[
        str, "激进分析师的最新回复"
    ]  # 最新回复
    current_conservative_response: Annotated[
        str, "保守分析师的最新回复"
    ]  # 最新回复
    current_neutral_response: Annotated[
        str, "中性分析师的最新回复"
    ]  # 最新回复
    judge_decision: Annotated[str, "裁判决策"]
    count: Annotated[int, "当前对话长度"]  # 对话长度


class AgentState(MessagesState):
    company_of_interest: Annotated[str, "正在交易的目标公司"]
    asset_type: Annotated[str, "正在分析的资产类型，例如股票或加密货币"]
    instrument_context: Annotated[str, "运行开始时确定性解析出的代码身份"]
    trade_date: Annotated[str, "交易日期"]

    sender: Annotated[str, "发送此消息的智能体"]

    # 每个分析师拥有独立的消息通道。分析师会并发运行（扇出），因此各自使用
    # 临时消息，而不是共享全局的 ``messages`` 列表；否则工具调用轮次会在
    # 共享历史中交错，污染彼此的上下文（#parallel-analysts）。
    # 共享的 ``messages`` 通道保留给分析师之后的顺序阶段（辩论 / 交易员 /
    # 风险管理），同时用于向后兼容。
    market_messages: Annotated[list, add_messages]
    sentiment_messages: Annotated[list, add_messages]
    news_messages: Annotated[list, add_messages]
    fundamentals_messages: Annotated[list, add_messages]

    # 每个分析师的清理节点写入“已完成”标记。分析师屏障据此区分“分析师已完成
    # 但产生了空报告”（少见的 LLM 失败，辩论应继续使用剩余报告）和“分析师
    # 仍在运行”（屏障必须等待）。
    market_done: Annotated[bool, "市场分析师已完成"]
    sentiment_done: Annotated[bool, "情绪分析师已完成"]
    news_done: Annotated[bool, "新闻分析师已完成"]
    fundamentals_done: Annotated[bool, "基本面分析师已完成"]

    # 研究步骤
    market_report: Annotated[str, "市场分析师报告"]
    sentiment_report: Annotated[str, "情绪分析师报告"]
    news_report: Annotated[
        str, "新闻研究员关于当前世界局势的报告"
    ]
    fundamentals_report: Annotated[str, "基本面研究员报告"]

    # 研究团队讨论步骤
    investment_debate_state: Annotated[
        InvestDebateState, "当前是否投资的辩论状态"
    ]
    investment_plan: Annotated[str, "分析师生成的计划"]

    trader_investment_plan: Annotated[str, "交易员生成的计划"]

    # 风险管理团队讨论步骤
    risk_debate_state: Annotated[
        RiskDebateState, "当前风险评估辩论状态"
    ]
    final_trade_decision: Annotated[str, "风险分析师作出的最终决策"]
    past_context: Annotated[str, "运行开始时注入的记忆日志上下文（同股票决策和其他股票经验）"]

logger.debug(
    "已加载智能体状态模式：InvestDebateState、RiskDebateState、AgentState"
)
