import logging

from . import akshare_data
from .alpha_vantage import (
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_global_news as get_alpha_vantage_global_news,
    get_income_statement as get_alpha_vantage_income_statement,
    get_indicator as get_alpha_vantage_indicator,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_stock as get_alpha_vantage_stock,
)
from .config import get_config
from .errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)
from .fred import get_macro_data as get_fred_macro_data
from .polymarket import get_prediction_markets as get_polymarket_prediction_markets
from .y_finance import (
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_fundamentals as get_yfinance_fundamentals,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
    get_stock_stats_indicators_window,
    get_YFin_data_online,
)
from .yfinance_news import get_global_news_yfinance, get_news_yfinance

logger = logging.getLogger(__name__)

# 按类别组织工具。
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV 股票价格数据",
        "tools": [
            "get_stock_data"
        ]
    },
    "ashare_context": {
        "description": "A 股特色上下文：龙虎榜、北向资金、涨停池、行业广度",
        "tools": [
            "get_lhb_context",
            "get_northbound_flow",
            "get_limit_up_context",
            "get_sector_context",
        ]
    },
    "forecast_data": {
        "description": "A-share earnings guidance (业绩预告)",
        "tools": [
            "get_earnings_forecast",
        ]
    },
    "technical_indicators": {
        "description": "技术分析指标",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "公司基本面",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "新闻和内幕交易数据",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    },
    "macro_data": {
        "description": "宏观经济指标（利率、通胀、就业、增长）",
        "tools": [
            "get_macro_indicators",
        ]
    },
    "prediction_markets": {
        "description": "未来事件的市场隐含概率",
        "tools": [
            "get_prediction_markets",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "fred",
    "polymarket",
    "alpha_vantage",
    "akshare",
]

# 可选增强类别。这些类别为新闻分析师补充宏观/事件上下文，但不是决策核心，
# 因此供应商失败时返回哨兵值，而不是中止运行。核心类别（价格、基本面、新闻）
# 仍会抛出异常，以便及时暴露主供应商故障。
OPTIONAL_CATEGORIES = {"macro_data", "prediction_markets"}

# 方法到供应商实现的映射。
VENDOR_METHODS = {
    # 核心股票数据接口
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "akshare": akshare_data.get_stock_data_akshare,
    },
    # ashare_context（A 股特色信号；仅支持 akshare，优雅降级）
    "get_lhb_context": {
        "akshare": akshare_data.get_lhb_context,
    },
    "get_northbound_flow": {
        "akshare": akshare_data.get_northbound_flow,
    },
    "get_limit_up_context": {
        "akshare": akshare_data.get_limit_up_context,
    },
    "get_sector_context": {
        "akshare": akshare_data.get_sector_context,
    },
    # forecast_data（A 股业绩预告）
    "get_earnings_forecast": {
        "akshare": akshare_data.get_earnings_forecast,
    },
    # 技术指标
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "akshare": get_stock_stats_indicators_window,  # 基于 akshare OHLCV 的 stockstats
    },
    # 基本面数据
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
        "akshare": akshare_data.get_fundamentals_akshare,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
        "akshare": akshare_data.get_balance_sheet_akshare,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
        "akshare": akshare_data.get_cashflow_akshare,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
        "akshare": akshare_data.get_income_statement_akshare,
    },
    # 新闻数据
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        "akshare": akshare_data.get_news_akshare,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
        "akshare": akshare_data.get_global_news_akshare,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
        "akshare": akshare_data.get_insider_transactions_akshare,
    },
    # 宏观数据
    "get_macro_indicators": {
        "fred": get_fred_macro_data,
        "akshare": akshare_data.get_macro_indicators_akshare,
    },
    # 预测市场
    "get_prediction_markets": {
        "polymarket": get_polymarket_prediction_markets,
    },
}

def get_category_for_method(method: str) -> str:
    """获取包含指定方法的类别。"""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"方法 '{method}' 不属于任何类别")

def get_vendor(category: str, method: str = None) -> str:
    """获取数据类别或具体工具方法配置的数据供应商。
    工具级配置优先于类别级配置。
    """
    config = get_config()

    # 如果提供了 method，先检查工具级配置。
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # 回退到类别级配置。
    return config.get("data_vendors", {}).get(category, "default")

def route_to_vendor(method: str, *args, **kwargs):
    """将方法调用路由到合适的供应商实现，并提供回退支持。"""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    all_available_vendors = list(VENDOR_METHODS[method].keys())

    # 已配置的供应商列表就是回退链：不会静默回退到用户未选择的供应商
    #（#988/#289），因为这会从意外来源返回数据，造成不同供应商之间不一致。
    # 如需多供应商回退，请按顺序列出，例如 data_vendors="yfinance,alpha_vantage"。
    #“default”哨兵值（未显式配置）会使用所有可用供应商。
    explicit = [v for v in primary_vendors if v and v != "default"]
    if explicit:
        vendor_chain = [v for v in explicit if v in VENDOR_METHODS[method]]
        if not vendor_chain:
            raise ValueError(
                f"配置的供应商 {explicit} 不支持方法 '{method}'。"
                f"可用供应商：{all_available_vendors}。"
            )
    else:
        vendor_chain = all_available_vendors

    last_no_data: NoMarketDataError | None = None
    first_error: Exception | None = None
    for vendor in vendor_chain:
        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            return impl_func(*args, **kwargs)
        except VendorRateLimitError:
            logger.warning("供应商 %r 对 %s 触发限流，尝试下一个供应商。", vendor, method)
            continue
        except VendorNotConfiguredError as e:
            logger.warning("供应商 %r 未配置，无法处理 %s，尝试下一个供应商。", vendor, method)
            if first_error is None:
                first_error = e  # 如果没有其他供应商可用，最终抛出该错误。
            continue
        except NoMarketDataError as e:
            last_no_data = e  # 此供应商没有数据，其他配置的供应商可能有数据。
            continue
        except Exception as e:
            # 一个供应商失败而另一个供应商可以提供数据时，不要让调用崩溃；
            # 但也不能静默吞掉异常：主供应商故障必须在日志中可见（#989），
            # 不能被备用供应商的结果掩盖。
            logger.warning("供应商 %r 处理 %s 失败：%s", vendor, method, e)
            if first_error is None:
                first_error = e
            continue

    # 如果任一供应商报告“无数据”，说明该代码确实不可用。
    # 返回统一且明确的指导性哨兵值，而不是供应商特定的空字符串，
    # 让智能体报告“不可用”而不是虚构数值。此判断优先于偶发的回退错误。
    if last_no_data is not None:
        if first_error is not None:
            # 某个供应商也遇到了真实错误；将其写入日志，避免“无数据”结论
            # 掩盖主供应商的网络、认证等故障。
            logger.warning(
                "返回 NO_DATA：%s，但此前已有供应商报错：%s",
                method, first_error,
            )
        sym = last_no_data.symbol
        canonical = last_no_data.canonical
        resolved = "" if canonical == sym else f" (resolved to '{canonical}')"
        # 暴露类型化错误的详细信息（例如“最新行是 2025-06-11……数据过期”），
        # 让智能体看到具体原因——代码无效、没有覆盖或数据过期，而不是笼统的“不可用”。
        reason = f" ({last_no_data.detail})" if last_no_data.detail else ""
        return (
            f"NO_DATA_AVAILABLE：任何配置的供应商都没有返回 '{sym}'{resolved} 的可用市场数据{reason}。"
            f"代码可能无效、已退市、没有数据覆盖，或供应商返回了过期数据。"
            f"不要估算或虚构数值，请报告该代码的数据不可用。"
        )

    # 没有供应商返回数据，也没有供应商明确报告“无数据”——暴露第一个真实错误
    #（例如主供应商网络失败）。可选增强类别则降级为哨兵值，避免辅助数据中止运行。
    if first_error is not None:
        if category in OPTIONAL_CATEGORIES:
            logger.warning("可选类别 %s 无法用于 %s：%s", category, method, first_error)
            return (
                f"DATA_UNAVAILABLE：无法获取可选类别 {category} 的数据（{first_error}）。"
                f"请在没有该数据的情况下继续，不要虚构数值。"
            )
        raise first_error

    raise RuntimeError(f"方法 '{method}' 没有可用供应商")
