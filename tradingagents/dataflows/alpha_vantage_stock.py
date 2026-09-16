import logging
from datetime import datetime

from .alpha_vantage_common import _filter_csv_by_date_range, _make_api_request

logger = logging.getLogger(__name__)


def get_stock(
    symbol: str,
    start_date: str,
    end_date: str
) -> str:
    """
    返回指定日期范围内的原始日 OHLCV、复权收盘价以及历史拆股/分红事件。

    Args:
        symbol：股票名称，例如 symbol=IBM。
        start_date：yyyy-mm-dd 格式的开始日期。
        end_date：yyyy-mm-dd 格式的结束日期。

    Returns:
        包含指定日期范围内日复权时间序列数据的 CSV 字符串。
    """
    logger.debug("已调用 get_stock：%s，范围 %s..%s", symbol, start_date, end_date)
    # 解析日期以确定范围。
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    today = datetime.now()

    # 根据请求范围是否在最近 100 天内选择 outputsize。
    # Compact 只返回最近 100 个数据点，因此需要检查 start_date 是否足够新。
    days_from_today_to_start = (today - start_dt).days
    outputsize = "compact" if days_from_today_to_start < 100 else "full"

    params = {
        "symbol": symbol,
        "outputsize": outputsize,
        "datatype": "csv",
    }

    response = _make_api_request("TIME_SERIES_DAILY_ADJUSTED", params)

    filtered = _filter_csv_by_date_range(response, start_date, end_date)
    logger.debug("Alpha Vantage 为 %s 返回 %d 字节的日线数据（%s..%s）", symbol, len(filtered), start_date, end_date)
    return filtered
