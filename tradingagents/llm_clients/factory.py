
import logging

from .base_client import BaseLLMClient

logger = logging.getLogger(__name__)


def create_llm_client(
    provider: str,
    model: str,
    base_url: str | None = None,
    **kwargs,
) -> BaseLLMClient:
    """为指定服务商创建 LLM 客户端。

    服务商模块采用延迟导入，因此仅导入此工厂（例如测试收集期间）不会加载大型
    LLM SDK，也不会因缺少 API 密钥而失败。

    Args:
        provider：LLM 服务商名称。
        model：模型名称/标识符。
        base_url：API 端点的可选基础 URL。
        **kwargs：服务商专属的其他参数。

    Returns:
        已配置的 BaseLLMClient 实例。

    Raises:
        ValueError：不支持该服务商时抛出。
    """
    provider_lower = provider.lower()
    logger.debug("创建 LLM 客户端：服务商=%s 模型=%s 基础 URL=%s", provider_lower, model, base_url)

    # 先匹配原生（非 OpenAI）API，避免字符串检查导入 OpenAI 客户端。其他服务商
    # 都是 OpenAI 兼容接口，并通过服务商注册表（唯一事实来源）路由。
    if provider_lower == "anthropic":
        from .anthropic_client import AnthropicClient
        logger.debug("将服务商 '%s' 分派给 AnthropicClient", provider_lower)
        return AnthropicClient(model, base_url, **kwargs)

    if provider_lower == "google":
        from .google_client import GoogleClient
        logger.debug("将服务商 '%s' 分派给 GoogleClient", provider_lower)
        return GoogleClient(model, base_url, **kwargs)

    if provider_lower == "azure":
        from .azure_client import AzureOpenAIClient
        logger.debug("将服务商 '%s' 分派给 AzureOpenAIClient", provider_lower)
        return AzureOpenAIClient(model, base_url, **kwargs)

    if provider_lower == "bedrock":
        from .bedrock_client import BedrockClient
        logger.debug("将服务商 '%s' 分派给 BedrockClient", provider_lower)
        return BedrockClient(model, base_url, **kwargs)

    from .openai_client import OpenAIClient, is_openai_compatible
    if is_openai_compatible(provider_lower):
        logger.debug("将服务商 '%s' 分派给 OpenAIClient（OpenAI 兼容模式）", provider_lower)
        return OpenAIClient(model, base_url, provider=provider_lower, **kwargs)

    logger.error("不支持的 LLM 服务商：%s", provider)
    raise ValueError(f"不支持的 LLM 服务商：{provider}")
