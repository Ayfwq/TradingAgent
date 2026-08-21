import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.market_data_validator import build_verified_market_snapshot

logger = logging.getLogger(__name__)


@tool
def get_verified_market_snapshot(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "the current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[
        int, "number of recent trading rows to include for sanity-checking"
    ] = 30,
) -> str:
    """Deterministic verification snapshot for exact market-data claims.

    Returns the latest OHLCV row on or before curr_date, common technical
    indicators, and recent closes. Call this before making exact claims about
    price levels, Bollinger bands, RSI, MACD, moving averages, support /
    resistance, or historical comparisons, and treat it as the source of truth.
    """
    logger.debug(
        "get_verified_market_snapshot called: symbol=%s, curr_date=%s, look_back_days=%s",
        symbol, curr_date, look_back_days,
    )
    try:
        result = build_verified_market_snapshot(symbol, curr_date, look_back_days)
        logger.debug(
            "get_verified_market_snapshot returned %d chars for %s",
            len(result), symbol,
        )
        return result
    except Exception:
        logger.exception(
            "get_verified_market_snapshot failed: symbol=%s, curr_date=%s, look_back_days=%s",
            symbol, curr_date, look_back_days,
        )
        raise
