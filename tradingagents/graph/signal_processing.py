"""从投资组合经理的决策中提取五级投资组合评级。

投资组合经理通过结构化输出生成类型化的 ``PortfolioDecision``，并将其渲染为始终
包含 ``**Rating**: X`` 标题的 Markdown（参见 :func:`tradingagents.agents.schemas.render_pm_decision`）。
``tradingagents.agents.utils.rating`` 中的确定性启发式足以提取评级，无需额外的 LLM 调用。

本模块用于兼容仍期待 ``SignalProcessor.process_signal(text)`` 接口的调用方。
"""

from __future__ import annotations

import logging
from typing import Any

from tradingagents.agents.utils.rating import parse_rating

logger = logging.getLogger(__name__)


class SignalProcessor:
    """从投资组合经理决策中读取五级评级。"""

    def __init__(self, quick_thinking_llm: Any = None):
        # 保留 LLM 参数以兼容旧调用，但不再使用：投资组合经理的结构化输出保证
        # 可以从渲染后的 Markdown 中解析评级，无需第二次 LLM 调用。
        self.quick_thinking_llm = quick_thinking_llm
        logger.debug("SignalProcessor 已初始化")

    def process_signal(self, full_signal: str) -> str:
        """返回 Buy / Overweight / Hold / Underweight / Sell 之一。"""
        rating = parse_rating(full_signal)
        logger.debug("已从投资组合经理决策解析评级：%s", rating)
        return rating
