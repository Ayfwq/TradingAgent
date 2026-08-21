import logging

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

logger = logging.getLogger(__name__)

# DEFAULT_CONFIG already applies TRADINGAGENTS_* env-var overrides
# (llm_provider, deep_think_llm, quick_think_llm, backend_url, etc.),
# so users can switch models or endpoints purely via .env without
# editing this script. Override individual keys here only when you
# want a hard-coded value that should ignore the environment.
config = DEFAULT_CONFIG.copy()

# Initialize with custom config
logger.info("Initializing TradingAgentsGraph with provider=%s deep=%s quick=%s",
            config.get("llm_provider"), config.get("deep_think_llm"), config.get("quick_think_llm"))
ta = TradingAgentsGraph(debug=True, config=config)

# forward propagate
logger.info("Starting propagate for NVDA / 2024-05-10")
_, decision = ta.propagate("NVDA", "2024-05-10")
logger.info("propagate finished; decision=%s", decision)
print(decision)

# Memorize mistakes and reflect
# ta.reflect_and_remember(1000) # parameter is the position returns
