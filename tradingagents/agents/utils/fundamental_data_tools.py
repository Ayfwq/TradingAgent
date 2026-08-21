import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)


@tool
def get_fundamentals(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """
    Retrieve comprehensive fundamental data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing comprehensive fundamental data
    """
    logger.debug("get_fundamentals called: ticker=%s, curr_date=%s", ticker, curr_date)
    try:
        result = route_to_vendor("get_fundamentals", ticker, curr_date)
        logger.debug("get_fundamentals returned %d chars for %s", len(result), ticker)
        return result
    except Exception:
        logger.exception("get_fundamentals failed: ticker=%s, curr_date=%s", ticker, curr_date)
        raise


@tool
def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve balance sheet data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing balance sheet data
    """
    logger.debug(
        "get_balance_sheet called: ticker=%s, freq=%s, curr_date=%s",
        ticker, freq, curr_date,
    )
    try:
        result = route_to_vendor("get_balance_sheet", ticker, freq, curr_date)
        logger.debug("get_balance_sheet returned %d chars for %s", len(result), ticker)
        return result
    except Exception:
        logger.exception(
            "get_balance_sheet failed: ticker=%s, freq=%s, curr_date=%s",
            ticker, freq, curr_date,
        )
        raise


@tool
def get_cashflow(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve cash flow statement data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing cash flow statement data
    """
    logger.debug(
        "get_cashflow called: ticker=%s, freq=%s, curr_date=%s",
        ticker, freq, curr_date,
    )
    try:
        result = route_to_vendor("get_cashflow", ticker, freq, curr_date)
        logger.debug("get_cashflow returned %d chars for %s", len(result), ticker)
        return result
    except Exception:
        logger.exception(
            "get_cashflow failed: ticker=%s, freq=%s, curr_date=%s",
            ticker, freq, curr_date,
        )
        raise


@tool
def get_income_statement(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve income statement data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing income statement data
    """
    logger.debug(
        "get_income_statement called: ticker=%s, freq=%s, curr_date=%s",
        ticker, freq, curr_date,
    )
    try:
        result = route_to_vendor("get_income_statement", ticker, freq, curr_date)
        logger.debug("get_income_statement returned %d chars for %s", len(result), ticker)
        return result
    except Exception:
        logger.exception(
            "get_income_statement failed: ticker=%s, freq=%s, curr_date=%s",
            ticker, freq, curr_date,
        )
        raise
