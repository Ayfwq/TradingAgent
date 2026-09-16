import logging
from copy import deepcopy

import tradingagents.default_config as default_config

logger = logging.getLogger(__name__)

# 使用默认配置，同时允许覆盖。
_config: dict | None = None


def initialize_config():
    """使用默认值初始化配置。"""
    global _config
    if _config is None:
        _config = deepcopy(default_config.DEFAULT_CONFIG)
        logger.debug("已从 default_config 初始化配置（%d 个键）", len(_config))


def set_config(config: dict):
    """使用自定义值更新配置。

    字典类型的键（例如 ``data_vendors``）会合并一层，因此类似
    ``{"data_vendors": {"core_stock_apis": "alpha_vantage"}}`` 的部分更新
    会保留默认的其他嵌套键；标量键则直接替换。
    """
    global _config
    initialize_config()
    incoming = deepcopy(config)
    logger.debug("调用 set_config，包含 %d 个顶层键", len(incoming))
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(_config.get(key), dict):
            _config[key].update(value)
        else:
            _config[key] = value


def get_config() -> dict:
    """获取当前配置。"""
    if _config is None:
        logger.debug("配置缓存未命中，正在从默认值重新初始化")
        initialize_config()
    return deepcopy(_config)


# 使用默认配置初始化。
initialize_config()
