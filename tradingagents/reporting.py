"""供 Web 和程序 API 共享的可复用报告树写入器。

在 ``save_path`` 下写入每次运行按章节划分的 Markdown（分析师、研究、交易、风险、
投资组合）以及汇总的 ``complete_report.md``。Web 和 ``TradingAgentsGraph.save_reports``
都会调用它，因此不同调用方式生成相同的磁盘报告树。
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def write_report_tree(final_state: dict, ticker: str, save_path) -> Path:
    """将已完成运行的报告保存到 ``save_path``，并返回完整报告路径。"""
    logger.debug("正在将 %s 的报告树写入 %s", ticker, save_path)
    try:
        save_path = Path(save_path)
        save_path.mkdir(parents=True, exist_ok=True)
        sections = []

        # 1. 分析师。
        analysts_dir = save_path / "1_analysts"
        analyst_parts = []
        if final_state.get("market_report"):
            analysts_dir.mkdir(exist_ok=True)
            (analysts_dir / "market.md").write_text(final_state["market_report"], encoding="utf-8")
            analyst_parts.append(("市场分析师", final_state["market_report"]))
        if final_state.get("sentiment_report"):
            analysts_dir.mkdir(exist_ok=True)
            (analysts_dir / "sentiment.md").write_text(final_state["sentiment_report"], encoding="utf-8")
            analyst_parts.append(("情绪分析师", final_state["sentiment_report"]))
        if final_state.get("news_report"):
            analysts_dir.mkdir(exist_ok=True)
            (analysts_dir / "news.md").write_text(final_state["news_report"], encoding="utf-8")
            analyst_parts.append(("新闻分析师", final_state["news_report"]))
        if final_state.get("fundamentals_report"):
            analysts_dir.mkdir(exist_ok=True)
            (analysts_dir / "fundamentals.md").write_text(final_state["fundamentals_report"], encoding="utf-8")
            analyst_parts.append(("基本面分析师", final_state["fundamentals_report"]))
        if analyst_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
            sections.append(f"## 一、分析师团队报告\n\n{content}")

        # 2. 研究。
        if final_state.get("investment_debate_state"):
            research_dir = save_path / "2_research"
            debate = final_state["investment_debate_state"]
            research_parts = []
            if debate.get("bull_history"):
                research_dir.mkdir(exist_ok=True)
                (research_dir / "bull.md").write_text(debate["bull_history"], encoding="utf-8")
                research_parts.append(("看多研究员", debate["bull_history"]))
            if debate.get("bear_history"):
                research_dir.mkdir(exist_ok=True)
                (research_dir / "bear.md").write_text(debate["bear_history"], encoding="utf-8")
                research_parts.append(("看空研究员", debate["bear_history"]))
            if debate.get("judge_decision"):
                research_dir.mkdir(exist_ok=True)
                (research_dir / "manager.md").write_text(debate["judge_decision"], encoding="utf-8")
                research_parts.append(("研究经理", debate["judge_decision"]))
            if research_parts:
                content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
                sections.append(f"## 二、研究团队决策\n\n{content}")

        # 3. 交易。
        if final_state.get("trader_investment_plan"):
            trading_dir = save_path / "3_trading"
            trading_dir.mkdir(exist_ok=True)
            (trading_dir / "trader.md").write_text(final_state["trader_investment_plan"], encoding="utf-8")
            sections.append(f"## 三、交易团队计划\n\n### 交易员\n{final_state['trader_investment_plan']}")

        # 4. 风险管理。
        if final_state.get("risk_debate_state"):
            risk_dir = save_path / "4_risk"
            risk = final_state["risk_debate_state"]
            risk_parts = []
            if risk.get("aggressive_history"):
                risk_dir.mkdir(exist_ok=True)
                (risk_dir / "aggressive.md").write_text(risk["aggressive_history"], encoding="utf-8")
                risk_parts.append(("激进分析师", risk["aggressive_history"]))
            if risk.get("conservative_history"):
                risk_dir.mkdir(exist_ok=True)
                (risk_dir / "conservative.md").write_text(risk["conservative_history"], encoding="utf-8")
                risk_parts.append(("保守分析师", risk["conservative_history"]))
            if risk.get("neutral_history"):
                risk_dir.mkdir(exist_ok=True)
                (risk_dir / "neutral.md").write_text(risk["neutral_history"], encoding="utf-8")
                risk_parts.append(("中性分析师", risk["neutral_history"]))
            if risk_parts:
                content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
                sections.append(f"## 四、风险管理团队决策\n\n{content}")

            # 5. 投资组合经理。
            if risk.get("judge_decision"):
                portfolio_dir = save_path / "5_portfolio"
                portfolio_dir.mkdir(exist_ok=True)
                (portfolio_dir / "decision.md").write_text(risk["judge_decision"], encoding="utf-8")
                sections.append(f"## 五、投资组合经理决策\n\n### 投资组合经理\n{risk['judge_decision']}")

        # 写入汇总报告。
        header = f"# 投研智报分析报告：{ticker}\n\n生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        complete_report = save_path / "complete_report.md"
        complete_report.write_text(header + "\n\n".join(sections), encoding="utf-8")
        metadata = {
            "ticker": ticker,
            "trade_date": str(final_state.get("trade_date", ""))[:10],
            "asset_type": final_state.get("asset_type", "stock"),
            "generated_at": datetime.now().isoformat(sep=" "),
        }
        (save_path / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(
            "报告树已保存到 %s；完整报告 %s（%d 字节）",
            save_path, complete_report.name, complete_report.stat().st_size,
        )
        return complete_report
    except Exception:
        logger.exception("写入 %s 的报告树到 %s 失败", ticker, save_path)
        raise
