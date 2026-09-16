"""决策回测：在历史日期运行完整流水线，并根据随后实现的收益为每个决策评分。

这是回答“它能否预测”的客观方式：

对每个历史交易日，完全按照实时运行方式执行整条智能体流水线
（分析师 -> 辩论 -> 研究经理 -> 交易员 -> 风险管理 -> 投资组合经理），
再将决策与未来 20/60/120 天的实际结果比较。

设计说明：
  - Look-ahead safety is inherited from the framework: every data tool is
    filtered to ``curr_date`` (no future prices/news/macros reach the agents).
  - 记忆日志重定向到临时文件，回测不会污染实时决策日志。
  - 持有期按带缓冲的日历天数计算；实际收益查询（akshare/Sina）返回真正使用的交易日。

用法：
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
    """从指定结束日期向前回溯指定月数，每月取 15 日这一相对安全的月中交易日。"""
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
    parser = argparse.ArgumentParser(description="回测 TradingAgents 决策")
    parser.add_argument("--ticker", default="600519.SS")
    parser.add_argument("--dates", default=None, help="以逗号分隔的 YYYY-MM-DD 日期")
    parser.add_argument("--months", type=int, default=0,
                        help="自动生成向前 N 个月的月度日期（每月 15 日）")
    parser.add_argument("--hold", default="20,60",
                        help="以逗号分隔的日历天持有期")
    parser.add_argument("--limit", type=int, default=0,
                        help="最多运行的日期数（0 = 全部）")
    parser.add_argument("--out", default=None, help="输出 CSV 路径")
    args = parser.parse_args()

    ticker = args.ticker
    if args.dates:
        dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    elif args.months:
        dates = _monthly_dates(datetime.now(), args.months)
    else:
        print("请提供 --dates 或 --months")
        return 2
    if args.limit > 0:
        dates = dates[: args.limit]
    holds = [int(h) for h in args.hold.split(",") if h.strip()]
    print(f"回测 {ticker}：{len(dates)} 个日期，持有期={holds} 天")

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
        print(f"\n[{i}/{len(dates)}] 正在运行 {ticker} 在 {trade_date} 的流水线……")
        try:
            final_state, signal = graph.propagate(ticker, trade_date)
        except Exception as exc:  # noqa: BLE001
            print(f"  流水线失败：{type(exc).__name__}：{exc}")
            rows.append({"date": trade_date, "rating": "ERROR", "signal": "ERROR",
                         "reason": f"{type(exc).__name__}: {str(exc)[:120]}"})
            continue

        decision = final_state.get("final_trade_decision", "")
        rating = parse_rating(decision)
        print(f"  评级={rating} 信号={signal}")

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
        print(f"  结果：raw={row.get('raw_%dd' % holds[0])}")

    df = pd.DataFrame(rows)
    out_csv = Path(args.out) if args.out else Path(scratch) / "backtest_results.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"\n=== RESULTS ({len(df)} dates) ===")
    print(df.to_string(index=False))
    print(f"\nCSV 已保存到：{out_csv}")
    print(f"报告目录：{out_dir}")

    # 摘要：BUY（首个持有期 raw>0）/ SELL（raw<0）的方向命中率。
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
            print("\n=== 摘要 ===")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
