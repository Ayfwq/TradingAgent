"""Batch scan: run the full pipeline for several tickers and emit a compact
comparison table (one row per ticker: rating, signal, target price, stop
loss, and a decision excerpt) plus a per-ticker report tree.

Usage:
  uv run --quiet python scripts/scan_tickers.py 600519.SS,000001.SZ,300750.SZ
  uv run --quiet python scripts/scan_tickers.py --tickers 600519.SS --date 2026-08-14
  uv run --quiet python scripts/scan_tickers.py --file my_watchlist.txt
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.graph.trading_graph import TradingAgentsGraph


def _extract_key_numbers(decision: str) -> tuple[str, str]:
    """Best-effort target-price / stop-loss extraction from the decision text."""
    target = stop = ""
    m = re.search(r"(?:target(?: price)?|目标价)[^0-9\-]{0,20}([0-9,]+\.?[0-9]*)", decision, re.I)
    if m:
        target = m.group(1).replace(",", "")
    m = re.search(r"(?:stop[- ]?loss|止损(?:价)?)[^0-9\-]{0,20}([0-9,]+\.?[0-9]*)", decision, re.I)
    if m:
        stop = m.group(1).replace(",", "")
    return target, stop


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a list of tickers through the pipeline")
    parser.add_argument("tickers", nargs="*", help="tickers, e.g. 600519.SS 000001.SZ")
    parser.add_argument("--tickers", dest="tickers_opt", default=None,
                        help="comma-separated tickers")
    parser.add_argument("--file", default=None, help="file with one ticker per line")
    parser.add_argument("--date", default=None, help="analysis date YYYY-MM-DD (default today)")
    parser.add_argument("--out", default=None, help="output directory (default under results_dir)")
    args = parser.parse_args()

    tickers: list[str] = []
    if args.tickers_opt:
        tickers += [t.strip() for t in args.tickers_opt.split(",") if t.strip()]
    tickers += [t for t in args.tickers if t.strip()]
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            tickers += [line.strip() for line in f if line.strip() and not line.startswith("#")]
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        print("No tickers provided.")
        return 2

    trade_date = args.date or datetime.now().strftime("%Y-%m-%d")
    print(f"Scanning {len(tickers)} tickers on {trade_date}:\n")

    rows = []
    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {ticker} ...")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(args.out) if args.out else None
        t0 = time.monotonic()
        try:
            graph = TradingAgentsGraph(debug=False)            final_state, signal = graph.propagate(ticker, trade_date)
            if out_dir is None:
                save_path = graph.save_reports(final_state, ticker)
            else:
                save_path = graph.save_reports(
                    final_state, ticker, out_dir / f"{ticker}_{stamp}"
                )
            decision = final_state.get("final_trade_decision", "")
            rating = parse_rating(decision)
            target, stop = _extract_key_numbers(decision)
            elapsed = time.monotonic() - t0
            print(f"  -> {rating} ({signal}) target={target or '-'} stop={stop or '-'} "
                  f"in {elapsed:.0f}s reports: {save_path}")
            rows.append({
                "ticker": ticker,
                "date": trade_date,
                "rating": rating,
                "signal": str(signal),
                "target": target,
                "stop": stop,
                "elapsed_s": round(elapsed, 1),
                "reports": str(save_path),
                "decision_excerpt": decision.strip()[:300].replace("\n", " "),
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  -> FAILED: {type(exc).__name__}: {str(exc)[:160]}")
            rows.append({"ticker": ticker, "date": trade_date, "rating": "ERROR",
                         "signal": "ERROR", "elapsed_s": round(time.monotonic() - t0, 1),
                         "decision_excerpt": f"{type(exc).__name__}: {str(exc)[:200]}"})

    print("\n=== SCAN SUMMARY ===")
    for r in rows:
        print(f"{r.get('ticker'):<12} {r.get('rating',''):<7} "
              f"target={r.get('target','-'):>10} stop={r.get('stop','-'):>10} "
              f"({r.get('elapsed_s','-')}s)")
    print("\nJSON:")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
