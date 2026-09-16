import logging

from .alpha_vantage_common import AlphaVantageNotConfiguredError, _make_api_request

logger = logging.getLogger(__name__)


def get_indicator(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int,
    interval: str = "daily",
    time_period: int = 14,
    series_type: str = "close"
) -> str:
    """
    返回一段时间内的 Alpha Vantage 技术指标值。

    Args:
        symbol：公司股票代码。
        indicator：需要分析并报告的技术指标。
        curr_date：当前交易日期，格式为 YYYY-mm-dd。
        look_back_days：回溯天数。
        interval：时间间隔（daily、weekly、monthly）。
        time_period：计算所需的数据点数量。
        series_type：价格类型（close、open、high、low）。

    Returns:
        包含指标值和说明的字符串。
    """
    logger.debug(
        "get_indicator called for %s indicator=%s curr_date=%s look_back_days=%d interval=%s time_period=%d series_type=%s",
        symbol, indicator, curr_date, look_back_days, interval, time_period, series_type,
    )
    from datetime import datetime

    from dateutil.relativedelta import relativedelta

    supported_indicators = {
        "close_50_sma": ("50 SMA", "close"),
        "close_200_sma": ("200 SMA", "close"),
        "close_10_ema": ("10 EMA", "close"),
        "macd": ("MACD", "close"),
        "macds": ("MACD Signal", "close"),
        "macdh": ("MACD Histogram", "close"),
        "rsi": ("RSI", "close"),
        "boll": ("Bollinger Middle", "close"),
        "boll_ub": ("Bollinger Upper Band", "close"),
        "boll_lb": ("Bollinger Lower Band", "close"),
        "atr": ("ATR", None),
        "vwma": ("VWMA", "close")
    }

    indicator_descriptions = {
        "close_50_sma": "50 SMA：中期趋势指标。用途：识别趋势方向并作为动态支撑/阻力。提示：具有滞后性，应结合更快的指标及时捕捉信号。",
        "close_200_sma": "200 SMA：长期趋势基准。用途：确认整体市场趋势并识别金叉/死叉形态。提示：反应较慢，更适合战略趋势确认，不适合频繁入场。",
        "close_10_ema": "10 EMA：响应灵敏的短期均线。用途：捕捉动量快速变化和潜在入场点。提示：震荡市场中噪声较多，应结合长期均线过滤假信号。",
        "macd": "MACD：通过 EMA 差值计算动量。用途：关注交叉和背离，识别趋势变化。提示：低波动或横盘市场中应结合其他指标确认。",
        "macds": "MACD 信号线：对 MACD 线进行 EMA 平滑。用途：与 MACD 线的交叉可触发交易。提示：应纳入更完整的策略，避免假信号。",
        "macdh": "MACD 柱：显示 MACD 线与信号线之间的差值。用途：观察动量强弱并尽早发现背离。提示：可能波动较大，快速市场中应增加过滤条件。",
        "rsi": "RSI：衡量动量并提示超买/超卖。用途：使用 70/30 阈值并关注背离以识别反转。提示：强趋势中 RSI 可能长期处于极值，应结合趋势分析。",
        "boll": "布林中轨：作为布林带基础的 20 SMA。用途：充当价格运动的动态基准。提示：结合上下轨识别突破或反转。",
        "boll_ub": "布林上轨：通常位于中轨上方 2 个标准差处。用途：提示潜在超买和突破区域。提示：应结合其他工具确认，强趋势中价格可能沿上轨运行。",
        "boll_lb": "布林下轨：通常位于中轨下方 2 个标准差处。用途：提示潜在超卖。提示：增加其他分析以避免错误的反转信号。",
        "atr": "ATR：通过平均真实波幅衡量波动率。用途：设置止损并根据当前波动率调整仓位。提示：这是反应型指标，应纳入更完整的风险管理策略。",
        "vwma": "VWMA：按成交量加权的移动平均线。用途：结合价格走势和成交量确认趋势。提示：成交量尖峰可能造成偏差，应结合其他成交量分析。"
    }

    if indicator not in supported_indicators:
        logger.warning("请求的 Alpha Vantage 指标 %s 不支持：%s", indicator, symbol)
        raise ValueError(
            f"不支持指标 {indicator}。请选择：{list(supported_indicators.keys())}"
        )

    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_date_dt - relativedelta(days=look_back_days)

    # 获取整个时间段的数据，避免逐次单独调用。
    _, required_series_type = supported_indicators[indicator]

    # 使用传入的 series_type，或回退到指标要求的类型。
    if required_series_type:
        series_type = required_series_type

    try:
        # 获取时间段内的指标数据。
        if indicator == "close_50_sma":
            data = _make_api_request("SMA", {
                "symbol": symbol,
                "interval": interval,
                "time_period": "50",
                "series_type": series_type,
                "datatype": "csv"
            })
        elif indicator == "close_200_sma":
            data = _make_api_request("SMA", {
                "symbol": symbol,
                "interval": interval,
                "time_period": "200",
                "series_type": series_type,
                "datatype": "csv"
            })
        elif indicator == "close_10_ema":
            data = _make_api_request("EMA", {
                "symbol": symbol,
                "interval": interval,
                "time_period": "10",
                "series_type": series_type,
                "datatype": "csv"
            })
        elif indicator == "macd" or indicator == "macds" or indicator == "macdh":
            data = _make_api_request("MACD", {
                "symbol": symbol,
                "interval": interval,
                "series_type": series_type,
                "datatype": "csv"
            })
        elif indicator == "rsi":
            data = _make_api_request("RSI", {
                "symbol": symbol,
                "interval": interval,
                "time_period": str(time_period),
                "series_type": series_type,
                "datatype": "csv"
            })
        elif indicator in ["boll", "boll_ub", "boll_lb"]:
            data = _make_api_request("BBANDS", {
                "symbol": symbol,
                "interval": interval,
                "time_period": "20",
                "series_type": series_type,
                "datatype": "csv"
            })
        elif indicator == "atr":
            data = _make_api_request("ATR", {
                "symbol": symbol,
                "interval": interval,
                "time_period": str(time_period),
                "datatype": "csv"
            })
        elif indicator == "vwma":
            # Alpha Vantage 没有直接的 VWMA 接口，因此返回说明性信息。
            # 实际实现需要基于 OHLCV 数据计算 VWMA。
            logger.debug("Alpha Vantage 没有 %s 的原生 VWMA 接口，返回说明信息", symbol)
            return f"## {symbol} 的 VWMA（成交量加权移动平均线）：\n\nVWMA 计算需要 OHLCV 数据，Alpha Vantage API 不直接提供。\n该指标需要使用原始股票数据，通过成交量加权价格计算。\n\n{indicator_descriptions.get('vwma', '暂无说明。')}"
        else:
            logger.warning("Alpha Vantage 尚未实现 %s 指标（代码 %s）", indicator, symbol)
            return f"错误：指标 {indicator} 尚未实现。"

        # 解析 CSV 数据并提取日期范围内的值。
        lines = data.strip().split('\n')
        if len(lines) < 2:
            logger.warning("Alpha Vantage 未返回 %s 的指标数据行（代码 %s）", indicator, symbol)
            return f"错误：指标 {indicator} 未返回数据。"

        # 解析表头和数据。
        header = [col.strip() for col in lines[0].split(',')]
        try:
            date_col_idx = header.index('time')
        except ValueError:
            logger.warning("Alpha Vantage %s 响应中找不到 time 列（%s）：%s", indicator, symbol, header)
            return f"错误：指标 {indicator} 的数据中找不到 time 列。可用列：{header}"

        # 将内部指标名称映射为 Alpha Vantage 预期的 CSV 列名。
        col_name_map = {
            "macd": "MACD", "macds": "MACD_Signal", "macdh": "MACD_Hist",
            "boll": "Real Middle Band", "boll_ub": "Real Upper Band", "boll_lb": "Real Lower Band",
            "rsi": "RSI", "atr": "ATR", "close_10_ema": "EMA",
            "close_50_sma": "SMA", "close_200_sma": "SMA"
        }

        target_col_name = col_name_map.get(indicator)

        if not target_col_name:
            # 没有特定映射时默认使用第二列。
            value_col_idx = 1
        else:
            try:
                value_col_idx = header.index(target_col_name)
            except ValueError:
                logger.warning("Alpha Vantage %s 响应中找不到列 %s（%s）：%s", indicator, target_col_name, symbol, header)
                return f"错误：指标 {indicator} 找不到列 {target_col_name}。可用列：{header}"

        result_data = []
        for line in lines[1:]:
            if not line.strip():
                continue
            values = line.split(',')
            if len(values) > value_col_idx:
                try:
                    date_str = values[date_col_idx].strip()
                    # 解析日期。
                    date_dt = datetime.strptime(date_str, "%Y-%m-%d")

                    # 检查日期是否在范围内。
                    if before <= date_dt <= curr_date_dt:
                        value = values[value_col_idx].strip()
                        result_data.append((date_dt, value))
                except (ValueError, IndexError):
                    continue

        # 按日期排序并格式化输出。
        result_data.sort(key=lambda x: x[0])

        ind_string = ""
        for date_dt, value in result_data:
            ind_string += f"{date_dt.strftime('%Y-%m-%d')}: {value}\n"

        if not ind_string:
            logger.debug("代码 %s 在 %s..%s 范围内没有 %s 指标值", symbol, before.strftime("%Y-%m-%d"), curr_date, indicator)
            ind_string = "指定日期范围内没有可用数据。\n"

        logger.debug("Alpha Vantage 为 %s 返回 %d 个 %s 指标值", symbol, len(result_data), indicator)
        result_str = (
            f"## {indicator.upper()} values from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
            + ind_string
            + "\n\n"
            + indicator_descriptions.get(indicator, "No description available.")
        )

        return result_str

    except AlphaVantageNotConfiguredError:
# 供应商不可用（没有 API 密钥）。让异常继续向上抛出，以便路由器回退或
# 发出“无数据”哨兵值，而不是将其作为看似成功的错误字符串返回。
        raise
    except Exception as e:
        logger.warning("获取代码 %s 的 Alpha Vantage 指标 %s 失败：%s", symbol, indicator, e)
        return f"Error retrieving {indicator} data: {str(e)}"
