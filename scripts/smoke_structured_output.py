"""针对真实 LLM 供应商执行结构化输出智能体的端到端冒烟测试。

直接使用结构化输出绑定运行三个决策智能体（研究经理、交易员、投资组合经理），
并打印每个智能体的类型化 Pydantic 实例及渲染后的 Markdown。可用此脚本验证
供应商原生结构化输出模式（OpenAI / xAI / DeepSeek / Qwen / GLM 使用
json_schema，Gemini 使用 response_schema，Anthropic 使用工具调用）是否能
根据项目提供的 Schema 返回干净的实例。

用法：
    OPENAI_API_KEY=... python scripts/smoke_structured_output.py openai
    GOOGLE_API_KEY=... python scripts/smoke_structured_output.py google
    ANTHROPIC_API_KEY=... python scripts/smoke_structured_output.py anthropic
    DEEPSEEK_API_KEY=... python scripts/smoke_structured_output.py deepseek

脚本不会调用 propagate()，以保持测试范围紧凑并降低成本；它只执行新增的三个
结构化输出调用，以及启发式 SignalProcessor。
"""

from __future__ import annotations

import argparse
import sys

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.trader.trader import create_trader
from tradingagents.graph.signal_processing import SignalProcessor
from tradingagents.llm_clients import create_llm_client

PROVIDER_DEFAULTS = {
    "openai": ("gpt-5.4-mini", None),
    "google": ("gemini-3.5-flash", None),
    "anthropic": ("claude-sonnet-4-6", None),
    "deepseek": ("deepseek-v4-flash", None),
    "qwen": ("qwen3.7-plus", None),
    "glm": ("glm-5", None),
    "xai": ("grok-4.3", None),
}


# 三个智能体使用的最小但真实的状态。
DEBATE_HISTORY = """
看多分析师：NVDA 上季度数据中心收入同比增长 60%，由 Blackwell 放量推动；
与多个政府签署的主权 AI 订单带来超过 400 亿美元的多年顺风。利润率仍高于同业平均水平。

看空分析师：客户集中度风险真实存在——前三大客户贡献超过 40% 的收入。
云服务商资本开支一旦暂停，估值倍数可能收缩。中国出口限制仍限制了相当一部分需求。
"""


def _make_rm_state():
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


def _make_trader_state(investment_plan: str):
    return {
        "company_of_interest": "NVDA",
        "investment_plan": investment_plan,
    }


def _make_pm_state(investment_plan: str, trader_plan: str):
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


def _print_section(title: str, content: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n{title}\n{bar}\n{content}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=list(PROVIDER_DEFAULTS.keys()))
    parser.add_argument("--deep-model", default=None, help="覆盖 deep_think_llm")
    parser.add_argument("--quick-model", default=None, help="覆盖 quick_think_llm")
    args = parser.parse_args()

    default_model, _ = PROVIDER_DEFAULTS[args.provider]
    deep_model = args.deep_model or default_model
    quick_model = args.quick_model or default_model

    print(f"供应商：{args.provider}")
    print(f"深度模型：{deep_model}")
    print(f"快速模型：{quick_model}")

    # 通过框架工厂构建 LLM 客户端。
    deep_client = create_llm_client(provider=args.provider, model=deep_model)
    quick_client = create_llm_client(provider=args.provider, model=quick_model)
    deep_llm = deep_client.get_llm()
    quick_llm = quick_client.get_llm()

    # 1）研究经理
    rm = create_research_manager(deep_llm)
    rm_result = rm(_make_rm_state())
    investment_plan = rm_result["investment_plan"]
    _print_section("[1] 研究经理 —— investment_plan", investment_plan)

    # 2）交易员（使用研究经理的计划）
    trader = create_trader(quick_llm)
    trader_result = trader(_make_trader_state(investment_plan))
    trader_plan = trader_result["trader_investment_plan"]
    _print_section("[2] 交易员 —— trader_investment_plan", trader_plan)

    # 3）投资组合经理（使用前两者的结果）
    pm = create_portfolio_manager(deep_llm)
    pm_result = pm(_make_pm_state(investment_plan, trader_plan))
    final_decision = pm_result["final_trade_decision"]
    _print_section("[3] 投资组合经理 —— final_trade_decision", final_decision)

    # 4）SignalProcessor 在不调用 LLM 的情况下提取评级。
    sp = SignalProcessor()
    rating = sp.process_signal(final_decision)
    _print_section("[4] SignalProcessor → 评级", rating)

    # 5）轻量检查：每个渲染结果都应包含预期的章节标题，确保下游消费者
    #   （记忆日志、Web 显示、保存的报告）继续正常工作。
    checks = [
        ("研究经理", investment_plan, ["**Recommendation**:"]),
        ("交易员",           trader_plan,     ["**Action**:", "FINAL TRANSACTION PROPOSAL:"]),
        ("投资组合经理", final_decision, ["**Rating**:", "**Executive Summary**:", "**Investment Thesis**:"]),
    ]
    print("\n" + "=" * 70 + "\n结构检查\n" + "=" * 70)
    failures = 0
    for name, text, required in checks:
        for marker in required:
            ok = marker in text
            print(f"  {'通过' if ok else '失败'}  {name}：包含 {marker!r}")
            failures += int(not ok)

    print()
    if failures:
        print(f"冒烟测试失败：缺少 {failures} 个结构检查项。")
        return 1
    print("冒烟测试通过：结构化输出 → 渲染 Markdown 链路可用于", args.provider)
    return 0


if __name__ == "__main__":
    sys.exit(main())
