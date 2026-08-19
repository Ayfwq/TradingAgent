"""Multi-agent pipeline smoke against the configured LLM endpoint.

Runs the decision chain Research Manager -> Trader -> Portfolio Manager ->
SignalProcessor through the framework's own factories, using the endpoint /
model from .env (provider=deepseek, backend_url, deepseek-v4-flash). No
market-data vendors involved, so it works even when Yahoo Finance is
rate-limited from the current network.

Usage:  uv run python scripts/smoke_pipeline.py
"""

import tradingagents  # noqa: F401  (loads .env)

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.trader.trader import create_trader
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.signal_processing import SignalProcessor
from tradingagents.llm_clients import create_llm_client

DEBATE_HISTORY = """
Bull Analyst: NVDA's data-center revenue grew 60% YoY last quarter, driven by
Blackwell ramp; sovereign AI deals add a $40B+ multi-year tailwind. Margins
remain above peer average.

Bear Analyst: Concentration risk is real — top three customers are >40% of
revenue. Any pause in hyperscaler capex would compress the multiple. China
export restrictions still cap a meaningful portion of demand.
"""


def make_rm_state():
    return {
        "company_of_interest": "NVDA",
        "investment_debate_state": {
            "history": DEBATE_HISTORY,
            "bull_history": "Bull Analyst: NVDA's data-center revenue grew 60% YoY...",
            "bear_history": "Bear Analyst: Concentration risk is real...",
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
            "history": "Aggressive: lean in. Conservative: trim. Neutral: balanced sizing.",
            "aggressive_history": "Aggressive: ...",
            "conservative_history": "Conservative: ...",
            "neutral_history": "Neutral: ...",
            "judge_decision": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "count": 1,
        },
        "market_report": "Market report.",
        "sentiment_report": "Sentiment report.",
        "news_report": "News report.",
        "fundamentals_report": "Fundamentals report.",
        "investment_plan": investment_plan,
        "trader_investment_plan": trader_plan,
    }


def main():
    print("=== Config ===")
    print("provider   :", DEFAULT_CONFIG["llm_provider"])
    print("deep model :", DEFAULT_CONFIG["deep_think_llm"])
    print("quick model:", DEFAULT_CONFIG["quick_think_llm"])
    print("backend_url:", DEFAULT_CONFIG["backend_url"])
    print()

    def build(model):
        return create_llm_client(
            provider=DEFAULT_CONFIG["llm_provider"],
            model=model,
            base_url=DEFAULT_CONFIG.get("backend_url"),
        ).get_llm()

    deep_llm = build(DEFAULT_CONFIG["deep_think_llm"])
    quick_llm = build(DEFAULT_CONFIG["quick_think_llm"])

    print("[1/4] Research Manager (deep LLM, structured output) ...")
    rm = create_research_manager(deep_llm)
    investment_plan = rm(make_rm_state())["investment_plan"]
    print("      ->", investment_plan.splitlines()[0][:90])

    print("[2/4] Trader (quick LLM, structured output) ...")
    trader = create_trader(quick_llm)
    trader_plan = trader(make_trader_state(investment_plan))["trader_investment_plan"]
    print("      ->", trader_plan.splitlines()[0][:90])

    print("[3/4] Portfolio Manager (deep LLM, structured output) ...")
    pm = create_portfolio_manager(deep_llm)
    final_decision = pm(make_pm_state(investment_plan, trader_plan))["final_trade_decision"]
    print("      ->", final_decision.splitlines()[0][:90])

    print("[4/4] SignalProcessor (heuristic, no LLM) ...")
    rating = SignalProcessor().process_signal(final_decision)
    print("      -> rating:", rating)

    checks = [
        ("Research Manager", investment_plan, ["**Recommendation**:"]),
        ("Trader", trader_plan, ["**Action**:", "FINAL TRANSACTION PROPOSAL:"]),
        ("Portfolio Manager", final_decision,
         ["**Rating**:", "**Executive Summary**:", "**Investment Thesis**:"]),
    ]
    failures = 0
    print()
    for name, text, required in checks:
        for marker in required:
            ok = marker in text
            print(f"  {'PASS' if ok else 'FAIL'}  {name}: contains {marker!r}")
            failures += int(not ok)

    print()
    if failures:
        print(f"SMOKE FAILED: {failures} structure check(s) missing.")
        return 1
    print("SMOKE PASSED: multi-agent decision chain works on deepseek-v4-flash @ "
          f"{DEFAULT_CONFIG['backend_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
