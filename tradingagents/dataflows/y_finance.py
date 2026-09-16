import logging
from datetime import datetime
from typing import Annotated

import pandas as pd
import yfinance as yf
from dateutil.relativedelta import relativedelta

from .stockstats_utils import (
    StockstatsUtils,
    _assert_ohlcv_not_stale,
    filter_financials_by_date,
    load_ohlcv,
    yf_retry,
)
from .symbol_utils import NoMarketDataError, normalize_symbol

logger = logging.getLogger(__name__)


def get_YFin_data_online(
    symbol: Annotated[str, "公司股票代码"],
    start_date: Annotated[str, "开始日期，格式为 yyyy-mm-dd"],
    end_date: Annotated[str, "结束日期，格式为 yyyy-mm-dd"],
):

    logger.debug("调用 get_YFin_data_online：%s（%s 至 %s）", symbol, start_date, end_date)
    datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # 将经纪商/外汇代码转换为 Yahoo 规范（XAUUSD+ -> GC=F）。
    canonical = normalize_symbol(symbol)
    ticker = yf.Ticker(canonical)

    # yfinance 将 ``end`` 视为不包含结束日，因此会丢弃请求的 end_date 行
    #（如果结束日是今天也会丢弃当天）。多请求一天，确保范围真正包含结束日（#986/#987）。
    end_inclusive = (end_dt + relativedelta(days=1)).strftime("%Y-%m-%d")
    data = yf_retry(lambda: ticker.history(start=start_date, end=end_inclusive))

    # 空结果表示代码未知或已退市。抛出类型化异常而不是返回散文式文本，路由层
    # 会将其转换为统一明确的“无数据”信号，避免 Agent 虚构价格。
    if data.empty:
        logger.warning(
            "yfinance 在 %s（规范代码 %s）的 %s 至 %s 区间没有返回数据行",
            symbol, canonical, start_date, end_date,
        )
        raise NoMarketDataError(
            symbol, canonical, f"{start_date} 至 {end_date} 之间没有数据行"
        )

    # 删除索引中的时区信息，使输出更简洁。
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)

    # 在格式化报告前拒绝过期数据帧（例如一年前的残缺响应）。这会抛出
    # NoMarketDataError，路由层将其转换为明确的不可用信号（#1021）。
    _assert_ohlcv_not_stale(data, end_date, symbol, canonical)

    # 将数值四舍五入到两位小数，便于展示。
    numeric_columns = ["Open", "High", "Low", "Close", "Adj Close"]
    for col in numeric_columns:
        if col in data.columns:
            data[col] = data[col].round(2)

    # 将 DataFrame 转换为 CSV 字符串。
    csv_string = data.to_csv()

    # 添加标题信息；如果规范代码不同，也一并展示原始代码，使 Agent 和用户知道
    # 实际定价使用了哪个标的。
    label = canonical if canonical == symbol.upper() else f"{canonical}（来自 {symbol}）"
    header = f"# {label} 的股票数据，日期范围：{start_date} 至 {end_date}\n"
    header += f"# 记录总数：{len(data)}\n"
    header += f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    logger.debug("yfinance 为 %s 返回 %d 行数据", symbol, len(data))
    return header + csv_string

def get_stock_stats_indicators_window(
    symbol: Annotated[str, "公司股票代码"],
    indicator: Annotated[str, "要分析并生成报告的技术指标"],
    curr_date: Annotated[
        str, "当前交易日期，格式为 YYYY-mm-dd"
    ],
    look_back_days: Annotated[int, "向前回看的天数"],
) -> str:

    logger.debug(
        "get_stock_stats_indicators_window called for %s indicator=%s curr_date=%s look_back_days=%d",
        symbol, indicator, curr_date, look_back_days,
    )

    best_ind_params = {
        # 移动平均线。
        "close_50_sma": (
            "50 SMA：中期趋势指标。用途：识别趋势方向并作为动态支撑/阻力。"
            "提示：存在价格滞后，应与更快指标结合以获得及时信号。"
        ),
        "close_200_sma": (
            "200 SMA：长期趋势基准。用途：确认整体市场趋势并识别金叉/死叉形态。"
            "提示：反应较慢，更适合战略趋势确认，不宜用于频繁入场。"
        ),
        "close_10_ema": (
            "10 EMA：灵敏的短期均线。用途：捕捉动能快速变化和潜在入场点。"
            "提示：震荡市噪声较多，应与长期均线结合过滤虚假信号。"
        ),
        # MACD 相关。
        "macd": (
            "MACD：通过 EMA 差值计算动能。用途：观察交叉和背离，识别趋势变化。"
            "提示：低波动或横盘市场需结合其他指标确认。"
        ),
        "macds": (
            "MACD 信号线：对 MACD 线进行 EMA 平滑。用途：与 MACD 线交叉时触发交易。"
            "提示：应纳入更完整策略以避免误报。"
        ),
        "macdh": (
            "MACD 柱状图：显示 MACD 线与信号线的差距。用途：观察动能强弱并尽早发现背离。"
            "提示：波动可能较大，快速市场中需增加过滤条件。"
        ),
        # 动能指标。
        "rsi": (
            "RSI：衡量动能并提示超买/超卖。用途：应用 70/30 阈值并观察背离以识别反转。"
            "提示：强趋势中 RSI 可能长期处于极端区间，务必结合趋势分析。"
        ),
        # 波动率指标。
        "boll": (
            "布林中轨：作为布林带基础的 20 SMA。用途：作为价格运动的动态基准。"
            "提示：结合上下轨可有效发现突破或反转。"
        ),
        "boll_ub": (
            "布林上轨：通常位于中轨上方 2 个标准差。用途：提示潜在超买和突破区域。"
            "提示：需结合其他工具确认，强趋势中价格可能沿上轨运行。"
        ),
        "boll_lb": (
            "布林下轨：通常位于中轨下方 2 个标准差。用途：提示潜在超卖。"
            "提示：需增加分析，避免错误的反转信号。"
        ),
        "atr": (
            "ATR：以真实波幅均值衡量波动率。用途：设置止损并根据当前波动率调整仓位。"
            "提示：这是反应型指标，应作为完整风险管理策略的一部分。"
        ),
        # 成交量指标。
        "vwma": (
            "VWMA：按成交量加权的移动平均线。用途：结合价格行为和成交量确认趋势。"
            "提示：成交量尖峰可能导致结果偏斜，应结合其他成交量分析。"
        ),
        "mfi": (
            "MFI：资金流量指数，结合价格和成交量衡量买卖压力的动能指标。"
            "用途：识别超买（>80）或超卖（<20），确认趋势或反转强度。"
            "提示：可与 RSI 或 MACD 配合确认信号；价格与 MFI 的背离可能提示潜在反转。"
        ),
    }

    if indicator not in best_ind_params:
        raise ValueError(
            f"不支持指标 {indicator}。请选择以下指标之一：{list(best_ind_params.keys())}"
        )

    end_date = curr_date
    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_date_dt - relativedelta(days=look_back_days)

    # 优化：只获取一次股票数据，然后计算所有日期的指标。
    try:
        indicator_data = _get_stock_stats_bulk(symbol, indicator, curr_date)

        # 生成需要的日期范围。
        current_dt = curr_date_dt
        date_values = []

        while current_dt >= before:
            date_str = current_dt.strftime('%Y-%m-%d')

            # 查找当天的指标值。
            if date_str in indicator_data:
                indicator_value = indicator_data[date_str]
            else:
                indicator_value = "N/A：不是交易日（周末或节假日）"

            date_values.append((date_str, indicator_value))
            current_dt = current_dt - relativedelta(days=1)

        # 组装结果字符串。
        ind_string = ""
        for date_str, value in date_values:
            ind_string += f"{date_str}: {value}\n"

    except NoMarketDataError:
        raise  # 未知或已退市代码，交由路由层返回哨兵值。
    except Exception as e:
        logger.warning("批量 stockstats 数据失败：代码=%s 指标=%s：%s", symbol, indicator, e)
        # 批量方法失败时回退到原始实现。
        ind_string = ""
        curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        while curr_date_dt >= before:
            indicator_value = get_stockstats_indicator(
                symbol, indicator, curr_date_dt.strftime("%Y-%m-%d")
            )
            ind_string += f"{curr_date_dt.strftime('%Y-%m-%d')}: {indicator_value}\n"
            curr_date_dt = curr_date_dt - relativedelta(days=1)

    result_str = (
        f"## {indicator} 指标值（{before.strftime('%Y-%m-%d')} 至 {end_date}）：\n\n"
        + ind_string
        + "\n\n"
        + best_ind_params.get(indicator, "暂无指标说明。")
    )

    return result_str


def _get_stock_stats_bulk(
    symbol: Annotated[str, "公司股票代码"],
    indicator: Annotated[str, "要计算的技术指标"],
    curr_date: Annotated[str, "参考日期"]
) -> dict:
    """批量计算 stockstats 指标的优化实现。
    只获取一次数据，然后计算所有可用日期的指标。
    返回日期字符串到指标值的映射。
    """
    from stockstats import wrap

    data = load_ohlcv(symbol, curr_date)
    df = wrap(data)
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

    # 一次性计算所有行的指标；访问该列会触发 stockstats 计算。
    df[indicator]

    # 创建日期字符串到指标值的映射。
    result_dict = {}
    for _, row in df.iterrows():
        date_str = row["Date"]
        indicator_value = row[indicator]

        # 处理 NaN/None 值。
        if pd.isna(indicator_value):
            result_dict[date_str] = "N/A"
        else:
            result_dict[date_str] = str(indicator_value)

    return result_dict


def get_stockstats_indicator(
    symbol: Annotated[str, "公司股票代码"],
    indicator: Annotated[str, "要分析并生成报告的技术指标"],
    curr_date: Annotated[
        str, "当前交易日期，格式为 YYYY-mm-dd"
    ],
) -> str:

    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    curr_date = curr_date_dt.strftime("%Y-%m-%d")

    logger.debug("调用 get_stockstats_indicator：代码=%s 指标=%s 当前日期=%s", symbol, indicator, curr_date)
    try:
        indicator_value = StockstatsUtils.get_stock_stats(
            symbol,
            indicator,
            curr_date,
        )
    except NoMarketDataError:
        raise  # 未知或已退市代码，交由路由层返回哨兵值。
    except Exception as e:
        logger.warning(
            "stockstats 指标失败：代码=%s 指标=%s 日期=%s：%s",
            symbol, indicator, curr_date, e,
        )
        return ""

    return str(indicator_value)


def get_fundamentals(
    ticker: Annotated[str, "公司股票代码"],
    curr_date: Annotated[str, "当前日期（yfinance 不使用）"] = None
):
    """从 yfinance 获取公司基本面概览。"""
    canonical = normalize_symbol(ticker)
    try:
        ticker_obj = yf.Ticker(canonical)
        info = yf_retry(lambda: ticker_obj.info)

        if not info:
            raise NoMarketDataError(ticker, canonical, "no fundamentals returned")

        fields = [
            ("名称", info.get("longName")),
            ("行业", info.get("sector")),
            ("细分行业", info.get("industry")),
            ("市值", info.get("marketCap")),
            ("市盈率（TTM）", info.get("trailingPE")),
            ("预期市盈率", info.get("forwardPE")),
            ("PEG", info.get("pegRatio")),
            ("市净率", info.get("priceToBook")),
            ("每股收益（TTM）", info.get("trailingEps")),
            ("预期每股收益", info.get("forwardEps")),
            ("股息率", info.get("dividendYield")),
            ("Beta", info.get("beta")),
            ("52 周最高", info.get("fiftyTwoWeekHigh")),
            ("52 周最低", info.get("fiftyTwoWeekLow")),
            ("50 日均线", info.get("fiftyDayAverage")),
            ("200 日均线", info.get("twoHundredDayAverage")),
            ("收入（TTM）", info.get("totalRevenue")),
            ("毛利润", info.get("grossProfits")),
            ("EBITDA", info.get("ebitda")),
            ("净利润", info.get("netIncomeToCommon")),
            ("利润率", info.get("profitMargins")),
            ("营业利润率", info.get("operatingMargins")),
            ("净资产收益率", info.get("returnOnEquity")),
            ("总资产收益率", info.get("returnOnAssets")),
            ("产权比率", info.get("debtToEquity")),
            ("流动比率", info.get("currentRatio")),
            ("账面价值", info.get("bookValue")),
            ("自由现金流", info.get("freeCashflow")),
        ]

        lines = []
        for label, value in fields:
            if value is not None:
                lines.append(f"{label}: {value}")

        # yfinance 对未知代码会返回占位字典（例如 {"trailingPegRatio": None），
        # 因此 info 虽为真值但所有字段都是空的。将“没有可用字段”视为无数据，
        # 不要只输出一个可能诱导 Agent 编造内容的空标题。
        if not lines:
            logger.warning("yfinance 未为 %s（规范代码 %s）返回可用的基本面字段", ticker, canonical)
            raise NoMarketDataError(ticker, canonical, "no fundamental fields returned")

        header = f"# {canonical} 的公司基本面\n"
        header += f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        logger.debug("yfinance 为 %s 返回 %d 个基本面字段", canonical, len(lines))
        return header + "\n".join(lines)

    except NoMarketDataError:
        raise
    except Exception as e:
        logger.warning("获取 %s 的基本面失败：%s", ticker, e)
        return f"获取 {ticker} 的基本面失败：{str(e)}"


def get_balance_sheet(
    ticker: Annotated[str, "公司股票代码"],
    freq: Annotated[str, "数据频率：'annual' 或 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "当前日期，格式为 YYYY-MM-DD"] = None
):
    """从 yfinance 获取资产负债表数据。"""
    canonical = normalize_symbol(ticker)
    try:
        ticker_obj = yf.Ticker(canonical)

        if freq.lower() == "quarterly":
            data = yf_retry(lambda: ticker_obj.quarterly_balance_sheet)
        else:
            data = yf_retry(lambda: ticker_obj.balance_sheet)

        data = filter_financials_by_date(data, curr_date)

        if data.empty:
            raise NoMarketDataError(ticker, canonical, "no balance sheet data")

        # 转换为 CSV 字符串，与其他函数保持一致。
        csv_string = data.to_csv()

        # 添加标题信息。
        header = f"# {canonical} 的资产负债表数据（{freq}）\n"
        header += f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        logger.debug("yfinance 为 %s 返回 %d 行资产负债表数据", canonical, len(data))
        return header + csv_string

    except NoMarketDataError:
        raise
    except Exception as e:
        logger.warning("获取 %s 的资产负债表失败：%s", ticker, e)
        return f"获取 {ticker} 的资产负债表失败：{str(e)}"


def get_cashflow(
    ticker: Annotated[str, "公司股票代码"],
    freq: Annotated[str, "数据频率：'annual' 或 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "当前日期，格式为 YYYY-MM-DD"] = None
):
    """从 yfinance 获取现金流量表数据。"""
    logger.debug("调用 get_cashflow：代码=%s 频率=%s 当前日期=%s", ticker, freq, curr_date)
    canonical = normalize_symbol(ticker)
    try:
        ticker_obj = yf.Ticker(canonical)

        if freq.lower() == "quarterly":
            data = yf_retry(lambda: ticker_obj.quarterly_cashflow)
        else:
            data = yf_retry(lambda: ticker_obj.cashflow)

        data = filter_financials_by_date(data, curr_date)

        if data.empty:
            logger.warning("yfinance 对 %s（规范代码 %s）返回空现金流数据", ticker, canonical)
            raise NoMarketDataError(ticker, canonical, "没有现金流数据")

        # 转换为 CSV 字符串，与其他函数保持一致。
        csv_string = data.to_csv()

        # 添加标题信息。
        header = f"# {canonical} 的现金流量表数据（{freq}）\n"
        header += f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        logger.debug("yfinance 为 %s 返回 %d 行现金流量表数据", canonical, len(data))
        return header + csv_string

    except NoMarketDataError:
        raise
    except Exception as e:
        logger.warning("获取 %s 的现金流量表失败：%s", ticker, e)
        return f"获取 {ticker} 的现金流量表失败：{str(e)}"


def get_income_statement(
    ticker: Annotated[str, "公司股票代码"],
    freq: Annotated[str, "数据频率：'annual' 或 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "当前日期，格式为 YYYY-MM-DD"] = None
):
    """从 yfinance 获取利润表数据。"""
    canonical = normalize_symbol(ticker)
    try:
        ticker_obj = yf.Ticker(canonical)

        if freq.lower() == "quarterly":
            data = yf_retry(lambda: ticker_obj.quarterly_income_stmt)
        else:
            data = yf_retry(lambda: ticker_obj.income_stmt)

        data = filter_financials_by_date(data, curr_date)

        if data.empty:
            raise NoMarketDataError(ticker, canonical, "no income statement data")

        # 转换为 CSV 字符串，与其他函数保持一致。
        csv_string = data.to_csv()

        # 添加标题信息。
        header = f"# {canonical} 的利润表数据（{freq}）\n"
        header += f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        logger.debug("yfinance 为 %s 返回 %d 行利润表数据", canonical, len(data))
        return header + csv_string

    except NoMarketDataError:
        raise
    except Exception as e:
        logger.warning("获取 %s 的利润表失败：%s", ticker, e)
        return f"获取 {ticker} 的利润表失败：{str(e)}"


def get_insider_transactions(
    ticker: Annotated[str, "公司股票代码"]
):
    """从 yfinance 获取内幕交易数据。"""
    logger.debug("调用 get_insider_transactions：代码=%s", ticker)
    canonical = normalize_symbol(ticker)
    try:
        ticker_obj = yf.Ticker(canonical)
        data = yf_retry(lambda: ticker_obj.insider_transactions)

        # 这里为空是正常情况（许多有效代码没有内幕交易申报），因此直接说明，
        # 不要将代码视为无效。
        if data is None or data.empty:
            logger.debug("%s（规范代码 %s）没有内幕交易记录", ticker, canonical)
            return f"代码 '{canonical}' 没有内幕交易记录"

        # 转换为 CSV 字符串，与其他函数保持一致。
        csv_string = data.to_csv()

        # 添加标题信息。
        header = f"# {canonical} 的内幕交易数据\n"
        header += f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        logger.debug("yfinance 为 %s 返回 %d 行内部人交易数据", canonical, len(data))
        return header + csv_string

    except Exception as e:
        logger.warning("获取 %s 的内部人交易数据失败：%s", ticker, e)
        return f"获取 {ticker} 的内幕交易失败：{str(e)}"
