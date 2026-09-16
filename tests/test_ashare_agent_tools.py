"""Regression coverage for market-aware analyst tool binding."""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from tradingagents.agents.analysts.fundamentals_analyst import (
    create_fundamentals_analyst,
)
from tradingagents.agents.analysts.market_analyst import create_market_analyst
from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.utils.agent_utils import is_ashare_ticker
from tradingagents.graph.trading_graph import TradingAgentsGraph


class _CapturingLLM:
    def __init__(self):
        self.tool_names = set()

    def bind_tools(self, tools, **kwargs):
        self.tool_names = {tool.name for tool in tools}
        return RunnableLambda(lambda _: AIMessage(content="report", tool_calls=[]))


def _state(ticker="600519.SS", asset_type="stock"):
    return {
        "company_of_interest": ticker,
        "trade_date": "2026-09-15",
        "asset_type": asset_type,
        "instrument_context": f"The instrument to analyze is `{ticker}`.",
        "messages": [],
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "ticker, expected",
    [
        ("600519.SS", True),
        ("000001.SZ", True),
        ("430047.BJ", True),
        ("688981", True),
        ("AAPL", False),
        ("0700.HK", False),
        ("BTC-USD", False),
    ],
)
def test_is_ashare_ticker(ticker, expected):
    assert is_ashare_ticker(ticker) is expected


@pytest.mark.unit
def test_market_analyst_gets_ashare_context_tools_only_for_ashares():
    ashare_llm = _CapturingLLM()
    create_market_analyst(ashare_llm)(_state())
    assert {
        "get_lhb_context",
        "get_northbound_flow",
        "get_limit_up_context",
        "get_sector_context",
    } <= ashare_llm.tool_names

    us_llm = _CapturingLLM()
    create_market_analyst(us_llm)(_state("AAPL"))
    assert not {
        "get_lhb_context",
        "get_northbound_flow",
        "get_limit_up_context",
        "get_sector_context",
    } & us_llm.tool_names


@pytest.mark.unit
def test_fundamentals_analyst_gets_earnings_forecast_only_for_ashares():
    ashare_llm = _CapturingLLM()
    create_fundamentals_analyst(ashare_llm)(_state())
    assert "get_earnings_forecast" in ashare_llm.tool_names

    us_llm = _CapturingLLM()
    create_fundamentals_analyst(us_llm)(_state("AAPL"))
    assert "get_earnings_forecast" not in us_llm.tool_names


@pytest.mark.unit
def test_news_analyst_gets_insider_tool_for_stocks_not_crypto():
    stock_llm = _CapturingLLM()
    create_news_analyst(stock_llm)(_state())
    assert "get_insider_transactions" in stock_llm.tool_names

    crypto_llm = _CapturingLLM()
    create_news_analyst(crypto_llm)(_state("BTC-USD", "crypto"))
    assert "get_insider_transactions" not in crypto_llm.tool_names


@pytest.mark.unit
def test_every_bound_ashare_tool_has_a_matching_executor():
    nodes = TradingAgentsGraph._create_tool_nodes(None)
    cases = (
        ("market", create_market_analyst),
        ("news", create_news_analyst),
        ("fundamentals", create_fundamentals_analyst),
    )
    for channel, factory in cases:
        llm = _CapturingLLM()
        factory(llm)(_state())
        node = nodes[channel]
        executable = getattr(
            node, "tools_by_name", getattr(node, "_tools_by_name", {})
        )
        assert llm.tool_names <= set(executable)
