"""Check akshare A-share data coverage across boards/market caps.

For each ticker it exercises the exact code paths the pipeline uses:
  - load_ohlcv_akshare        (Sina daily OHLCV -> indicators/snapshot)
  - get_stock_data_akshare    (CSV for agents)
  - get_fundamentals_akshare  (Sina financial indicators)
  - get_balance_sheet_akshare (Sina financial abstract)
  - get_news_akshare          (Eastmoney per-ticker news)
  - get_insider_transactions_akshare (Xueqiu insider trades)

Usage:  uv run --quiet python scripts/check_ashare_coverage.py [ticker ...]
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime

import pandas as pd

from tradingagents.dataflows import akshare_data as akv

DEFAULT_TICKERS = [
    "600519.SS",  # 贵州茅台  沪主板 (blue chip)
    "601318.SS",  # 中国平安  沪主板 (blue chip)
    "000001.SZ",  # 平安银行  深主板
    "002594.SZ",  # 比亚迪    深主板(原中小板)
    "300750.SZ",  # 宁德时代  创业板
    "688981.SS",  # 中芯国际  科创板
    "920002.BJ",  # 北交所(920 新代码段)
    "832566.BJ",  # 北交所(83 老代码段, 已知新浪不支持)
    "000029.SZ",  # 深深房A   小市值/低流动性
]


def check(ticker: str, curr_date: str) -> dict:
    out: dict = {"ticker": ticker}
    try:
        df = akv.load_ohlcv_akshare(ticker, curr_date)
        out["ohlcv_rows"] = len(df)
        out["ohlcv_last"] = str(df["Date"].iloc[-1].date())
        out["ohlcv_close"] = float(df["Close"].iloc[-1])
    except Exception as exc:  # noqa: BLE001
        out["ohlcv_error"] = f"{type(exc).__name__}: {exc}"

    try:
        csv = akv.get_stock_data_akshare(ticker, "2025-01-01", curr_date)
        out["csv_len"] = len(csv)
    except Exception as exc:  # noqa: BLE001
        out["csv_error"] = f"{type(exc).__name__}: {exc}"

    try:
        s = akv.get_fundamentals_akshare(ticker, curr_date)
        out["fundamentals"] = "ok" if "unavailable" not in s and "Error" not in s else f"degraded: {s[:80]}"
    except Exception as exc:  # noqa: BLE001
        out["fundamentals_error"] = f"{type(exc).__name__}: {exc}"

    try:
        s = akv.get_balance_sheet_akshare(ticker, "quarterly", curr_date)
        out["balance"] = "ok" if "unavailable" not in s and "Error" not in s else f"degraded: {s[:80]}"
    except Exception as exc:  # noqa: BLE001
        out["balance_error"] = f"{type(exc).__name__}: {exc}"

    start = (pd.Timestamp(curr_date) - pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    try:
        s = akv.get_news_akshare(ticker, start, curr_date)
        n = s.count("\n") if s else 0
        out["news"] = f"{n} lines" if "No" not in s[:60] else s[:60]
    except Exception as exc:  # noqa: BLE001
        out["news_error"] = f"{type(exc).__name__}: {exc}"

    try:
        s = akv.get_insider_transactions_akshare(ticker)
        out["insider"] = "ok" if "unavailable" not in s and "Error" not in s else s[:80]
    except Exception as exc:  # noqa: BLE001
        out["insider_error"] = f"{type(exc).__name__}: {exc}"

    return out


def main() -> None:
    tickers = sys.argv[1:] or DEFAULT_TICKERS
    curr_date = datetime.now().strftime("%Y-%m-%d")
    print(f"curr_date={curr_date}\n")
    failed = 0
    for t in tickers:
        try:
            r = check(t, curr_date)
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"== {t} ==\n  FATAL:\n{traceback.format_exc()}")
            continue
        status = []
        for k in ("ohlcv_rows", "ohlcv_last", "ohlcv_close", "csv_len",
                  "fundamentals", "balance", "news", "insider"):
            if k in r:
                status.append(f"{k}={r[k]}")
        for k in ("ohlcv_error", "csv_error", "fundamentals_error",
                  "balance_error", "news_error", "insider_error"):
            if k in r:
                status.append(f"{k}={r[k]}")
        ok = any(k in r for k in ("ohlcv_rows",)) and not any(
            k.endswith("_error") for k in r
        )
        if not ok:
            failed += 1
        print(f"== {t} == {'OK' if ok else 'ISSUES'}")
        for s in status:
            print(f"   {s}")
        print()
    print(f"tickers with issues: {failed}/{len(tickers)}")


if __name__ == "__main__":
    main()
