import json
import logging

from .alpha_vantage_common import _make_api_request

logger = logging.getLogger(__name__)


def _filter_reports_by_date(result, curr_date: str):
    """Drop annual/quarterly reports dated after curr_date to prevent look-ahead.

    ``_make_api_request`` returns the fundamentals payload as a JSON string, so
    parse, filter, and re-serialize. A non-JSON body or an unset ``curr_date`` is
    returned unchanged.
    """
    logger.debug("_filter_reports_by_date called for curr_date=%s", curr_date)
    if not curr_date or not isinstance(result, str):
        return result
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return result
    if not isinstance(payload, dict):
        return result
    for key in ("annualReports", "quarterlyReports"):
        if isinstance(payload.get(key), list):
            payload[key] = [
                r for r in payload[key]
                if r.get("fiscalDateEnding", "") <= curr_date
            ]
    return json.dumps(payload)


def get_fundamentals(ticker: str, curr_date: str = None) -> str:
    """
    Retrieve comprehensive fundamental data for a given ticker symbol using Alpha Vantage.

    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Current date you are trading at, yyyy-mm-dd (not used for Alpha Vantage)

    Returns:
        str: Company overview data including financial ratios and key metrics
    """
    logger.debug("get_fundamentals called for %s curr_date=%s", ticker, curr_date)
    params = {
        "symbol": ticker,
    }

    result = _make_api_request("OVERVIEW", params)
    logger.debug("alpha vantage overview returned %d bytes for %s", len(result), ticker)
    return result


def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """Retrieve balance sheet data for a given ticker symbol using Alpha Vantage."""
    logger.debug("get_balance_sheet called for %s freq=%s curr_date=%s", ticker, freq, curr_date)
    result = _make_api_request("BALANCE_SHEET", {"symbol": ticker})
    logger.debug("alpha vantage balance sheet returned %d bytes for %s", len(result), ticker)
    return _filter_reports_by_date(result, curr_date)


def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """Retrieve cash flow statement data for a given ticker symbol using Alpha Vantage."""
    logger.debug("get_cashflow called for %s freq=%s curr_date=%s", ticker, freq, curr_date)
    result = _make_api_request("CASH_FLOW", {"symbol": ticker})
    logger.debug("alpha vantage cash flow returned %d bytes for %s", len(result), ticker)
    return _filter_reports_by_date(result, curr_date)


def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """Retrieve income statement data for a given ticker symbol using Alpha Vantage."""
    logger.debug("get_income_statement called for %s freq=%s curr_date=%s", ticker, freq, curr_date)
    result = _make_api_request("INCOME_STATEMENT", {"symbol": ticker})
    logger.debug("alpha vantage income statement returned %d bytes for %s", len(result), ticker)
    return _filter_reports_by_date(result, curr_date)

