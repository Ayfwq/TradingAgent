import functools
import logging
from collections.abc import Mapping
from typing import Any

import yfinance as yf
from langchain_core.messages import HumanMessage, RemoveMessage

# 从独立的工具模块导入数据工具。
from tradingagents.agents.utils.ashare_context_tools import (
    get_earnings_forecast,
    get_lhb_context,
    get_limit_up_context,
    get_northbound_flow,
    get_sector_context,
)
from tradingagents.agents.utils.core_stock_tools import get_stock_data
from tradingagents.agents.utils.fundamental_data_tools import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
)
from tradingagents.agents.utils.macro_data_tools import get_macro_indicators
from tradingagents.agents.utils.market_data_validation_tools import get_verified_market_snapshot
from tradingagents.agents.utils.news_data_tools import (
    get_global_news,
    get_insider_transactions,
    get_news,
)
from tradingagents.agents.utils.prediction_markets_tools import get_prediction_markets
from tradingagents.agents.utils.technical_indicators_tools import get_indicators

# 公共导出面：数据工具集中在此处导出，Agent 和图可以从同一位置导入；
# 下方还定义了标的与语言相关的辅助函数。
__all__ = [
    "get_stock_data",
    "get_indicators",
    "get_fundamentals",
    "get_balance_sheet",
    "get_cashflow",
    "get_income_statement",
    "get_news",
    "get_global_news",
    "get_insider_transactions",
    "get_macro_indicators",
    "get_prediction_markets",
    "get_verified_market_snapshot",
    "get_lhb_context",
    "get_northbound_flow",
    "get_limit_up_context",
    "get_sector_context",
    "get_earnings_forecast",
    "is_ashare_ticker",
    "build_instrument_context",
    "resolve_instrument_identity",
    "get_instrument_context_from_state",
    "get_language_instruction",
    "create_msg_delete",
]

logger = logging.getLogger(__name__)


def is_ashare_ticker(ticker: str) -> bool:
    """判断 ``ticker`` 是否为受支持的中国内地 A 股代码。

    支持带上海、深圳、北京交易所后缀的代码，以及 akshare 已支持的六位纯数字
    代码。该检查不访问网络，分析师节点可以在调用 LLM 前据此决定暴露哪些工具
    schema。
    """
    if not isinstance(ticker, str):
        return False
    raw = ticker.strip().upper()
    for suffix in (".SS", ".SH", ".SZ", ".BJ"):
        if raw.endswith(suffix):
            code = raw[: -len(suffix)]
            return len(code) == 6 and code.isdigit()
    return len(raw) == 6 and raw.isdigit() and raw[0] in "012345689"


def get_language_instruction() -> str:
    """返回配置的输出语言对应的提示词指令。

    配置非英语输出时返回明确指令。该指令覆盖报告、推理、工具调用文本和
    Agent 中间消息，避免本地化运行混用多种语言。所有输出会进入已保存报告的
    Agent（分析师、研究员、辩论员、研究经理、交易员和投资组合经理）都会应用
    该指令，从而生成完整本地化的报告。
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    if lang.strip().lower() in ("chinese", "zh", "简体中文", "中文"):
        # 比通用指令更具体：固定 A 股术语，使中文报告更像原生研究笔记，而不是
        # 直译文本。
        return (
            " Write your entire response in 简体中文。请将所有回复、分析过程、研究员之间的讨论、工具调用中的自然语言参数、"
            "日志摘要和最终报告全部使用简体中文；股票代码、公司英文名、数据源名称、"
            "JSON 键名和 Markdown 语法可以保留原样。使用标准中文金融术语："
            "买入/增持/持有/减持/卖出，市盈率/市净率/净资产收益率，止损/目标价/仓位，"
            "以及北向资金/龙虎榜/涨停板/业绩预告。不要因为数据源标题是英文就改用英文。"
        )
    return f" Write your entire response in {lang}."


def _clean_identity_value(value: Any) -> str | None:
    """返回去除首尾空白的字符串；空值或占位值返回 None。"""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"none", "n/a", "nan", "null"}:
        return None
    return cleaned


@functools.lru_cache(maxsize=256)
def resolve_instrument_identity(ticker: str) -> dict:
    """确定性解析代码对应的身份元数据（公司名、行业等）。

    这样可以避免图表形态暗示了其他行业时，流水线臆造出另一家公司（#814）。
    如果没有真实公司名，市场分析师可能把价格走势套入某个叙事并虚构身份，
    这个错误随后会扩散到所有下游 Agent。

    该解析按尽力而为设计：如果 yfinance 不可用、触发限流或无法识别代码，
    返回 ``{}``，调用方退回仅含代码的上下文，不会在分析开始前直接失败。
    结果会缓存，每个进程对同一代码最多查询一次。

    会先标准化代码（例如 ``XAUUSD`` -> ``GC=F``），确保身份解析和实际行情
    请求针对的是同一个标的（#983）。
    """
    from tradingagents.dataflows.symbol_utils import normalize_symbol

    try:
        info = yf.Ticker(normalize_symbol(ticker)).info or {}
    except Exception as exc:  # noqa: BLE001 — 容错放行，不阻塞运行
        logger.debug("无法解析标的身份 %s：%s", ticker, exc)
        return {}

    identity: dict[str, str] = {}
    company_name = _clean_identity_value(info.get("longName")) or _clean_identity_value(
        info.get("shortName")
    )
    if company_name:
        identity["company_name"] = company_name
    for source_key, target_key in (
        ("sector", "sector"),
        ("industry", "industry"),
        ("exchange", "exchange"),
        ("quoteType", "quote_type"),
    ):
        value = _clean_identity_value(info.get(source_key))
        if value:
            identity[target_key] = value
    return identity


def build_instrument_context(
    ticker: str,
    asset_type: str = "stock",
    identity: Mapping[str, str] | None = None,
) -> str:
    """描述精确的分析标的，确保 Agent 保留身份和代码。

    如果提供了通过 :func:`resolve_instrument_identity` 确定性解析出的
    ``identity``，就把公司名称和业务分类注入上下文，让 Agent 锚定真实公司，
    而不是把价格图表误套到其他公司上（#814）。
    """
    is_crypto = asset_type == "crypto"
    instrument_label = "加密资产" if is_crypto else "金融标的"
    context = (
        f"待分析的{instrument_label}是 `{ticker}`。"
        "所有工具调用、报告和建议都必须使用此精确代码，保留交易所后缀"
        "（例如 `.TO`、`.L`、`.HK`、`.T`、`-USD`）。"
    )

    details = []
    if identity:
        name = identity.get("company_name") or identity.get("name")
        if name:
            details.append(f"{'名称' if is_crypto else '公司'}：{name}")
        sector, industry = identity.get("sector"), identity.get("industry")
        if sector and industry:
            details.append(f"业务分类：{sector} / {industry}")
        elif sector:
            details.append(f"行业：{sector}")
        elif industry:
            details.append(f"细分行业：{industry}")
        if identity.get("exchange"):
            details.append(f"交易所：{identity['exchange']}")

    if details:
        context += (
            f"已解析身份：{'；'.join(details)}。"
            "除非工具结果明确推翻该身份，否则不要替换成其他公司或代码。"
        )

    if is_crypto:
        context += (
            "请将其视为加密资产而非公司，不要假定存在公司基本面数据。"
        )
    return context


def get_instrument_context_from_state(state: Mapping[str, Any]) -> str:
    """返回当前运行的标的上下文。

    优先使用运行开始时计算并写入 state 的身份解析上下文（见
    ``TradingAgentsGraph.resolve_instrument_context``）。如果构造 state 时没有
    提供该上下文（例如直接编程调用或测试），则退回仅含代码的上下文且不访问
    网络，避免调用方在图运行过程中被迫请求 yfinance。
    """
    context = state.get("instrument_context")
    if isinstance(context, str) and context.strip():
        return context
    return build_instrument_context(
        str(state["company_of_interest"]),
        state.get("asset_type", "stock"),
    )


def create_msg_delete(messages_key: str = "messages", done_key: str | None = None):
    """为指定 state 通道创建消息清理节点。

    ``messages_key`` 决定要清理的通道（共享通道使用 ``messages``，每位分析师
    使用 ``market_messages`` 等独立通道）。分析师并行运行，因此每个节点只能
    清理自己的临时消息，不能清理共享历史。

    可选的 ``done_key`` 会在共享 state 中标记分析师完成。Analyst Barrier 用它
    区分“分析师已完成但报告为空”（LLM 偶发失败，辩论仍应带着其余报告继续）
    和“分析师仍在运行”（Barrier 必须继续等待）。
    """

    def delete_messages(state):
        """清理消息并添加带有上下文锚点的占位消息。

        占位消息不能只是 ``"Continue"``：部分 OpenAI 兼容服务商会把它直接
        当成用户任务，围绕“继续”这个词生成内容，而不是分析标的（#888）。
        绑定已解析的标的上下文和日期，即使服务商把占位消息当成独立请求，
        也能让下一位分析师继续处理正确任务。
        """
        messages = state.get(messages_key, [])
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        instrument_context = get_instrument_context_from_state(state)
        trade_date = state.get("trade_date", "请求的日期")
        placeholder = HumanMessage(
            content=(
                f"请继续完成你在本流程中负责的分析。"
                f"{instrument_context} 分析日期为 {trade_date}。"
            )
        )
        update = {messages_key: removal_operations + [placeholder]}
        if done_key:
            update[done_key] = True
        return update

    return delete_messages



