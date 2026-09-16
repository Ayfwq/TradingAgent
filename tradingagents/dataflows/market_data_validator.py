"""确定性的市场数据校验快照。

市场分析师是 LLM，可能编造精确数字，例如引用底层数据并不支持的布林带或“经过
历史验证的反弹”（#830）。本模块计算真实数据快照（分析日期当日及之前的最新
OHLCV 行、常用指标和近期收盘价），并要求分析师将其作为所有精确数字声明的事实
来源。该过程是确定性的，不涉及 LLM。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import pandas as pd
from stockstats import wrap

from tradingagents.dataflows.stockstats_utils import load_ohlcv

logger = logging.getLogger(__name__)

# 固定的常用指标集合，确保每次快照结构一致。
DEFAULT_SNAPSHOT_INDICATORS: tuple[str, ...] = (
    "close_10_ema", "close_50_sma", "close_200_sma",
    "rsi", "boll", "boll_ub", "boll_lb",
    "macd", "macds", "macdh", "atr",
)


def _verified_rows(symbol: str, curr_date: str) -> pd.DataFrame:
    """获取 curr_date 当日及之前按日期排序的 OHLCV；没有可用数据时抛出异常。

    ``load_ohlcv`` 已规范化 Date 列并过滤前视数据，但这里仍防御性地重新应用截止
    日期。由于这是校验路径，不能假设输入已经完成过滤。
    """
    logger.debug("_verified_rows called for %s curr_date=%s", symbol, curr_date)
    data = load_ohlcv(symbol, curr_date)
    if data is None or data.empty:
        logger.warning("%s 在 %s 没有可用 OHLCV 数据", symbol, curr_date)
        raise ValueError(f"{symbol} 没有可用 OHLCV 数据。")

    df = data.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df = df[df["Date"] <= pd.to_datetime(curr_date)].sort_values("Date")
    if df.empty:
        logger.warning("%s 在 %s 当日及之前没有 OHLCV 数据行", symbol, curr_date)
        raise ValueError(f"{symbol} 在 {curr_date} 当日及之前没有 OHLCV 数据行。")
    return df


def _fmt(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def build_verified_market_snapshot(
    symbol: str,
    curr_date: str,
    look_back_days: int = 30,
    indicators: Iterable[str] | None = None,
) -> str:
    """渲染真实数据快照：最新 OHLCV 行、指标和近期收盘价。"""
    logger.debug("已调用 build_verified_market_snapshot：%s，curr_date=%s，look_back_days=%d", symbol, curr_date, look_back_days)
    # `df` 保留原始大写 OHLCV 列（Open/High/Low/Close/Volume）；stockstats 的
    # `wrap()` 会将列名转为小写并添加指标列，因此从 `df` 读取原始价格，从
    # `stock_df` 读取指标。
    df = _verified_rows(symbol, curr_date)
    stock_df = wrap(df.copy())

    selected = tuple(indicators or DEFAULT_SNAPSHOT_INDICATORS)
    indicator_values: dict[str, str] = {}
    for name in selected:
        try:
            stock_df[name]  # 触发 stockstats 计算。
            indicator_values[name] = _fmt(stock_df.iloc[-1][name])
        except Exception as exc:  # noqa: BLE001 — 单个指标失败不应影响整个快照
            logger.warning("指标 %s 在 %s 的 %s 日期计算失败：%s", name, symbol, curr_date, exc)
            indicator_values[name] = f"N/A ({type(exc).__name__})"

    latest = df.iloc[-1]
    latest_date = _fmt(latest["Date"])
    window = max(1, min(int(look_back_days), 30))
    recent = df.tail(window)

    lines = [
        f"## {symbol.upper()} 的已校验市场数据快照",
        "",
        f"- 请求的分析日期：{curr_date}",
        f"- 使用的最新交易行：{latest_date}",
        "- 校验前已排除请求分析日期之后的数据行。",
        "",
        "### 最新已校验 OHLCV 行",
        "",
        "| 字段 | 数值 |",
        "|---|---:|",
    ]
    for field in ("Open", "High", "Low", "Close", "Volume"):
        lines.append(f"| {field} | {_fmt(latest.get(field))} |")

    lines += ["", "### 最新行的已校验技术指标", "",
              "| 指标 | 数值 |", "|---|---:|"]
    for name, value in indicator_values.items():
        lines.append(f"| {name} | {value} |")

    lines += ["", f"### 近期已校验收盘价（最近 {len(recent)} 行）", "",
              "| 日期 | 收盘价 |", "|---|---:|"]
    for _, row in recent.iterrows():
        lines.append(f"| {_fmt(row['Date'])} | {_fmt(row.get('Close'))} |")

    lines += [
        "",
        "将此快照作为精确 OHLCV、价格水平和指标值声明的事实来源。如果其他工具输出"
        "与之冲突，应指出差异，不要编造一个调和后的数字。除非工具输出提供了具体"
        "日期和价格直接支持，否则不要声称已通过历史验证、出现支撑/阻力反弹或发生"
        "精确百分比变动。",
    ]
    logger.debug("已为 %s 在 %s 构建校验快照（%d 行，最新日期 %s）", symbol, curr_date, len(df), latest_date)
    return "\n".join(lines)
