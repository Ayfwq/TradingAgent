import json
import logging

from .alpha_vantage_common import _make_api_request

logger = logging.getLogger(__name__)


def _filter_reports_by_date(result, curr_date: str):
    """删除 curr_date 之后的年度/季度报告，防止前视偏差。

    ``_make_api_request`` 返回 JSON 字符串形式的基本面数据，因此需要解析、过滤
    并重新序列化。非 JSON 响应体或未设置 ``curr_date`` 时原样返回。
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
    使用 Alpha Vantage 获取指定股票代码的完整基本面数据。

    Args:
        ticker（str）：公司股票代码。
        curr_date（str）：交易当前日期，格式为 yyyy-mm-dd（Alpha Vantage 不使用）。

    Returns:
        str：包含财务比率和关键指标的公司概览数据。
    """
    logger.debug("已调用 get_fundamentals：%s，curr_date=%s", ticker, curr_date)
    params = {
        "symbol": ticker,
    }

    result = _make_api_request("OVERVIEW", params)
    logger.debug("Alpha Vantage 为 %s 返回 %d 字节的概览数据", ticker, len(result))
    return result


def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """使用 Alpha Vantage 获取指定股票代码的资产负债表数据。"""
    logger.debug("已调用 get_balance_sheet：%s，freq=%s，curr_date=%s", ticker, freq, curr_date)
    result = _make_api_request("BALANCE_SHEET", {"symbol": ticker})
    logger.debug("Alpha Vantage 为 %s 返回 %d 字节的资产负债表数据", ticker, len(result))
    return _filter_reports_by_date(result, curr_date)


def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """使用 Alpha Vantage 获取指定股票代码的现金流量表数据。"""
    logger.debug("已调用 get_cashflow：%s，freq=%s，curr_date=%s", ticker, freq, curr_date)
    result = _make_api_request("CASH_FLOW", {"symbol": ticker})
    logger.debug("Alpha Vantage 为 %s 返回 %d 字节的现金流量表数据", ticker, len(result))
    return _filter_reports_by_date(result, curr_date)


def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: str = None):
    """使用 Alpha Vantage 获取指定股票代码的利润表数据。"""
    logger.debug("已调用 get_income_statement：%s，freq=%s，curr_date=%s", ticker, freq, curr_date)
    result = _make_api_request("INCOME_STATEMENT", {"symbol": ticker})
    logger.debug("Alpha Vantage 为 %s 返回 %d 字节的利润表数据", ticker, len(result))
    return _filter_reports_by_date(result, curr_date)

