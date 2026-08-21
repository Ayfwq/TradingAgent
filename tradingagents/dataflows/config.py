import logging
from copy import deepcopy

import tradingagents.default_config as default_config

logger = logging.getLogger(__name__)

# Use default config but allow it to be overridden
_config: dict | None = None


def initialize_config():
    """Initialize the configuration with default values."""
    global _config
    if _config is None:
        _config = deepcopy(default_config.DEFAULT_CONFIG)
        logger.debug("config initialized from default_config (%d keys)", len(_config))


def set_config(config: dict):
    """Update the configuration with custom values.

    Dict-valued keys (e.g. ``data_vendors``) are merged one level deep so a
    partial update like ``{"data_vendors": {"core_stock_apis": "alpha_vantage"}}``
    keeps the other nested keys from the default; scalar keys are replaced.
    """
    global _config
    initialize_config()
    incoming = deepcopy(config)
    logger.debug("set_config called with %d top-level keys", len(incoming))
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(_config.get(key), dict):
            _config[key].update(value)
        else:
            _config[key] = value


def get_config() -> dict:
    """Get the current configuration."""
    if _config is None:
        logger.debug("config cache miss; re-initializing from defaults")
        initialize_config()
    return deepcopy(_config)


# Initialize with default config
initialize_config()
