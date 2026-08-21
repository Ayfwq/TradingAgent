"""Backwards-compatibility shim for the renamed module.

The agent is now ``sentiment_analyst`` and aggregates Yahoo Finance news,
StockTwits cashtag streams, and Reddit posts into a single sentiment
report. Import from ``tradingagents.agents.analysts.sentiment_analyst``
going forward; this module will be removed in a future release.

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
