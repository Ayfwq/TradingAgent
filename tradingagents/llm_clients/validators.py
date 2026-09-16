"""各服务商的模型名称校验器。"""

import logging

from .model_catalog import get_known_models

logger = logging.getLogger(__name__)

# 模型名称由用户定义的服务商（本地服务器、中继、提供大量模型的托管 OpenAI
# 兼容端点），接受任意模型字符串且不发出警告。
_ANY_MODEL_PROVIDERS = (
    "ollama", "openrouter", "openai_compatible",
    "mistral", "kimi", "groq", "nvidia", "bedrock",
)

VALID_MODELS = {
    provider: models
    for provider, models in get_known_models().items()
    if provider not in _ANY_MODEL_PROVIDERS
}


def validate_model(provider: str, model: str) -> bool:
    """检查模型名称是否对指定服务商有效。

    对 ollama、openrouter 和 openai_compatible，任意模型都可接受。
    """
    provider_lower = provider.lower()
    logger.debug("正在校验服务商 '%s' 的模型 '%s'", provider_lower, model)

    if provider_lower in _ANY_MODEL_PROVIDERS:
        logger.debug("服务商 '%s' 接受任意模型名称", provider_lower)
        return True

    if provider_lower not in VALID_MODELS:
        logger.debug("服务商 '%s' 没有已知模型列表，接受该模型", provider_lower)
        return True

    valid = model in VALID_MODELS[provider_lower]
    logger.debug("模型 '%s' 对服务商 '%s' 是否有效：%s", model, provider_lower, valid)
    return valid
