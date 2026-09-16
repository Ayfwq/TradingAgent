"""A 股完整流水线运行器（数据完整、零降级路径）。

使用贵州茅台（600519.SS），以当天日期作为分析日期：
- OHLCV、技术指标、经校验快照、基本面、三大财务报表、个股新闻、全球新闻、
  宏观序列和内部交易全部通过 akshare 供应商来自国内来源（新浪/东方财富/
  金十/雪球），不使用 Yahoo 或海外 API。
- LLM 栈通过配置的端点运行 deepseek（deep=pro，quick=flash）。
- 在报告旁写入结构化运行摘要（run_summary.json）。

用法：uv run python scripts/run_ashare.py [TICKER] [DATE] [SAVE_PATH]
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

print(f"=== A 股流水线：{TICKER} @ {DATE} ===")
print(f"LLM：深度={DEFAULT_CONFIG['deep_think_llm']} 快速={DEFAULT_CONFIG['quick_think_llm']}")
print(f"LLM 端点：{DEFAULT_CONFIG['backend_url']}")
print(f"数据供应商：{DEFAULT_CONFIG['data_vendors']}")
print()

t0 = time.monotonic()
config = DEFAULT_CONFIG.copy()
ta = TradingAgentsGraph(debug=True, config=config)

_, decision = ta.propagate(TICKER, DATE)
elapsed = time.monotonic() - t0

print("\n" + "=" * 70)
print("最终决策")
print("=" * 70)
print(decision)

# 同时写入 Markdown 报告树（与 Web 相同）。
report_path = ta.save_reports(
    ta.curr_state, TICKER,
    save_path=sys.argv[3] if len(sys.argv) > 3 else None,
)
print(f"\n报告已保存到：{report_path}")

# 结构化运行摘要（⑬）：供批量分析使用的机器可读记录。
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
# ``save_reports`` 返回 complete_report.md 文件路径；摘要位于同一报告目录中。
summary_path = Path(report_path).parent / "run_summary.json"
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"运行摘要已保存到：{summary_path}")
