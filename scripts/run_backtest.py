"""Decision backtest: run the full pipeline on historical dates and score
each decision against the subsequently realized returns.

This is the objective answer to "can it predict?": for every historical
trade date we run the whole agent pipeline exactly as a live run would
(analysts -> debate -> RM -> trader -> risk -> PM), then compare the
decision with what actually happened over the next 20/60/120 days.

Design notes:
  - Look-ahead safety is inherited from the framework: every data tool is
    filtered to ``curr_date`` (no future prices/news/macros reach the agents).
  - Memory log is redirected to a scratch file so backtests never pollute the
    live decision log.
  - Holding periods are calendar days with a buffer; the realized-return
    lookup (akshare/Sina) returns the actual trading days used.

Usage:
  uv run --quiet python scripts/run_backtest.py --ticker 600519.SS \
      --dates 2026-01-15,2026-03-16,2026-05-15 --hold 20,60
  uv run --quiet python scripts/run_backtest.py --ticker 000001.SZ --months 6
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.dataflows.akshare_data import get_market_returns
from tradingagents.graph.trading_graph import TradingAgentsGraph


def _monthly_dates(end: datetime, months: int) -> list[str]:
    """One date per month (the 15th, a safe mid-month trading day) ending at
    ``end``, going back ``months`` months."""
    dates = []
    y, m = end.year, end.month
    for _ in range(months):
        dates.append(f"{y:04d}-{m:02d}-15")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(dates))


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest TradingAgents decisions")
    parser.add_argument("--ticker", default="600519.SS")
    parser.add_argument("--dates", default=None, help="comma-separated YYYY-MM-DD")
    parser.add_argument("--months", type=int, default=0,
                        help="auto-generate monthly dates going back N months (15th of each)")
    parser.add_argument("--hold", default="20,60",
                        help="comma-separated holding periods in calendar days")
    parser.add_argument("--limit", type=int, default=0,
                        help="max number of dates to run (0 = all)")
    parser.add_argument("--out", default=None, help="output CSV path")
    args = parser.parse_args()

    ticker = args.ticker
    if args.dates:
        dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    elif args.months:
        dates = _monthly_dates(datetime.now(), args.months)
    else:
        print("Provide --dates or --months")
        return 2
    if args.limit > 0:
        dates = dates[: args.limit]
    holds = [int(h) for h in args.hold.split(",") if h.strip()]
    print(f"Backtest {ticker}: {len(dates)} dates, holds={holds} days")

    scratch = tempfile.mkdtemp(prefix="ta_backtest_")
    out_dir = Path(args.out) if args.out else Path(scratch) / "reports"

    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config.update({
        "results_dir": str(out_dir),
        "data_cache_dir": os.path.join(scratch, "cache"),
        "memory_log_path": os.path.join(scratch, "memory.md"),
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "max_tool_rounds": 3,
        "checkpoint_enabled": False,
        "output_language": "English",
    })
    graph = TradingAgentsGraph(config=config, debug=False)
    benchmark = graph._resolve_benchmark(ticker)

    rows = []
    for i, trade_date in enumerate(dates, 1):
        print(f"\n[{i}/{len(dates)}] Running pipeline for {ticker} on {trade_date} ...")
        try:
            final_state, signal = graph.propagate(ticker, trade_date)
        except Exception as exc:  # noqa: BLE001
            print(f"  pipeline FAILED: {type(exc).__name__}: {exc}")
            rows.append({"date": trade_date, "rating": "ERROR", "signal": "ERROR",
                         "reason": f"{type(exc).__name__}: {str(exc)[:120]}"})
            continue

        decision = final_state.get("final_trade_decision", "")
        rating = parse_rating(decision)
        print(f"  rating={rating} signal={signal}")

        row = {
            "date": trade_date,
            "rating": rating,
            "signal": str(signal),
            "decision_excerpt": (decision.strip()[:200].replace("\n", " ")),
        }
        for hold in holds:
            raw, alpha, days = get_market_returns(ticker, trade_date, hold, benchmark)
            row[f"raw_{hold}d"] = round(raw, 6) if raw is not None else None
            row[f"alpha_{hold}d"] = round(alpha, 6) if alpha is not None else None
            row[f"days_{hold}d"] = days
        rows.append(row)
        print(f"  outcome: raw={row.get('raw_%dd' % holds[0])}")

    df = pd.DataFrame(rows)
    out_csv = Path(args.out) if args.out else Path(scratch) / "backtest_results.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"\n=== RESULTS ({len(df)} dates) ===")
    print(df.to_string(index=False))
    print(f"\nCSV saved to: {out_csv}")
    print(f"Reports under: {out_dir}")

    # Summary: directional hit rate for BUY (raw>0 over first hold) / SELL (raw<0).
    if len(df) and f"raw_{holds[0]}d" in df.columns:
        valid = df.dropna(subset=[f"raw_{holds[0]}d"])
        if len(valid):
            buys = valid[valid["rating"] == "Buy"]
            sells = valid[valid["rating"] == "Sell"]
            hold_ = valid[valid["rating"] == "Hold"]
            col = f"raw_{holds[0]}d"
            summary = {
                "total": len(valid),
                "buy": len(buys), "buy_avg_raw": round(buys[col].mean(), 4) if len(buys) else None,
                "sell": len(sells), "sell_avg_raw": round(sells[col].mean(), 4) if len(sells) else None,
                "hold": len(hold_), "hold_avg_raw": round(hold_[col].mean(), 4) if len(hold_) else None,
            }
            print("\n=== SUMMARY ===")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
