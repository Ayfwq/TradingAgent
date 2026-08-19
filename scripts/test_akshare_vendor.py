"""Tool-level integration test for the akshare vendor.

Exercises every data tool through the framework's vendor router exactly as
the agents would call them (TradingAgentsGraph applies TRADINGAGENTS_DATA_VENDORS
from .env at init). Uses A-share ticker 600519.SS (Kweichow Moutai) and US
NVDA where supported.

Usage:  uv run python scripts/test_akshare_vendor.py
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

# Mirror what TradingAgentsGraph does at init.
from tradingagents.default_config import DEFAULT_CONFIG, apply_data_vendors_env

set_config(apply_data_vendors_env(DEFAULT_CONFIG.copy()))

cfg = get_config()
print("=== data_vendors ===")
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

print("\nALL TOOL TESTS DONE")
