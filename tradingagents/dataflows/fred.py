"""FRED（Federal Reserve Economic Data）宏观数据供应商。

通过圣路易斯联储免费 API 获取宏观经济时间序列，包括政策利率、国债收益率、通胀、
就业和增长数据。供新闻分析师使用真实数字支撑宏观评论，而不只依赖新闻标题。

从 ``FRED_API_KEY`` 读取免费 API 密钥；未设置时抛出 ``FredNotConfiguredError``，
让路由层将其视为“不可用”，而不是导致程序崩溃。
"""
import logging
import os
from datetime import datetime, timedelta

import requests

from .errors import VendorNotConfiguredError

logger = logging.getLogger(__name__)

FRED_API_BASE = "https://api.stlouisfed.org/fred"

# 网络超时时间（秒），避免卡住的请求阻塞 Agent，与 Alpha Vantage 客户端保持一致。
REQUEST_TIMEOUT = 30

# 调用方未指定时的默认回溯窗口。一年可以覆盖大多数月度/季度序列的趋势及同比基数。
DEFAULT_LOOKBACK_DAYS = 365

# 渲染表格的行数上限：近期值对决策最重要，长窗口的日频序列（收益率、VIX）
# 否则会淹没上下文。
MAX_ROWS = 40

# 精选的易读别名 -> FRED 序列 ID。未列出的值会原样作为 FRED 原始序列 ID
# 使用，因此高级用户不会受此列表限制。
MACRO_SERIES = {
    # 政策利率与国债收益率。
    "fed_funds_rate": "FEDFUNDS",
    "federal_funds_rate": "FEDFUNDS",
    "fed_funds": "FEDFUNDS",
    "2y_treasury": "DGS2",
    "10y_treasury": "DGS10",
    "30y_treasury": "DGS30",
    "10y_2y_spread": "T10Y2Y",
    "yield_curve": "T10Y2Y",
    # 通胀。
    "cpi": "CPIAUCSL",
    "core_cpi": "CPILFESL",
    "pce": "PCEPI",
    "core_pce": "PCEPILFE",
    "inflation_expectations": "T10YIE",
    # 增长与产出。
    "real_gdp": "GDPC1",
    "gdp": "GDP",
    "industrial_production": "INDPRO",
    # 就业。
    "unemployment_rate": "UNRATE",
    "unemployment": "UNRATE",
    "nonfarm_payrolls": "PAYEMS",
    "payrolls": "PAYEMS",
    "initial_claims": "ICSA",
    # 货币与市场。
    "m2": "M2SL",
    "money_supply": "M2SL",
    "vix": "VIXCLS",
    "dollar_index": "DTWEXBGS",
    # 情绪与住房。
    "consumer_sentiment": "UMCSENT",
    "housing_starts": "HOUST",
    "retail_sales": "RSAFS",
}


class FredNotConfiguredError(VendorNotConfiguredError):
    """选择 FRED 但未配置 API 密钥时抛出。

    该异常继承 VendorNotConfiguredError（因此仍是 ValueError），可以继续兼容
    路由层的“供应商不可用”处理和现有 ValueError 调用方。
    """


def get_api_key() -> str:
    """从环境变量读取 FRED API 密钥。"""
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise FredNotConfiguredError(
            "未设置 FRED_API_KEY 环境变量。可在以下地址获取免费密钥："
            "https://fred.stlouisfed.org/docs/api/api_key.html."
        )
    return api_key


def _resolve_series_id(indicator: str) -> str:
    """将友好别名映射为 FRED 序列 ID，或直接透传原始 ID。

    当输入既不是已知别名，也不是合理的序列 ID 时抛出 ``ValueError``，通常是因为
    LLM 传入了描述性短语（例如 "bank of japan rate"）。FRED ID 短且只含字母数字，
    因此提前拒绝并给出提示，避免 API 返回 400。
    """
    key = indicator.strip().lower().replace(" ", "_").replace("-", "_")
    if key in MACRO_SERIES:
        return MACRO_SERIES[key]
    candidate = indicator.strip().upper()
    # FRED 序列 ID 不含空格且长度较短；拒绝其他输入（LLM 传入的描述性短语），
    # 避免 API 返回 400。
    if not candidate or len(candidate) > 30 or any(c.isspace() for c in candidate):
        raise ValueError(
            f"'{indicator}' 不是已知宏观别名或有效的 FRED 序列 ID。"
            f"请使用别名（例如 'cpi'、'unemployment'、'10y_treasury'）或原始"
            f" FRED 序列 ID（例如 'CPIAUCSL'）。"
        )
    return candidate


def _request(path: str, params: dict) -> dict:
    """请求 FRED 接口，在请求失败时暴露 FRED 返回的 JSON 错误内容。"""
    api_params = {**params, "api_key": get_api_key(), "file_type": "json"}
    response = requests.get(
        f"{FRED_API_BASE}/{path}", params=api_params, timeout=REQUEST_TIMEOUT
    )
    # FRED 会针对未知序列 ID 或错误参数返回包含 error_message 的 400 JSON；
    # 将其转换为清晰且可处理的错误。
    if response.status_code == 400:
        try:
            message = response.json().get("error_message", response.text)
        except ValueError:
            message = response.text
        raise ValueError(f"FRED 请求失败：{message}")
    response.raise_for_status()
    return response.json()


def get_macro_data(
    indicator: str,
    curr_date: str,
    look_back_days: int | None = None,
) -> str:
    """获取 FRED 宏观经济序列，并格式化为 Markdown 报告。

    Args:
        indicator：友好别名（例如 "cpi"、"unemployment"、"10y_treasury"）或
            原始 FRED 序列 ID（例如 "CPIAUCSL"、"DGS10"）。
        curr_date：窗口结束日期（yyyy-mm-dd）；不会返回更晚的观测值，
            因此历史日期不会泄漏未来数据。
        look_back_days：回溯窗口长度；``None`` 使用 DEFAULT_LOOKBACK_DAYS。

    Returns:
        包含序列标题、单位、频率、最新值、窗口变化和近期观测表的 Markdown 报告。
    """
    if look_back_days is None:
        look_back_days = DEFAULT_LOOKBACK_DAYS

    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_date = (end_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")

    # LLM 提供的指标无效时返回指导而不是抛出异常，避免错误参数中止运行。
    # 路由层也会降级宏观数据，但具体提示对分析师更有用。
    try:
        series_id = _resolve_series_id(indicator)
    except ValueError as e:
        return f"FRED：{e}"

    meta = _request("series", {"series_id": series_id}).get("seriess") or []
    if not meta:
        return (
            f"找不到 FRED 序列 '{series_id}'。请传入已知别名（例如 'cpi'、'unemployment'）"
            f"或有效的 FRED 序列 ID。"
        )
    info = meta[0]
    title = info.get("title", series_id)
    units = info.get("units_short") or info.get("units", "")
    frequency = info.get("frequency", "")
    seasonal = info.get("seasonal_adjustment_short", "")

    observations = _request(
        "series/observations",
        {
            "series_id": series_id,
            "observation_start": start_date,
            "observation_end": curr_date,
            "sort_order": "asc",
        },
    ).get("observations", [])

    # FRED 用 "." 表示缺失观测值。
    points = [
        (o["date"], o["value"])
        for o in observations
        if o.get("value") not in (".", None, "")
    ]

    header = (
        f"## FRED：{title}（{series_id}）\n"
        f"- 单位：{units}\n"
        f"- 频率：{frequency}"
        f"{f' ({seasonal})' if seasonal else ''}\n"
        f"- 窗口：{start_date} 至 {curr_date}\n"
    )

    if not points:
        return header + (
            f"\n该窗口内没有 {series_id} 的观测值。该序列的发布频率可能低于窗口长度，"
            f"请增大 look_back_days。"
        )

    first_date, first_val = points[0]
    last_date, last_val = points[-1]
    try:
        delta = float(last_val) - float(first_val)
        base = float(first_val)
        pct = f" ({delta / base * 100:+.2f}%)" if base != 0 else ""
        summary = (
            f"\n**最新值：** {last_val}（{last_date}）| "
            f"**窗口变化：** {delta:+.2f}{pct}，"
            f"从 {first_val}（{first_date}）计算\n"
        )
    except ValueError:
        summary = f"\n**最新值：** {last_val}（{last_date}）\n"

    shown = points
    note = ""
    if len(points) > MAX_ROWS:
        shown = points[-MAX_ROWS:]
        note = f"\n_（显示最近 {MAX_ROWS} 条，共 {len(points)} 条观测）_\n"

    table = (
        "\n| 日期 | 数值 |\n| --- | --- |\n"
        + "\n".join(f"| {d} | {v} |" for d, v in shown)
        + "\n"
    )

    return header + summary + note + table
