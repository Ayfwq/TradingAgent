"""akshare 供应商的工具级集成测试。

通过框架供应商路由器执行每个数据工具，调用路径与智能体完全一致
（TradingAgentsGraph 初始化时会应用 .env 中的 TRADINGAGENTS_DATA_VENDORS）。
使用 A 股代码 600519.SS（贵州茅台），并在支持的地方测试美股 NVDA。

用法：uv run python scripts/test_akshare_vendor.py
"""

import tradingagents  # noqa: F401  (loads .env + NO_PROXY)

from tradingagents.agents.utils.agent_utils import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_global_news,
    get_income_statement,
    get_indicators,
    get_insider_transactions,
    get_macro_indicators,
    get_news,
    get_stock_data,
    get_verified_market_snapshot,
)
from tradingagents.dataflows.config import get_config, set_config

# 对照 TradingAgentsGraph 初始化时执行的逻辑。
from tradingagents.default_config import DEFAULT_CONFIG, apply_data_vendors_env

set_config(apply_data_vendors_env(DEFAULT_CONFIG.copy()))

cfg = get_config()
print("=== 数据供应商 ===")
for k, v in cfg["data_vendors"].items():
    print(f"  {k}: {v}")

TICKER = "600519.SS"
DATE = "2024-02-01"


def section(name):
    print(f"\n{'=' * 70}\n{name}\n{'=' * 70}")


section("get_stock_data (A-share)")
out = get_stock_data.invoke({"symbol": TICKER, "start_date": "2024-01-02", "end_date": "2024-02-01"})
print(out[:400])
print("...\n[length]", len(out))

section("get_indicators rsi (A-share)")
out = get_indicators.invoke({"symbol": TICKER, "indicator": "rsi", "curr_date": DATE, "look_back_days": 30})
print(out[:500])

section("get_verified_market_snapshot (A-share)")
out = get_verified_market_snapshot.invoke({"symbol": TICKER, "curr_date": DATE, "look_back_days": 30})
print(out[:600])

section("get_fundamentals (A-share)")
out = get_fundamentals.invoke({"ticker": TICKER, "curr_date": DATE})
print(out[:500])

section("get_balance_sheet (A-share)")
out = get_balance_sheet.invoke({"ticker": TICKER, "freq": "quarterly", "curr_date": DATE})
print(out[:400])

section("get_cashflow (A-share)")
out = get_cashflow.invoke({"ticker": TICKER, "freq": "quarterly", "curr_date": DATE})
print(out[:300])

section("get_income_statement (A-share)")
out = get_income_statement.invoke({"ticker": TICKER, "freq": "quarterly", "curr_date": DATE})
print(out[:300])

section("get_news (A-share)")
out = get_news.invoke({"ticker": TICKER, "start_date": "2024-01-25", "end_date": "2024-02-01"})
print(out[:600])

section("get_global_news")
out = get_global_news.invoke({"curr_date": DATE, "look_back_days": 7, "limit": 5})
print(out[:500])

section("get_insider_transactions")
out = get_insider_transactions.invoke({"ticker": TICKER})
print(out[:400])

section("get_macro_indicators cpi")
out = get_macro_indicators.invoke({"indicator": "cpi", "curr_date": DATE, "look_back_days": 365})
print(out[:400])

section("get_stock_data (US NVDA)")
out = get_stock_data.invoke({"symbol": "NVDA", "start_date": "2024-01-02", "end_date": "2024-02-01"})
print(out[:400])
print("...\n[length]", len(out))

print("\n所有工具测试完成")
