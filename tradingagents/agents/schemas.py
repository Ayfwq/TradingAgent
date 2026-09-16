"""生成结构化输出的 Agent 所使用的 Pydantic schema。

框架的主要产物仍然是自然语言文本：用户会阅读已保存 Markdown 报告中的推理，
下游 Agent 也会把它作为上下文。结构化输出叠加在三个决策 Agent（研究经理、
交易员、投资组合经理）之上，以确保：

- 不同运行和服务商都使用一致的输出章节；
- 使用各服务商的原生结构化输出模式（OpenAI/xAI 使用 json_schema，Gemini 使用
  response_schema，Anthropic 使用 tool-use）；
- schema 字段描述成为模型的输出指令，让提示词正文可以专注于上下文和评级尺度；
- 渲染辅助函数将解析后的 Pydantic 实例转换回系统已有的 Markdown 结构，保证展示、
  记忆日志和已保存报告继续正常工作。
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# LLM 有时会把占位字符串（"None"、"N/A" 等）写入可选数值字段，而不是省略字段。
# 将这些值转换为 None，使结构化调用可以通过校验而不是报错（#1058）。Pydantic
# 仍会把真实数字字符串（"189.5"）解析为 float。
_NULLISH_FLOAT = {"", "none", "n/a", "na", "null", "nil", "-", "tbd", "unknown"}


def _coerce_optional_float(value):
    if isinstance(value, str) and value.strip().lower() in _NULLISH_FLOAT:
        logger.debug("_coerce_optional_float 已将类空值 %r 转换为 None", value)
        return None
    return value


# ---------------------------------------------------------------------------
# 共享评级类型
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """研究经理和投资组合经理使用的五档评级。"""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """交易员使用的三档交易方向。

    交易员负责将研究经理的投资计划转化为具体交易提案：本轮交易台应买入、卖出
    还是持有。仓位大小以及更细致的 Overweight / Underweight 判断由投资组合
    经理稍后完成。
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


# ---------------------------------------------------------------------------
# 研究经理
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """研究经理生成的结构化投资计划。

    交接给交易员时，recommendation 固定方向判断，rationale 说明看多/看空辩论中
    哪一方的论据占优，strategic_actions 则将其转化为交易员可以执行的具体指令。
    """

    recommendation: PortfolioRating = Field(
        description=(
            "投资建议。必须且只能选择 Buy / Overweight / Hold / Underweight / Sell 之一。"
            "只有双方证据确实均衡时才使用 Hold，否则应选择论据更有力的一方。"
        ),
    )
    rationale: str = Field(
        description=(
            "以对话方式总结辩论双方的关键观点，并在结尾说明哪些论据促成了该建议。"
            "请自然表达，就像在向队友说明一样。"
        ),
    )
    strategic_actions: str = Field(
        description=(
            "交易员执行该建议时应采取的具体步骤，包括与评级一致的仓位指导。"
        ),
    )


def render_research_plan(plan: ResearchPlan) -> str:
    """将 ResearchPlan 渲染为 Markdown，供存储和交易员提示词使用。"""
    logger.debug(
        "已调用 render_research_plan：recommendation=%s", plan.recommendation.value,
    )
    result = "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ])
    logger.debug("render_research_plan 已生成 %d 个字符", len(result))
    return result


# ---------------------------------------------------------------------------
# 交易员
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """交易员生成的结构化交易提案。

    交易员读取研究经理的投资计划和分析师报告，然后将它们转化为具体交易：采取
    什么行动、支持该行动的理由，以及实际的入场价、止损价和仓位水平。
    """

    action: TraderAction = Field(
        description="交易方向。必须且只能选择 Buy / Hold / Sell 之一。",
    )
    reasoning: str = Field(
        description=(
            "支持该行动的理由，必须以分析师报告和研究计划为依据。使用两到四句话。"
        ),
    )
    entry_price: float | None = Field(
        default=None,
        description="可选的入场价格目标，单位为该标的的报价货币。",
    )
    stop_loss: float | None = Field(
        default=None,
        description="可选的止损价格，单位为该标的的报价货币。",
    )
    position_sizing: str | None = Field(
        default=None,
        description="可选的仓位指导，例如“占投资组合的 5%”。",
    )

    @field_validator("entry_price", "stop_loss", mode="before")
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)


def render_trader_proposal(proposal: TraderProposal) -> str:
    """将 TraderProposal 渲染为 Markdown。

    末尾的 ``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` 行为兼容分析师停止
    信号文本以及通过 grep 查找该文本的外部代码而保留。
    """
    logger.debug("已调用 render_trader_proposal：action=%s", proposal.action.value)
    parts = [
        f"**Action**: {proposal.action.value}",
        "",
        f"**Reasoning**: {proposal.reasoning}",
    ]
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.position_sizing:
        parts.extend(["", f"**Position Sizing**: {proposal.position_sizing}"])
    parts.extend([
        "",
        f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**",
    ])
    result = "\n".join(parts)
    logger.debug("render_trader_proposal 已生成 %d 个字符", len(result))
    return result


# ---------------------------------------------------------------------------
# 投资组合经理
# ---------------------------------------------------------------------------


class PortfolioDecision(BaseModel):
    """投资组合经理生成的结构化输出。

    模型会在主要 LLM 调用中填写全部字段，不需要单独的提取步骤。字段描述同时
    充当模型的输出指令，因此提示词正文只需传递上下文和评级尺度说明。
    """

    rating: PortfolioRating = Field(
        description=(
            "最终仓位评级。必须根据分析师辩论选择 Buy / Overweight / Hold / Underweight / Sell 之一。"
        ),
    )
    executive_summary: str = Field(
        description=(
            "简洁的行动计划，涵盖入场策略、仓位大小、关键风险水平和持有周期。使用两到四句话。"
        ),
    )
    investment_thesis: str = Field(
        description=(
            "以分析师辩论中的具体证据为依据进行详细推理。如果提示词上下文提供了过往经验，"
            "请将其纳入分析；否则只依赖当前分析。"
        ),
    )
    price_target: float | None = Field(
        default=None,
        description="可选的目标价格，单位为该标的的报价货币。",
    )
    time_horizon: str | None = Field(
        default=None,
        description="可选的建议持有周期，例如“3-6 个月”。",
    )

    @field_validator("price_target", mode="before")
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)


def render_pm_decision(decision: PortfolioDecision) -> str:
    """将 PortfolioDecision 渲染回系统其余部分所需的 Markdown 结构。

    记忆日志、Web 展示和已保存报告文件都会读取该 Markdown，因此渲染结果保留
    下游解析器和报告写入器已经支持的精确章节标识（``**Rating**``、
    ``**Executive Summary**``、``**Investment Thesis**``）。
    """
    logger.debug("已调用 render_pm_decision：rating=%s", decision.rating.value)
    parts = [
        f"**Rating**: {decision.rating.value}",
        "",
        f"**Executive Summary**: {decision.executive_summary}",
        "",
        f"**Investment Thesis**: {decision.investment_thesis}",
    ]
    if decision.price_target is not None:
        parts.extend(["", f"**Price Target**: {decision.price_target}"])
    if decision.time_horizon:
        parts.extend(["", f"**Time Horizon**: {decision.time_horizon}"])
    result = "\n".join(parts)
    logger.debug("render_pm_decision 已生成 %d 个字符", len(result))
    return result


# ---------------------------------------------------------------------------
# 情绪分析师
# ---------------------------------------------------------------------------


class SentimentBand(str, Enum):
    """情绪分析师生成的离散情绪方向。

    六个等级既能让信号足够细致、便于执行，又能让各服务商可靠地从 JSON 输出映射。
    """

    BULLISH = "Bullish"
    MILDLY_BULLISH = "Mildly Bullish"
    NEUTRAL = "Neutral"
    MIXED = "Mixed"
    MILDLY_BEARISH = "Mildly Bearish"
    BEARISH = "Bearish"


class SentimentReport(BaseModel):
    """情绪分析师生成的结构化情绪报告。

    它替代原来的自由文本输出，使下游消费者（仪表盘、审计日志、PDF 渲染器和
    其他 Agent）可以直接读取 ``overall_band`` 和 ``overall_score``，不再维护
    会随着模型版本变化而失效的脆弱正则回退。``narrative`` 保留丰富的逐来源
    分析，``render_sentiment_report`` 添加确定性的标题，使保存的报告易于阅读。
    """

    overall_band: SentimentBand = Field(
        description=(
            "总体情绪方向。必须且只能选择 Bullish / Mildly Bullish / Neutral / Mixed / "
            "Mildly Bearish / Bearish 之一。来源明确指向不同方向时使用 Mixed；只有所有来源确实沉默或不明确时才使用 Neutral。"
        ),
    )
    overall_score: float = Field(
        ge=0.0,
        le=10.0,
        description=(
            "0–10 范围的数值情绪强度。0 = 极度看空，5 = 中性，10 = 极度看多。"
            "为保持与 overall_band 一致，建议：Bullish 约 6.5–10，Mildly Bullish 约 5.5–6.4，"
            "Neutral/Mixed 约 4.5–5.5，Mildly Bearish 约 3.5–4.4，Bearish 约 0–3.4。"
            "系统只强制校验 0–10 边界。"
        ),
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description=(
            "根据数据质量和样本量判断评估置信度。当一个或多个来源返回占位符或少于 5 个数据点时使用 'low'；"
            "数据存在但较稀疏时使用 'medium'；三个来源都返回实质数据时使用 'high'。"
        ),
    )
    narrative: str = Field(
        description=(
            "完整情绪报告，按以下顺序涵盖：(1) 逐来源拆解并提供具体证据（引用消息数、比例和重要帖子）；"
            "(2) 来源之间的分歧与一致；(3) 主导叙事主题；(4) 数据揭示的催化剂和风险；"
            "(5) 用 Markdown 表格总结关键情绪信号、方向、来源和支持证据。"
            "报告应有信息量且内容扎实，每个部分都要用具体证据充分展开，为交易员提供新的有效信号。"
        ),
    )


def render_sentiment_report(report: SentimentReport) -> str:
    """将 SentimentReport 渲染为系统其余部分所需的 Markdown 结构。

    将结构化标题（区间、分数和置信度）添加到叙述前，使已保存报告既易于阅读，
    又可以在不使用正则的情况下由机器解析。
    """
    logger.debug(
        "已调用 render_sentiment_report：band=%s，score=%s，confidence=%s",
        report.overall_band.value, report.overall_score, report.confidence,
    )
    result = "\n".join([
        f"**Overall Sentiment:** **{report.overall_band.value}** "
        f"(Score: {report.overall_score:.1f}/10)",
        f"**Confidence:** {report.confidence.capitalize()}",
        "",
        report.narrative,
    ])
    logger.debug("render_sentiment_report 已生成 %d 个字符", len(result))
    return result
