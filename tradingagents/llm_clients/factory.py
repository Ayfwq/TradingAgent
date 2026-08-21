
import logging

from .base_client import BaseLLMClient

logger = logging.getLogger(__name__)


def create_llm_client(
    provider: str,
    model: str,
    base_url: str | None = None,
    **kwargs,
) -> BaseLLMClient:
    """Create an LLM client for the specified provider.

    Provider modules are imported lazily so that simply importing this
    factory (e.g. during test collection) does not pull in heavy LLM SDKs
    or fail when their API keys are absent.

    Args:
        provider: LLM provider name
        model: Model name/identifier
        base_url: Optional base URL for API endpoint
        **kwargs: Additional provider-specific arguments

    Returns:
        Configured BaseLLMClient instance

    Raises:
        ValueError: If provider is not supported
    """
    provider_lower = provider.lower()
    logger.debug("Creating LLM client: provider=%s model=%s base_url=%s", provider_lower, model, base_url)

    # Native (non-OpenAI) APIs are matched first so their string check doesn't
    # import the OpenAI client. Everything else is OpenAI-compatible and routes
    # through the provider registry (single source of truth).
    if provider_lower == "anthropic":
        from .anthropic_client import AnthropicClient
        logger.debug("Dispatching provider '%s' to AnthropicClient", provider_lower)
        return AnthropicClient(model, base_url, **kwargs)

    if provider_lower == "google":
        from .google_client import GoogleClient
        logger.debug("Dispatching provider '%s' to GoogleClient", provider_lower)
        return GoogleClient(model, base_url, **kwargs)

    if provider_lower == "azure":
        from .azure_client import AzureOpenAIClient
        logger.debug("Dispatching provider '%s' to AzureOpenAIClient", provider_lower)
        return AzureOpenAIClient(model, base_url, **kwargs)

    if provider_lower == "bedrock":
        from .bedrock_client import BedrockClient
        logger.debug("Dispatching provider '%s' to BedrockClient", provider_lower)
        return BedrockClient(model, base_url, **kwargs)

    from .openai_client import OpenAIClient, is_openai_compatible
    if is_openai_compatible(provider_lower):
        logger.debug("Dispatching provider '%s' to OpenAIClient (OpenAI-compatible)", provider_lower)
        return OpenAIClient(model, base_url, provider=provider_lower, **kwargs)

    logger.error("Unsupported LLM provider: %s", provider)
    raise ValueError(f"Unsupported LLM provider: {provider}")
