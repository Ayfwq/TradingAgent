"""规范的服务商 -> API 密钥环境变量映射。

这是每个受支持 LLM 服务商 API 密钥环境变量的唯一事实来源，供所有需要判断
“服务商是否需要密钥、对应哪个环境变量”的代码使用。

新增服务商时应在这里登记其环境变量，避免首次 API 调用时因缺少映射而失败。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PROVIDER_API_KEY_ENV: dict[str, str | None] = {
    "openai":     "OPENAI_API_KEY",
    "anthropic":  "ANTHROPIC_API_KEY",
    "google":     "GOOGLE_API_KEY",
    "azure":      "AZURE_OPENAI_API_KEY",
    # Bedrock 通过 AWS 凭证链认证，不使用单一密钥环境变量。
    "bedrock":    None,
    "xai":        "XAI_API_KEY",
    "deepseek":   "DEEPSEEK_API_KEY",
    # 双区域服务商各自对应独立账户；国际端点和中国端点的密钥不能互换。
    "qwen":       "DASHSCOPE_API_KEY",
    "qwen-cn":    "DASHSCOPE_CN_API_KEY",
    "glm":        "ZHIPU_API_KEY",
    "glm-cn":     "ZHIPU_CN_API_KEY",
    "minimax":    "MINIMAX_API_KEY",
    "minimax-cn": "MINIMAX_CN_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    # 其他托管的 OpenAI 兼容服务商（模型由用户指定）。
    # kimi -> Moonshot AI；nvidia -> NVIDIA NIM。
    "mistral":    "MISTRAL_API_KEY",
    "kimi":       "MOONSHOT_API_KEY",
    "groq":       "GROQ_API_KEY",
    "nvidia":     "NVIDIA_API_KEY",
    # 本地运行时不需要认证。
    "ollama":     None,
    # 通用 OpenAI 兼容端点：设置后客户端会读取（用于需要密钥的中继），但服务商
    # 注册表将其标记为可选，无密钥本地服务器也能运行。
    "openai_compatible": "OPENAI_COMPATIBLE_API_KEY",
}


def get_api_key_env(provider: str) -> str | None:
    """返回 `provider` API 密钥对应的环境变量名，不适用时返回 None。

    未知服务商同样返回 None；调用方应将其理解为“无法检查密钥”，而不是“不需要密钥”。
    """
    result = PROVIDER_API_KEY_ENV.get(provider.lower())
    logger.debug("已解析服务商 '%s' 的 API 密钥环境变量：%s", provider, result)
    return result
