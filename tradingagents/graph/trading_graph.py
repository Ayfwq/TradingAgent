# TradingAgents/graph/trading_graph.py

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import yfinance as yf
from langgraph.prebuilt import ToolNode

# Import the abstract tool methods from agent_utils
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
    """Validate an ``llm_max_retries`` value to a non-negative int.

    Accepts an int or a numeric string (env vars arrive as strings). Rejects
    booleans and negatives loudly so a misconfiguration fails at startup rather
    than silently disabling retries.
    """
    if isinstance(value, bool):
        raise ValueError(f"llm_max_retries must be an integer, not a boolean: {value!r}")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"llm_max_retries must be an integer, got {value!r}") from exc
    if n < 0:
        raise ValueError(f"llm_max_retries must be >= 0, got {n}")
    return n


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=("market", "social", "news", "fundamentals"),
        debug=False,
        config: dict[str, Any] = None,
        callbacks: list | None = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
        """
        self.debug = debug
        self.config = apply_data_vendors_env(config or DEFAULT_CONFIG)
        self.callbacks = callbacks or []

        logger.info(
            "Initializing TradingAgentsGraph debug=%s selected_analysts=%s provider=%s "
            "deep_llm=%s quick_llm=%s",
            debug, selected_analysts, self.config.get("llm_provider"),
            self.config.get("deep_think_llm"), self.config.get("quick_think_llm"),
        )

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)
        logger.debug(
            "Directories ready: data_cache_dir=%s results_dir=%s",
            self.config["data_cache_dir"], self.config["results_dir"],
        )

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Shared HTTP transport: both LLM clients reuse one connection pool so
        # the concurrent analyst calls (parallel fan-out) share keep-alive
        # sockets to the gateway instead of each client opening its own
        # connections (a real latency win against a remote gateway).
        self._shared_http_client = httpx.Client(
            timeout=httpx.Timeout(300.0, connect=10.0)
        )
        llm_kwargs["http_client"] = self._shared_http_client

        # Add callbacks to kwargs if provided (passed to LLM constructor)
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
                "Failed to create LLM clients for provider=%s: %s",
                self.config.get("llm_provider"), exc,
            )
            raise

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()
        logger.debug(
            "LLM clients created: deep=%s quick=%s",
            self.config["deep_think_llm"], self.config["quick_think_llm"],
        )

        self.memory_log = TradingMemoryLog(self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
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

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Graph-shape-affecting run choices, kept for the checkpoint signature.
        self.selected_analysts = tuple(selected_analysts)

        # Set up the graph: keep the workflow for recompilation with a checkpointer.
        try:
            self.workflow = self.graph_setup.setup_graph(selected_analysts)
            self.graph = self.workflow.compile()
        except Exception as exc:
            logger.exception("Failed to build/compile the trading graph: %s", exc)
            raise
        self._checkpointer_ctx = None
        logger.info(
            "Graph compiled: nodes=%s", list(getattr(self.graph, "nodes", {}).keys())
        )

    def _get_provider_kwargs(self) -> dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        # Web model profiles carry a per-profile key. Passing it explicitly is
        # safe for concurrent users and avoids mutating process-wide env vars.
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

        # Sampling temperature is cross-provider: forward it whenever set.
        # float() here so a value coming from a TRADINGAGENTS_TEMPERATURE env
        # string ("0.2") works the same as a programmatic float.
        temperature = self.config.get("temperature")
        if temperature is not None and temperature != "":
            kwargs["temperature"] = float(temperature)

        # SDK retry budget is cross-provider. Forward it only when explicitly set
        # so each provider keeps its own default (usually 2) otherwise (#1091).
        max_retries = self.config.get("llm_max_retries")
        if max_retries is not None and max_retries != "":
            kwargs["max_retries"] = _coerce_max_retries(max_retries)

        return kwargs

    def _create_tool_nodes(self) -> dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods.

        Each analyst runs concurrently on its own message channel, so every
        ToolNode is bound to that channel via ``messages_name`` — tool results
        land back in the owning analyst's scratch messages instead of the
        shared history.
        """
        tool_nodes = {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # Technical indicators
                    get_indicators,
                    # Deterministic verification snapshot (bound to the analyst
                    # LLM and required by its prompt; must be executable here or
                    # the call fails and the model reports it "unavailable").
                    get_verified_market_snapshot,
                    # A-share special context (all degrade gracefully)
                    get_lhb_context,
                    get_northbound_flow,
                    get_limit_up_context,
                    get_sector_context,
                ],
                messages_key="market_messages",
            ),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                ],
                messages_key="sentiment_messages",
            ),
            "news": ToolNode(
                [
                    # News and insider information
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
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                    # A-share earnings guidance (业绩预告)
                    get_earnings_forecast,
                ],
                messages_key="fundamentals_messages",
            ),
        }
        for channel, node in tool_nodes.items():
            logger.debug(
                "ToolNode %s ready with %d tools (channel=%s)",
                channel, len(node.tools_by_name), node.messages_name,
            )
        return tool_nodes

    def _resolve_benchmark(self, ticker: str) -> str:
        """Pick the benchmark ticker for alpha calculation against ``ticker``.

        ``config["benchmark_ticker"]`` overrides everything when set; otherwise
        the suffix map matches the ticker's exchange suffix (e.g. ``.T`` for
        Tokyo). US-listed tickers without a dotted suffix fall through to the
        empty-suffix entry (SPY by default). Unrecognised suffixes (including
        US tickers with dots like ``BRK.B``) also fall back to the empty-suffix
        entry, which is the right default because the alpha calculation works
        in USD.
        """
        explicit = self.config.get("benchmark_ticker")
        if explicit:
            logger.debug("Benchmark overridden by config for %s: %s", ticker, explicit)
            return explicit
        benchmark_map = self.config.get("benchmark_map", {})
        ticker_upper = ticker.upper()
        for suffix, benchmark in benchmark_map.items():
            if suffix and ticker_upper.endswith(suffix.upper()):
                logger.debug("Benchmark for %s resolved via suffix %s: %s", ticker, suffix, benchmark)
                return benchmark
        benchmark = benchmark_map.get("", "SPY")
        logger.debug("Benchmark for %s fell back to default: %s", ticker, benchmark)
        return benchmark

    def _fetch_returns(
        self, ticker: str, trade_date: str, holding_days: int = 5,
        benchmark: str = "SPY",
    ) -> tuple[float | None, float | None, int | None]:
        """Fetch raw and alpha return for ticker over holding_days from trade_date.

        ``benchmark`` is the index used as the alpha baseline (resolved by the
        caller via ``_resolve_benchmark``). Returns ``(raw_return, alpha_return,
        actual_holding_days)`` or ``(None, None, None)`` if price data is
        unavailable (too recent, delisted, or network error).

        akshare (Sina) is tried first — Yahoo is IP-blocked on this network, so
        the yfinance path would never resolve and every decision would stay
        "pending" forever. yfinance remains the fallback for exotic symbols.
        """
        from tradingagents.dataflows.akshare_data import get_market_returns

        try:
            resolved = get_market_returns(ticker, trade_date, holding_days, benchmark)
            if resolved != (None, None, None):
                logger.debug(
                    "Realized returns for %s on %s: raw=%s alpha=%s days=%s",
                    ticker, trade_date, *resolved,
                )
                return resolved
            logger.debug(
                "akshare returned no price data for %s on %s (too recent/delisted)",
                ticker, trade_date,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("akshare realized-return lookup failed for %s: %s", ticker, exc)

        # Legacy fallback (Yahoo) — works where Yahoo is reachable.
        from tradingagents.dataflows.symbol_utils import normalize_symbol

        try:
            start = datetime.strptime(trade_date, "%Y-%m-%d")
            end = start + timedelta(days=holding_days + 7)  # buffer for weekends/holidays
            end_str = end.strftime("%Y-%m-%d")

            # Normalize so the realized-return lookup hits the same instrument
            # the analysis priced (e.g. XAUUSD -> GC=F) (#984). The benchmark is
            # already a canonical Yahoo symbol from ``_resolve_benchmark``.
            stock = yf.Ticker(normalize_symbol(ticker)).history(start=trade_date, end=end_str)
            bench = yf.Ticker(benchmark).history(start=trade_date, end=end_str)

            if len(stock) < 2 or len(bench) < 2:
                logger.debug(
                    "yfinance returned insufficient bars for %s/%s on %s (stock=%d bench=%d)",
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
                "yfinance realized returns for %s on %s: raw=%.6f alpha=%.6f days=%d",
                ticker, trade_date, raw, alpha, actual_days,
            )
            return raw, alpha, actual_days
        except Exception as e:
            logger.warning(
                "Could not resolve outcome for %s on %s vs %s (will retry next run): %s",
                ticker, trade_date, benchmark, e,
            )
            return None, None, None

    def _resolve_pending_entries(self, ticker: str) -> None:
        """Resolve pending log entries for ticker at the start of a new run.

        Fetches returns for each same-ticker pending entry, generates reflections,
        then writes all updates in a single atomic batch write to avoid redundant I/O.
        Skips entries whose price data is not yet available (too recent or delisted).

        Trade-off: only same-ticker entries are resolved per run.  Entries for
        other tickers accumulate until that ticker is run again.
        """
        pending = [e for e in self.memory_log.get_pending_entries() if e["ticker"] == ticker]
        if not pending:
            return
        logger.info("Resolving %d pending entry/entries for %s", len(pending), ticker)

        benchmark = self._resolve_benchmark(ticker)
        updates = []
        for entry in pending:
            raw, alpha, days = self._fetch_returns(
                ticker, entry["date"], benchmark=benchmark,
            )
            if raw is None:
                logger.debug(
                    "Pending entry %s on %s still lacks price data; will retry next run",
                    ticker, entry["date"],
                )
                continue  # price not available yet — try again next run
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
                "Writing outcomes for %d resolved entry/entries of %s", len(updates), ticker
            )
            self.memory_log.batch_update_with_outcomes(updates)

    def resolve_instrument_context(self, ticker: str, asset_type: str = "stock") -> str:
        """Resolve ticker identity once and return the full instrument context.

        Deterministic yfinance lookup (cached, fail-open) injected into a
        context string so every agent anchors to the real company instead of
        hallucinating one from the price chart (#814). Both the propagate()
        path and the CLI call this so the resolved identity reaches the whole
        graph regardless of entry point.
        """
        identity = resolve_instrument_identity(ticker)
        logger.debug(
            "Instrument identity resolved for %s (asset_type=%s): %s",
            ticker, asset_type, identity,
        )
        return build_instrument_context(ticker, asset_type, identity)

    def _run_signature(self, asset_type: str) -> str:
        """Graph-shape inputs that must invalidate a checkpoint if changed.

        Keyed into the checkpoint thread ID so a resume under a different analyst
        selection, debate/risk depth, or asset mode starts fresh instead of
        silently continuing the previous graph (#1089).
        """
        return "|".join([
            "layout=parallel-v1",
            "analysts=" + ",".join(self.selected_analysts),
            f"debate={self.config['max_debate_rounds']}",
            f"risk={self.config['max_risk_discuss_rounds']}",
            f"asset={asset_type}",
        ])

    def propagate(self, company_name, trade_date, asset_type: str = "stock"):
        """Run the trading agents graph for a company on a specific date.

        ``asset_type`` selects between the stock pipeline (default) and the
        crypto pipeline (``"crypto"``) shipped in #567 — the CLI auto-detects
        from the ticker; programmatic callers pass it explicitly. When
        ``checkpoint_enabled`` is set in config, the graph is recompiled with
        a per-ticker SqliteSaver so a crashed run can resume from the last
        successful node on a subsequent invocation with the same ticker+date.
        """
        self.ticker = company_name
        logger.info(
            "propagate() called: ticker=%s trade_date=%s asset_type=%s",
            company_name, trade_date, asset_type,
        )

        # Resolve any pending memory-log entries for this ticker before the pipeline runs.
        self._resolve_pending_entries(company_name)

        # Recompile with a checkpointer if the user opted in.
        if self.config.get("checkpoint_enabled"):
            self._checkpointer_ctx = get_checkpointer(
                self.config["data_cache_dir"], company_name
            )
            saver = self._checkpointer_ctx.__enter__()
            self.graph = self.workflow.compile(checkpointer=saver)

            step = checkpoint_step(
                self.config["data_cache_dir"], company_name, str(trade_date),
                self._run_signature(asset_type),
            )
            if step is not None:
                logger.info(
                    "Resuming from step %d for %s on %s", step, company_name, trade_date
                )
            else:
                logger.info("Starting fresh for %s on %s", company_name, trade_date)

        try:
            logger.info(
                "Executing graph pipeline for %s on %s (asset_type=%s)",
                company_name, trade_date, asset_type,
            )
            return self._run_graph(company_name, trade_date, asset_type=asset_type)
        except Exception as exc:
            logger.exception(
                "Graph pipeline failed for %s on %s: %s", company_name, trade_date, exc
            )
            raise
        finally:
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()

    def save_reports(self, final_state, ticker, save_path=None) -> Path:
        """Write the markdown report tree for a completed run, like the CLI does.

        Programmatic callers get the same on-disk reports the CLI produces. Pass
        an explicit ``save_path`` or let it default under ``results_dir``.
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
        """Execute the graph and write the resulting state to disk and memory log."""
        # Initialize state — inject memory log context for PM and the
        # deterministically resolved instrument identity for all agents.
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
            "Initial state prepared for %s on %s; past_context=%s",
            company_name, trade_date, bool(past_context),
        )

        # Inject thread_id so same ticker+date+graph-shape resumes; a different
        # date or graph shape starts fresh (#1089).
        if self.config.get("checkpoint_enabled"):
            tid = thread_id(company_name, str(trade_date), self._run_signature(asset_type))
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid
            logger.debug("Checkpoint thread_id=%s", tid)

        try:
            if self.debug:
                trace = []
                last_printed = None
                for chunk in self.graph.stream(init_agent_state, **args):
                    if chunk["messages"]:
                        msg = chunk["messages"][-1]
                        # Nodes after the trader don't append to messages, so the
                        # same trailing message repeats across chunks. Print it only
                        # when it changes (#1027); the trace/state merge is unchanged.
                        signature = (type(msg).__name__, getattr(msg, "content", None))
                        if signature != last_printed:
                            msg.pretty_print()
                            last_printed = signature
                        trace.append(chunk)
                # Streamed chunks are per-node deltas. Merge them so the returned
                # state matches what graph.invoke() yields in the non-debug path.
                final_state = {}
                for chunk in trace:
                    final_state.update(chunk)
                logger.debug("Debug stream executed with %d chunks", len(trace))
            else:
                final_state = self.graph.invoke(init_agent_state, **args)
        except Exception as exc:
            logger.exception(
                "Graph execution failed for %s on %s: %s", company_name, trade_date, exc
            )
            raise
        logger.info("Graph execution finished for %s on %s", company_name, trade_date)

        # Store current state for reflection.
        self.curr_state = final_state

        # Log state to disk.
        self._log_state(trade_date, final_state)

        # Store decision for deferred reflection on the next same-ticker run.
        decision = final_state.get("final_trade_decision")
        logger.info(
            "Storing decision for %s on %s: %s", company_name, trade_date, decision
        )
        self.memory_log.store_decision(
            ticker=company_name,
            trade_date=trade_date,
            final_trade_decision=final_state["final_trade_decision"],
        )

        # Clear checkpoint on successful completion to avoid stale state.
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config["data_cache_dir"], company_name, str(trade_date),
                self._run_signature(asset_type),
            )
            logger.debug("Checkpoint cleared for %s on %s", company_name, trade_date)

        signal = self.process_signal(final_state["final_trade_decision"])
        logger.info(
            "Final decision for %s on %s: %s", company_name, trade_date, signal
        )
        return final_state, signal

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
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

        # Save to file. Reject ticker values that would escape the
        # results directory when joined as a path component.
        safe_ticker = safe_ticker_component(self.ticker)
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(self.log_states_dict[str(trade_date)], f, indent=4)
            logger.debug("State snapshot written to %s", log_path)
        except Exception as exc:
            logger.error("Failed to write state snapshot %s: %s", log_path, exc)

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        logger.debug("Processing full signal: %s", full_signal)
        return self.signal_processor.process_signal(full_signal)
