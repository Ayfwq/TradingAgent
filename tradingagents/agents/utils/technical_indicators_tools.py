import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)


@tool
def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"] = 30,
) -> str:
    """
    Retrieve a single technical indicator for a given ticker symbol.
    Uses the configured technical_indicators vendor.
    Args:
        symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
        indicator (str): A single technical indicator name, e.g. 'rsi', 'macd'. Call this tool once per indicator.
        curr_date (str): The current trading date you are trading on, YYYY-mm-dd
        look_back_days (int): How many days to look back, default is 30
    Returns:
        str: A formatted dataframe containing the technical indicators for the specified ticker symbol and indicator.
    """
    # LLMs sometimes pass multiple indicators as a comma-separated string;
    # split and process each individually.
    logger.debug(
        "get_indicators called: symbol=%s, indicator=%s, curr_date=%s, look_back_days=%s",
        symbol, indicator, curr_date, look_back_days,
    )
    indicators = [i.strip().lower() for i in indicator.split(",") if i.strip()]
    results = []
    for ind in indicators:
        try:
            result = route_to_vendor("get_indicators", symbol, ind, curr_date, look_back_days)
            logger.debug("get_indicators returned %d chars for %s / %s", len(result), symbol, ind)
            results.append(result)
        except ValueError as e:
            logger.exception("get_indicators failed for %s / %s", symbol, ind)
            results.append(str(e))
    logger.debug("get_indicators aggregated %d result blocks for %s", len(results), symbol)
    return "\n\n".join(results)
