"""A-share special-context tools (龙虎榜 / 北向资金 / 涨停池 / 板块 / 业绩预告).

Wrappers around the akshare vendor functions, following the same
``route_to_vendor`` pattern as the other data tools so agent tool-calling
sees a uniform interface. All of them degrade to a short string (never a
crash): absence of a record is a real answer, network failure is
DATA_UNAVAILABLE.
"""

from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_lhb_context(
    ticker: Annotated[str, "ticker symbol of the company, e.g. 600519.SS"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days back to search for LHB appearances"] = 10,
) -> str:
    """A-share Dragon-Tiger list (龙虎榜) context for the ticker: abnormal-move
    institutional/seat activity (net buy, reason, post-listing 1/2/5-day returns).
    Only call for A-share tickers; absence from the list is normal for most stocks.
    """
    return route_to_vendor("get_lhb_context", ticker, curr_date, look_back_days)


@tool
def get_northbound_flow(
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days back of northbound history to show"] = 10,
) -> str:
    """A-share northbound (北向资金) flow: HK->A net buying — the closest A-share
    analogue to institutional money flow. Recent daily net buys + latest-day
    summary. Market-wide, not per-ticker.
    """
    return route_to_vendor("get_northbound_flow", curr_date, look_back_days)


@tool
def get_limit_up_context(
    ticker: Annotated[str, "ticker symbol of the company, e.g. 600519.SS"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
) -> str:
    """A-share limit-up board (涨停池) context: whether the ticker is limit-up
    today (连板数/封板资金/所属行业) and the breadth of today's limit-up board
    (count, top sectors, highest streak) as a market-sentiment signal.
    Only call for A-share tickers.
    """
    return route_to_vendor("get_limit_up_context", ticker, curr_date)


@tool
def get_sector_context(
    ticker: Annotated[str, "ticker symbol of the company, e.g. 600519.SS"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
) -> str:
    """A-share sector breadth: today's best/worst Sina industry sectors with
    their leader stocks. Market-wide context; also flags when the ticker is a
    sector leader today. Only call for A-share tickers.
    """
    return route_to_vendor("get_sector_context", ticker, curr_date)


@tool
def get_earnings_forecast(
    ticker: Annotated[str, "ticker symbol of the company, e.g. 600519.SS"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
) -> str:
    """A-share earnings guidance (业绩预告): the company's own forecast for the
    most recent reporting window (预告类型/业绩变动/公告日期) — a leading signal
    that arrives before the actual financial statements. Only call for A-share
    tickers; guidance is optional in A-shares, absence is normal.
    """
    return route_to_vendor("get_earnings_forecast", ticker, curr_date)
