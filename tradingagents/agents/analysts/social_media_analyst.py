"""重命名模块的向后兼容适配层。

Agent 现在位于 sentiment_analyst，会将 Yahoo Finance 新闻、StockTwits cashtag 信息流
和 Reddit 帖子汇总为一份情绪报告。后续请从对应的 sentiment_analyst 模块导入；
本模块将在未来版本删除。

See: https://github.com/TauricResearch/TradingAgents/issues/557
"""

import logging
import warnings as _warnings

from tradingagents.agents.analysts.sentiment_analyst import (  # noqa: F401
    create_sentiment_analyst,
    create_social_media_analyst,
)

logger = logging.getLogger(__name__)

_warnings.warn(
    "tradingagents.agents.analysts.social_media_analyst is deprecated. "
    "Import from tradingagents.agents.analysts.sentiment_analyst instead.",
    DeprecationWarning,
    stacklevel=2,
)
logger.warning(
    "tradingagents.agents.analysts.social_media_analyst is deprecated; "
    "import from tradingagents.agents.analysts.sentiment_analyst instead"
)
