"""针对配置的 LLM 端点执行多智能体流水线冒烟测试。

通过框架自身的工厂运行决策链：研究经理 -> 交易员 -> 投资组合经理 ->
SignalProcessor，使用 .env 中的端点/模型（provider=deepseek、backend_url、
deepseek-v4-flash）。不涉及市场数据供应商，因此即使当前网络下 Yahoo Finance
受到限流也可以运行。

用法：uv run python scripts/smoke_pipeline.py
"""

import tradingagents  # noqa: F401  (loads .env)

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.trader.trader import create_trader
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.signal_processing import SignalProcessor
from tradingagents.llm_clients import create_llm_client

DEBATE_HISTORY = """
看多分析师：NVDA 上季度数据中心收入同比增长 60%，由 Blackwell 放量推动；
主权 AI 订单带来超过 400 亿美元的多年顺风。利润率仍高于同业平均水平。

看空分析师：客户集中度风险真实存在——前三大客户贡献超过 40% 的收入。
云服务商资本开支一旦暂停，估值倍数可能收缩。中国出口限制仍限制了相当一部分需求。
"""


def make_rm_state():
    return {
        "company_of_interest": "NVDA",
        "investment_debate_state": {
            "history": DEBATE_HISTORY,
            "bull_history": "看多分析师：NVDA 数据中心收入同比增长 60%……",
            "bear_history": "看空分析师：客户集中度风险真实存在……",
            "current_response": "",
            "judge_decision": "",
            "count": 1,
        },
    }


def make_trader_state(investment_plan: str):
    return {"company_of_interest": "NVDA", "investment_plan": investment_plan}


def make_pm_state(investment_plan: str, trader_plan: str):
    return {
        "company_of_interest": "NVDA",
        "past_context": "",
        "risk_debate_state": {
            "history": "激进：增加仓位。保守：减仓。中性：均衡配置。",
            "aggressive_history": "激进：……",
            "conservative_history": "保守：……",
            "neutral_history": "中性：……",
            "judge_decision": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "count": 1,
        },
        "market_report": "市场报告。",
        "sentiment_report": "情绪报告。",
        "news_report": "新闻报告。",
        "fundamentals_report": "基本面报告。",
        "investment_plan": investment_plan,
        "trader_investment_plan": trader_plan,
    }


def main():
    print("=== 配置 ===")
    print("供应商    ：", DEFAULT_CONFIG["llm_provider"])
    print("深度模型  ：", DEFAULT_CONFIG["deep_think_llm"])
    print("快速模型  ：", DEFAULT_CONFIG["quick_think_llm"])
    print("backend_url：", DEFAULT_CONFIG["backend_url"])
    print()

    def build(model):
        return create_llm_client(
            provider=DEFAULT_CONFIG["llm_provider"],
            model=model,
            base_url=DEFAULT_CONFIG.get("backend_url"),
        ).get_llm()

    deep_llm = build(DEFAULT_CONFIG["deep_think_llm"])
    quick_llm = build(DEFAULT_CONFIG["quick_think_llm"])

    print("[1/4] 研究经理（深度 LLM，结构化输出）……")
    rm = create_research_manager(deep_llm)
    investment_plan = rm(make_rm_state())["investment_plan"]
    print("      ->", investment_plan.splitlines()[0][:90])

    print("[2/4] 交易员（快速 LLM，结构化输出）……")
    trader = create_trader(quick_llm)
    trader_plan = trader(make_trader_state(investment_plan))["trader_investment_plan"]
    print("      ->", trader_plan.splitlines()[0][:90])

    print("[3/4] 投资组合经理（深度 LLM，结构化输出）……")
    pm = create_portfolio_manager(deep_llm)
    final_decision = pm(make_pm_state(investment_plan, trader_plan))["final_trade_decision"]
    print("      ->", final_decision.splitlines()[0][:90])

    print("[4/4] SignalProcessor（启发式，不调用 LLM）……")
    rating = SignalProcessor().process_signal(final_decision)
    print("      -> rating:", rating)

    checks = [
        ("研究经理", investment_plan, ["**Recommendation**:"]),
        ("交易员", trader_plan, ["**Action**:", "FINAL TRANSACTION PROPOSAL:"]),
        ("投资组合经理", final_decision,
         ["**Rating**:", "**Executive Summary**:", "**Investment Thesis**:"]),
    ]
    failures = 0
    print()
    for name, text, required in checks:
        for marker in required:
            ok = marker in text
            print(f"  {'通过' if ok else '失败'}  {name}：包含 {marker!r}")
            failures += int(not ok)

    print()
    if failures:
        print(f"冒烟测试失败：缺少 {failures} 个结构检查项。")
        return 1
    print("冒烟测试通过：多智能体决策链可在 deepseek-v4-flash @ "
          f"{DEFAULT_CONFIG['backend_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
