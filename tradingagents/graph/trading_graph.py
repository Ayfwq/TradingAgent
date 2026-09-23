# TradingAgents/graph/trading_graph.py：交易 Agent 图。

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import yfinance as yf
from langgraph.prebuilt import ToolNode

# 从 agent_utils 导入抽象工具方法。
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_earnings_forecast,
    get_fundamentals,
    get_global_news,
    get_income_statement,
    get_indicators,
    get_insider_transactions,
    get_lhb_context,
    get_limit_up_context,
    get_macro_indicators,
    get_news,
    get_northbound_flow,
    get_prediction_markets,
    get_sector_context,
    get_stock_data,
    get_verified_market_snapshot,
    resolve_instrument_identity,
)
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG, apply_data_vendors_env
from tradingagents.llm_clients import create_llm_client
from tradingagents.reporting import write_report_tree

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .propagation import Propagator
from .reflection import Reflector
from .setup import GraphSetup
from .signal_processing import SignalProcessor

logger = logging.getLogger(__name__)


def _coerce_max_retries(value):
    """将 ``llm_max_retries`` 校验为非负整数。

    接受整数或数字字符串（环境变量以字符串形式传入）。明确拒绝布尔值和负数，
    让配置错误在启动时暴露，而不是静默禁用重试。
    """
    if isinstance(value, bool):
        raise ValueError(f"llm_max_retries 必须是整数，不能是布尔值：{value!r}")
    if isinstance(value, float):
        raise ValueError(f"llm_max_retries 必须是整数，实际为 {value!r}")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"llm_max_retries 必须是整数，实际为 {value!r}") from exc
    if n < 0:
        raise ValueError(f"llm_max_retries 必须 >= 0，实际为 {n}")
    return n


class TradingAgentsGraph:
    """编排 TradingAgents 框架的主类。"""

    def __init__(
        self,
        selected_analysts=("market", "social", "news", "fundamentals"),
        debug=False,
        config: dict[str, Any] = None,
        callbacks: list | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
        """初始化交易 Agent 图及其组件。

        Args:
            selected_analysts：要包含的分析师类型列表。
            debug：是否以调试模式运行。
            config：配置字典；为 None 时使用默认配置。
            callbacks：可选回调处理器列表（例如跟踪 LLM/工具统计）。
            progress_callback：可选的图状态回调，用于向 Web UI 推送阶段性产物。
        """
        self.debug = debug
        self.config = apply_data_vendors_env(config or DEFAULT_CONFIG)
        self.callbacks = callbacks or []
        self.progress_callback = progress_callback

        logger.info(
            "正在初始化 TradingAgentsGraph：debug=%s，selected_analysts=%s，provider=%s，"
            "deep_llm=%s，quick_llm=%s",
            debug, selected_analysts, self.config.get("llm_provider"),
            self.config.get("deep_think_llm"), self.config.get("quick_think_llm"),
        )

        # 更新接口配置。
        set_config(self.config)

        # 创建必要目录。
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)
        logger.debug(
            "目录已准备就绪：data_cache_dir=%s，results_dir=%s",
            self.config["data_cache_dir"], self.config["results_dir"],
        )

        # 使用服务商专属的思考配置初始化 LLM。
        llm_kwargs = self._get_provider_kwargs()

        # 共享 HTTP 传输：两个 LLM 客户端复用同一连接池，使并发分析师调用（并行分发）
        # 共享到网关的 keep-alive 连接，而不是每个客户端单独建立连接，
        # 从而降低远程网关的实际延迟。
        self._shared_http_client = httpx.Client(
            timeout=httpx.Timeout(300.0, connect=10.0)
        )
        llm_kwargs["http_client"] = self._shared_http_client

        # 如果提供回调，将其加入关键字参数（传给 LLM 构造器）。
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        try:
            deep_client = create_llm_client(
                provider=self.config["llm_provider"],
                model=self.config["deep_think_llm"],
                base_url=self.config.get("backend_url"),
                **llm_kwargs,
            )
            quick_client = create_llm_client(
                provider=self.config["llm_provider"],
                model=self.config["quick_think_llm"],
                base_url=self.config.get("backend_url"),
                **llm_kwargs,
            )
        except Exception as exc:
            logger.exception(
                "创建服务商=%s 的 LLM 客户端失败：%s",
                self.config.get("llm_provider"), exc,
            )
            raise

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()
        logger.debug(
            "LLM 客户端已创建：deep=%s，quick=%s",
            self.config["deep_think_llm"], self.config["quick_think_llm"],
        )

        self.memory_log = TradingMemoryLog(self.config)

        # 创建工具节点。
        self.tool_nodes = self._create_tool_nodes()

        # 初始化组件。
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
            max_tool_rounds=self.config.get("max_tool_rounds", 3),
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
        )

        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 100),
        )
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # 状态跟踪。
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # 日期 -> 完整状态字典。

        # 影响图结构的运行选项，用于检查点签名。
        self.selected_analysts = tuple(selected_analysts)

        # 设置图：保留工作流，以便配合检查点重新编译。
        try:
            self.workflow = self.graph_setup.setup_graph(selected_analysts)
            self.graph = self.workflow.compile()
        except Exception as exc:
            logger.exception("构建/编译交易图失败：%s", exc)
            raise
        self._checkpointer_ctx = None
        logger.info(
            "交易图已编译：节点=%s", list(getattr(self.graph, "nodes", {}).keys())
        )

    def _get_provider_kwargs(self) -> dict[str, Any]:
        """获取创建 LLM 客户端所需的供应商专属参数。"""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        # Web 模型配置携带每个配置专属的密钥。显式传递对并发用户安全，
        # 并避免修改进程级环境变量。
        api_key = self.config.get("llm_api_key")
        if api_key:
            kwargs["api_key"] = api_key

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort

        # 采样温度适用于所有服务商，只要设置就转发。这里使用 float()，使来自
        # TRADINGAGENTS_TEMPERATURE 环境变量的字符串（"0.2"）与程序传入的浮点数一致。
        temperature = self.config.get("temperature")
        if temperature is not None and temperature != "":
            kwargs["temperature"] = float(temperature)

        # SDK 重试额度适用于所有服务商。只有显式设置时才转发，否则保留每个服务商
        # 自己的默认值（通常为 2）（#1091）。
        max_retries = self.config.get("llm_max_retries")
        if max_retries is not None and max_retries != "":
            kwargs["max_retries"] = _coerce_max_retries(max_retries)

        return kwargs

    def _create_tool_nodes(self) -> dict[str, ToolNode]:
        """使用抽象方法为不同数据源创建工具节点。

        每位分析师在独立消息通道上并发运行，因此每个 ToolNode 通过 ``messages_name``
        绑定到对应通道；工具结果会回到所属分析师的临时消息中，而不是共享历史。
        """
        tool_nodes = {
            "market": ToolNode(
                [
                    # 核心股票数据工具。
                    get_stock_data,
                    # 技术指标。
                    get_indicators,
                    # 确定性校验快照（绑定到分析师 LLM 且为提示词所需；必须能在这里
                    # 执行，否则调用失败，模型会报告“不可用”）。
                    get_verified_market_snapshot,
                    # A 股专项上下文（全部优雅降级）。
                    get_lhb_context,
                    get_northbound_flow,
                    get_limit_up_context,
                    get_sector_context,
                ],
                messages_key="market_messages",
            ),
            "social": ToolNode(
                [
                    # 情绪分析使用的新闻工具。
                    get_news,
                ],
                messages_key="sentiment_messages",
            ),
            "news": ToolNode(
                [
                    # 新闻和内幕信息。
                    get_news,
                    get_global_news,
                    get_insider_transactions,
                    get_macro_indicators,
                    get_prediction_markets,
                ],
                messages_key="news_messages",
            ),
            "fundamentals": ToolNode(
                [
                    # 基本面分析工具。
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                    # A 股业绩预告。
                    get_earnings_forecast,
                ],
                messages_key="fundamentals_messages",
            ),
        }
        for channel, node in tool_nodes.items():
            # LangGraph 1.2 将 ToolNode 的公共属性重命名为私有属性。读取两种拼写，
            # 确保日志不会在支持的依赖版本范围内破坏图构建。
            tools_by_name = getattr(
                node, "tools_by_name", getattr(node, "_tools_by_name", {})
            )
            messages_name = getattr(
                node, "messages_name", getattr(node, "_messages_key", "messages")
            )
            logger.debug(
                "工具节点 %s 已就绪，包含 %d 个工具（channel=%s）",
                channel, len(tools_by_name), messages_name,
            )
        return tool_nodes

    def _resolve_benchmark(self, ticker: str) -> str:
        """选择用于计算 ``ticker`` Alpha 的基准代码。

        设置 ``config["benchmark_ticker"]`` 时它拥有最高优先级；否则通过后缀映射匹配
        股票代码的交易所后缀（例如东京市场使用 ``.T``）。没有点号后缀的美股代码会
        回退到空后缀配置（默认 SPY）。无法识别的后缀（包括 ``BRK.B`` 这类带点美股
        代码）也回退到空后缀，因为 Alpha 计算使用美元。
        """
        explicit = self.config.get("benchmark_ticker")
        if explicit:
            logger.debug("%s 的基准被配置覆盖：%s", ticker, explicit)
            return explicit
        benchmark_map = self.config.get("benchmark_map", {})
        ticker_upper = ticker.upper()
        for suffix, benchmark in benchmark_map.items():
            if suffix and ticker_upper.endswith(suffix.upper()):
                logger.debug("%s 通过后缀 %s 解析基准：%s", ticker, suffix, benchmark)
                return benchmark
        benchmark = benchmark_map.get("", "SPY")
        logger.debug("%s 的基准回退到默认值：%s", ticker, benchmark)
        return benchmark

    def _fetch_returns(
        self, ticker: str, trade_date: str, holding_days: int = 5,
        benchmark: str = "SPY",
    ) -> tuple[float | None, float | None, int | None]:
        """获取代码从 trade_date 开始持有 holding_days 天的原始收益和 Alpha。

        ``benchmark`` 是用于计算 Alpha 的基准指数（由调用方通过 ``_resolve_benchmark``
        解析）。返回 ``(raw_return, alpha_return, actual_holding_days)``；价格数据不可用
       （数据太新、已退市或网络错误）时返回 ``(None, None, None)``。

        优先尝试 akshare（新浪）；当前网络屏蔽 Yahoo，因此 yfinance 路径可能永远无法
        解析，使每个决策永久保持“pending”。yfinance 仍作为特殊代码的回退方案。
        """
        from tradingagents.dataflows.akshare_data import get_market_returns

        try:
            resolved = get_market_returns(ticker, trade_date, holding_days, benchmark)
            if resolved != (None, None, None):
                logger.debug(
                    "%s 在 %s 的实际收益：原始=%s Alpha=%s 天数=%s",
                    ticker, trade_date, *resolved,
                )
                return resolved
            logger.debug(
                "akshare 未返回 %s 在 %s 的价格数据（数据太新/已退市）",
                ticker, trade_date,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("通过 akshare 查询 %s 的实际收益失败：%s", ticker, exc)

        # 旧版回退方案（Yahoo），适用于可以访问 Yahoo 的环境。
        from tradingagents.dataflows.symbol_utils import normalize_symbol

        try:
            start = datetime.strptime(trade_date, "%Y-%m-%d")
            end = start + timedelta(days=holding_days + 7)  # 为周末/节假日预留缓冲。
            end_str = end.strftime("%Y-%m-%d")

            # 规范化代码，使实际收益查询与分析定价使用同一标的（例如 XAUUSD -> GC=F）
            #（#984）。基准已经由 ``_resolve_benchmark`` 解析为规范 Yahoo 代码。
            stock = yf.Ticker(normalize_symbol(ticker)).history(start=trade_date, end=end_str)
            bench = yf.Ticker(benchmark).history(start=trade_date, end=end_str)

            if len(stock) < 2 or len(bench) < 2:
                logger.debug(
                    "yfinance 为 %s/%s 在 %s 返回的 K 线不足（股票=%d 基准=%d）",
                    ticker, benchmark, trade_date, len(stock), len(bench),
                )
                return None, None, None

            actual_days = min(holding_days, len(stock) - 1, len(bench) - 1)
            raw = float(
                (stock["Close"].iloc[actual_days] - stock["Close"].iloc[0])
                / stock["Close"].iloc[0]
            )
            bench_ret = float(
                (bench["Close"].iloc[actual_days] - bench["Close"].iloc[0])
                / bench["Close"].iloc[0]
            )
            alpha = raw - bench_ret
            logger.debug(
                "yfinance 计算 %s 在 %s 的实际收益：原始=%.6f Alpha=%.6f 天数=%d",
                ticker, trade_date, raw, alpha, actual_days,
            )
            return raw, alpha, actual_days
        except Exception as e:
            logger.warning(
                "无法解析 %s 在 %s 相对于 %s 的结果（下次运行将重试）：%s",
                ticker, trade_date, benchmark, e,
            )
            return None, None, None

    def _resolve_pending_entries(self, ticker: str) -> None:
        """在新运行开始时解析股票代码的待处理日志条目。

        获取同一代码每个待处理条目的收益，生成反思，然后通过一次原子批量写入保存
        所有更新，避免重复 I/O。跳过价格数据尚不可用的条目（数据太新或已退市）。

        权衡：每次运行只解析同一代码的条目。其他代码的条目会累积，直到再次运行该代码。
        """
        pending = [e for e in self.memory_log.get_pending_entries() if e["ticker"] == ticker]
        if not pending:
            return
        logger.info("正在解析 %s 的 %d 个待处理条目", ticker, len(pending))

        benchmark = self._resolve_benchmark(ticker)
        updates = []
        for entry in pending:
            raw, alpha, days = self._fetch_returns(
                ticker, entry["date"], benchmark=benchmark,
            )
            if raw is None:
                logger.debug(
                    "%s 在 %s 的待处理条目仍缺少价格数据，下次运行重试",
                    ticker, entry["date"],
                )
                continue  # 价格暂不可用，下次运行重试。
            reflection = self.reflector.reflect_on_final_decision(
                final_decision=entry.get("decision", ""),
                raw_return=raw,
                alpha_return=alpha,
                benchmark_name=benchmark,
            )
            updates.append({
                "ticker": ticker,
                "trade_date": entry["date"],
                "raw_return": raw,
                "alpha_return": alpha,
                "holding_days": days,
                "reflection": reflection,
            })

        if updates:
            logger.info(
                "正在写入 %s 的 %d 个已解析条目结果", ticker, len(updates)
            )
            self.memory_log.batch_update_with_outcomes(updates)

    def resolve_instrument_context(self, ticker: str, asset_type: str = "stock") -> str:
        """解析一次股票代码身份并返回完整标的上下文。

        将确定性的 yfinance 查询结果（带缓存、失败开放）注入上下文字符串，让每个
        Agent 都绑定真实公司，而不是从价格图表中臆测公司（#814）。propagate() 路径
        Web 和程序化入口都会调用此方法，确保解析后的身份从任意入口传遍整个图。
        """
        identity = resolve_instrument_identity(ticker)
        logger.debug(
            "已解析 %s 的标的身份（asset_type=%s）：%s",
            ticker, asset_type, identity,
        )
        return build_instrument_context(ticker, asset_type, identity)

    def _run_signature(self, asset_type: str) -> str:
        """发生变化时必须使检查点失效的图结构输入。

        这些值会纳入检查点线程 ID，因此分析师选择、辩论/风险深度或资产模式变化时
        会重新开始，而不是静默延续之前的图（#1089）。
        """
        return "|".join([
            "layout=parallel-v1",
            "analysts=" + ",".join(self.selected_analysts),
            f"debate={self.config['max_debate_rounds']}",
            f"risk={self.config['max_risk_discuss_rounds']}",
            f"asset={asset_type}",
        ])

    def propagate(self, company_name, trade_date, asset_type: str = "stock"):
        """在指定日期为公司运行交易 Agent 图。

        ``asset_type`` 在股票流水线（默认）和 #567 提供的加密货币流水线（``"crypto"``）
        之间选择；Web 会根据股票代码自动检测，程序调用方显式传入。当配置中设置
        ``checkpoint_enabled`` 时，图会使用 PostgreSQL 中每个代码独立的线程重新编译，
        使崩溃运行可以在下次使用相同代码+日期调用时从最后一个成功节点恢复。
        """
        self.ticker = company_name
        logger.info(
            "已调用 propagate()：ticker=%s，trade_date=%s，asset_type=%s",
            company_name, trade_date, asset_type,
        )

        # 在流水线运行前解析该代码的待处理记忆日志条目。
        self._resolve_pending_entries(company_name)

        # 如果用户启用检查点，则使用检查点重新编译。
        if self.config.get("checkpoint_enabled"):
            self._checkpointer_ctx = get_checkpointer(
                self.config.get("checkpoint_database_url")
            )
            saver = self._checkpointer_ctx.__enter__()
            self.graph = self.workflow.compile(checkpointer=saver)

            step = checkpoint_step(
                self.config.get("checkpoint_database_url"), company_name, str(trade_date),
                self._run_signature(asset_type),
            )
            if step is not None:
                logger.info(
                    "从步骤 %d 恢复 %s 在 %s 的运行", step, company_name, trade_date
                )
            else:
                logger.info("全新开始 %s 在 %s 的运行", company_name, trade_date)

        try:
            logger.info(
                "执行 %s 在 %s 的图流水线（asset_type=%s）",
                company_name, trade_date, asset_type,
            )
            return self._run_graph(company_name, trade_date, asset_type=asset_type)
        except Exception as exc:
            logger.exception(
                "%s 在 %s 的图流水线失败：%s", company_name, trade_date, exc
            )
            raise
        finally:
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()

    def save_reports(self, final_state, ticker, save_path=None) -> Path:
        """为已完成的运行写入 Markdown 报告树，与 Web 行为一致。

        程序调用方会得到与 Web 相同的磁盘报告。可显式传入 ``save_path``，或使用
        ``results_dir`` 下的默认路径。
        """
        if save_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = (
                Path(self.config["results_dir"])
                / "reports"
                / f"{safe_ticker_component(ticker)}_{stamp}"
            )
        return write_report_tree(final_state, ticker, save_path)

    def _run_graph(self, company_name, trade_date, asset_type: str = "stock"):
        """执行图，并将结果状态写入磁盘和记忆日志。"""
        started = time.monotonic()
        # 初始化状态：为投资组合经理注入记忆日志上下文，
        # 为所有 Agent 注入已确定解析的标的身份。
        past_context = self.memory_log.get_past_context(company_name)
        instrument_context = self.resolve_instrument_context(company_name, asset_type)
        init_agent_state = self.propagator.create_initial_state(
            company_name,
            trade_date,
            asset_type=asset_type,
            past_context=past_context,
            instrument_context=instrument_context,
        )
        args = self.propagator.get_graph_args()
        logger.debug(
            "已为 %s（%s）准备初始状态；past_context=%s",
            company_name, trade_date, bool(past_context),
        )

        # 注入 thread_id，使相同代码+日期+图结构可以恢复；日期或图结构不同则重新开始（#1089）。
        if self.config.get("checkpoint_enabled"):
            tid = thread_id(company_name, str(trade_date), self._run_signature(asset_type))
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid
            logger.debug("检查点 thread_id=%s", tid)

        try:
            if self.debug or self.progress_callback:
                trace = []
                streamed_state = {}
                last_printed = None
                for chunk in self.graph.stream(init_agent_state, **args):
                    trace.append(chunk)
                    streamed_state.update(chunk)
                    if self.progress_callback:
                        try:
                            self.progress_callback(dict(streamed_state))
                        except Exception:  # noqa: BLE001 - UI progress must not stop analysis
                            logger.exception("推送图阶段产物失败，继续执行分析")
                    if self.debug and chunk.get("messages"):
                        msg = chunk["messages"][-1]
                        # 交易员之后的节点不会向 messages 追加内容，因此同一条尾部消息
                        # 会在多个数据块重复。只在消息变化时打印（#1027）；轨迹/状态合并不变。
                        signature = (type(msg).__name__, getattr(msg, "content", None))
                        if signature != last_printed:
                            msg.pretty_print()
                            last_printed = signature
                # 流式数据块是逐节点增量。合并它们，使返回状态与非调试路径中
                # graph.invoke() 的结果一致。
                final_state = streamed_state
                logger.debug("调试流已执行，共 %d 个数据块", len(trace))
            else:
                final_state = self.graph.invoke(init_agent_state, **args)
        except Exception as exc:
            logger.exception(
                "%s（%s）的图执行失败：%s", company_name, trade_date, exc
            )
            raise
        logger.info(
            "%s（%s）的图执行已完成：耗时 %.1f 秒",
            company_name, trade_date, time.monotonic() - started,
        )

        # 保存当前状态，供反思使用。
        self.curr_state = final_state

        # 将状态记录到磁盘。
        self._log_state(trade_date, final_state)

        # 保存决策，供下次运行同一代码时延迟反思。
        logger.info("正在保存 %s（%s）的决策", company_name, trade_date)
        self.memory_log.store_decision(
            ticker=company_name,
            trade_date=trade_date,
            final_trade_decision=final_state["final_trade_decision"],
        )

        # 成功完成后清除检查点，避免保留过期状态。
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config.get("checkpoint_database_url"), company_name, str(trade_date),
                self._run_signature(asset_type),
            )
            logger.debug("已清除 %s（%s）的检查点", company_name, trade_date)

        signal = self.process_signal(final_state["final_trade_decision"])
        logger.info(
            "最终决策：%s（%s）为 %s", company_name, trade_date, signal
        )
        return final_state, signal

    def _log_state(self, trade_date, final_state):
        """将最终状态记录到 JSON 文件。"""
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "aggressive_history": final_state["risk_debate_state"]["aggressive_history"],
                "conservative_history": final_state["risk_debate_state"]["conservative_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
        }

        # 保存到文件。拒绝作为路径组件拼接后会逃逸结果目录的股票代码。
        safe_ticker = safe_ticker_component(self.ticker)
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(self.log_states_dict[str(trade_date)], f, indent=4)
            logger.info(
                "状态快照已写入：ticker=%s trade_date=%s path=%s",
                self.ticker, trade_date, log_path,
            )
        except Exception as exc:
            logger.error("写入状态快照 %s 失败：%s", log_path, exc)

    def process_signal(self, full_signal):
        """处理信号并提取核心决策。"""
        logger.debug("正在处理完整信号：%s", full_signal)
        return self.signal_processor.process_signal(full_signal)
