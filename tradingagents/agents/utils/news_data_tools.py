import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)


@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    logger.debug(
        "get_news called: ticker=%s, start_date=%s, end_date=%s",
        ticker, start_date, end_date,
    )
    try:
        result = route_to_vendor("get_news", ticker, start_date, end_date)
        logger.debug("get_news returned %d chars for %s", len(result), ticker)
        return result
    except Exception:
        logger.exception(
            "get_news failed: ticker=%s, start_date=%s, end_date=%s",
            ticker, start_date, end_date,
        )
        raise

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int | None, "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[int | None, "Max articles to return; omit to use the configured default"] = None,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor. Defaults for look_back_days and
    limit come from DEFAULT_CONFIG (global_news_lookback_days,
    global_news_article_limit); pass explicit values to override.

    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back; omit to inherit config
        limit (int): Maximum number of articles to return; omit to inherit config

    Returns:
        str: A formatted string containing global news data
    """
    logger.debug(
        "get_global_news called: curr_date=%s, look_back_days=%s, limit=%s",
        curr_date, look_back_days, limit,
    )
    try:
        result = route_to_vendor("get_global_news", curr_date, look_back_days, limit)
        logger.debug("get_global_news returned %d chars", len(result))
        return result
    except Exception:
        logger.exception(
            "get_global_news failed: curr_date=%s, look_back_days=%s, limit=%s",
            curr_date, look_back_days, limit,
        )
        raise

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    logger.debug("get_insider_transactions called: ticker=%s", ticker)
    try:
        result = route_to_vendor("get_insider_transactions", ticker)
        logger.debug("get_insider_transactions returned %d chars for %s", len(result), ticker)
        return result
    except Exception:
        logger.exception("get_insider_transactions failed: ticker=%s", ticker)
        raise
