"""共用的五级评级词汇与确定性启发式解析器。

研究经理（投资计划建议）、投资组合经理（最终仓位决策）、信号处理器
（为下游消费者提取评级）和记忆日志（在决策条目旁保存评级标签）统一使用
Buy、Overweight、Hold、Underweight、Sell 五级尺度。

将其集中维护可以避免这些调用点之间出现偏差。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 标准的五级有序尺度（从最看多到最看空）。
RATINGS_5_TIER: tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

_RATING_SET = {r.lower() for r in RATINGS_5_TIER}

# 匹配“Rating: X”/“rating - X”/“Rating: **X**”，兼容 Markdown 加粗标记
# 以及冒号或连字符分隔符。
_RATING_LABEL_RE = re.compile(r"rating.*?[:\-][\s*]*(\w+)", re.IGNORECASE)


def parse_rating(text: str, default: str = "Hold") -> str:
    """从自然语言文本中启发式提取五级评级。

    分两轮处理：
    1. 查找明确的“Rating: X”标签（兼容 Markdown 加粗）。
    2. 如果没有标签，则使用文本中出现的第一个五级评级词。

    返回首字母大写的评级字符串；如果没有评级词，则返回 ``default``。
    """
    logger.debug("已调用 parse_rating：文本长度=%d，默认值=%s", len(text), default)
    for line in text.splitlines():
        m = _RATING_LABEL_RE.search(line)
        if m and m.group(1).lower() in _RATING_SET:
            rating = m.group(1).capitalize()
            logger.debug("parse_rating 通过标签解析出评级=%s", rating)
            return rating

    for line in text.splitlines():
        for word in line.lower().split():
            clean = word.strip("*:.,")
            if clean in _RATING_SET:
                rating = clean.capitalize()
                logger.debug("parse_rating 通过关键词解析出评级=%s", rating)
                return rating

    logger.debug("parse_rating 回退到默认值=%s", default)
    return default
