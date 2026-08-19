"""A-share full-pipeline runner (data-complete, zero-degradation path).

Uses Kweichow Moutai (600519.SS) with today's date as the analysis date:
- OHLCV, technical indicators, verified snapshot, fundamentals, the three
  financial statements, per-ticker news, global news, macro series and
  insider transactions all come from domestic sources (Sina/Eastmoney/
  JinShi/Xueqiu) via the akshare vendor — no Yahoo, no overseas APIs.
- The LLM stack runs deepseek @ the configured endpoint (deep=pro, quick=flash).
- Writes a structured run summary (run_summary.json) next to the reports.

Usage:  uv run python scripts/run_ashare.py [TICKER] [DATE] [SAVE_PATH]
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import tradingagents  # noqa: F401  (loads .env)

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

TICKER = sys.argv[1] if len(sys.argv) > 1 else "600519.SS"
DATE = sys.argv[2] if len(sys.argv) > 2 else datetime.now().strftime("%Y-%m-%d")

print(f"=== A-share pipeline: {TICKER} @ {DATE} ===")
print(f"LLM: deep={DEFAULT_CONFIG['deep_think_llm']} quick={DEFAULT_CONFIG['quick_think_llm']}")
print(f"LLM: {DEFAULT_CONFIG['backend_url']}")
print(f"Vendors: {DEFAULT_CONFIG['data_vendors']}")
print()

t0 = time.monotonic()
config = DEFAULT_CONFIG.copy()
ta = TradingAgentsGraph(debug=True, config=config)

_, decision = ta.propagate(TICKER, DATE)
elapsed = time.monotonic() - t0

print("\n" + "=" * 70)
print("FINAL DECISION")
print("=" * 70)
print(decision)

# Also write the markdown report tree (like the CLI does).
report_path = ta.save_reports(
    ta.curr_state, TICKER,
    save_path=sys.argv[3] if len(sys.argv) > 3 else None,
)
print(f"\nReports saved to: {report_path}")

# Structured run summary (⑬): machine-readable record for batch analysis.
summary = {
    "ticker": TICKER,
    "trade_date": DATE,
    "elapsed_s": round(elapsed, 1),
    "decision": str(decision),
    "signal": str(ta.process_signal(ta.curr_state["final_trade_decision"])),
    "reports_file": str(report_path),
    "llm": {
        "provider": DEFAULT_CONFIG["llm_provider"],
        "backend_url": DEFAULT_CONFIG.get("backend_url"),
        "deep": DEFAULT_CONFIG["deep_think_llm"],
        "quick": DEFAULT_CONFIG["quick_think_llm"],
        "temperature": DEFAULT_CONFIG.get("temperature"),
    },
    "data_vendors": DEFAULT_CONFIG["data_vendors"],
    "report_sizes": {
        k: len(str(ta.curr_state.get(k, "")))
        for k in ("market_report", "sentiment_report", "news_report", "fundamentals_report")
    },
}
# ``save_reports`` returns the complete_report.md FILE path; the summary sits
# next to it in the same report directory.
summary_path = Path(report_path).parent / "run_summary.json"
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Run summary saved to: {summary_path}")
