"""Model name validators for each provider."""

import logging

from .model_catalog import get_known_models

logger = logging.getLogger(__name__)

# Providers whose model names are user-defined (local servers, relays, hosted
# OpenAI-compatible endpoints serving many models), so any model string is
# accepted without warning.
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
    """Check if model name is valid for the given provider.

    For ollama, openrouter, and openai_compatible - any model is accepted.
    """
    provider_lower = provider.lower()
    logger.debug("Validating model '%s' for provider '%s'", model, provider_lower)

    if provider_lower in _ANY_MODEL_PROVIDERS:
        logger.debug("Provider '%s' accepts any model name", provider_lower)
        return True

    if provider_lower not in VALID_MODELS:
        logger.debug("Provider '%s' has no known-model list; accepting model", provider_lower)
        return True

    valid = model in VALID_MODELS[provider_lower]
    logger.debug("Model '%s' valid for provider '%s': %s", model, provider_lower, valid)
    return valid
