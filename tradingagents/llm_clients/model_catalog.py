"""供模型选择与校验共用的模型目录。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

ModelOption = tuple[str, str]
ProviderModeOptions = dict[str, dict[str, list[ModelOption]]]

# 提供大量或频繁变化模型的供应商只提供“自定义模型 ID”，避免下拉列表过时。
_CUSTOM_ONLY: dict[str, list[ModelOption]] = {
    "quick": [("自定义模型 ID", "custom")],
    "deep": [("自定义模型 ID", "custom")],
}


# Z.AI（国际）与 BigModel（中国）共用的 GLM 模型列表。
# 来源：docs.z.ai（GLM Coding Plan 支持的模型及 LLM 指南）。
# GLM 4.7 及以上条目均支持通过 thinking={"type":"enabled"} 开启思考模式。
_GLM_MODELS: dict[str, list[ModelOption]] = {
    "quick": [
        ("GLM-5-Turbo - 快速，可切换思考模式", "glm-5-turbo"),
        ("GLM-4.7 - 上一代旗舰模型", "glm-4.7"),
        ("GLM-4.5-Air - 轻量且高性价比", "glm-4.5-air"),
        ("自定义模型 ID", "custom"),
    ],
    "deep": [
        ("GLM-5.2 - 最新旗舰模型，1M 上下文", "glm-5.2"),
        ("GLM-5.1 - 745B，200K 上下文", "glm-5.1"),
        ("GLM-5 - 旗舰模型，204K 上下文", "glm-5"),
        ("GLM-4.7 - 上一代旗舰模型", "glm-4.7"),
        ("自定义模型 ID", "custom"),
    ],
}


# Qwen 全球（dashscope-intl）与中国（dashscope）端点共用的模型列表。
# 来源：modelstudio.console.alibabacloud.com（精选模型——旗舰与高性价比）。
#
# 下拉列表只展示带版本号的 ID。不带版本号的别名（qwen-plus、qwen-flash）
# 会自动升级，因此阿里巴巴轮换底层模型时其行为会发生变化。需要固定代际
# 的用户应明确选择版本；需要自动使用最新版本的用户可以通过“自定义模型 ID”
# 输入别名。
_QWEN_MODELS: dict[str, list[ModelOption]] = {
    "quick": [
        ("Qwen 3.7 Plus - 最新版本，速度与成本均衡", "qwen3.7-plus"),
        ("Qwen 3.6 Plus - 上一代均衡模型", "qwen3.6-plus"),
        ("自定义模型 ID", "custom"),
    ],
    "deep": [
        ("Qwen 3.7 Max - 最新旗舰模型，智能程度最高，1M 上下文", "qwen3.7-max"),
        ("Qwen 3.6 Max - 上一代旗舰模型", "qwen3.6-max"),
        ("Qwen 3.7 Plus - 均衡型替代方案", "qwen3.7-plus"),
        ("自定义模型 ID", "custom"),
    ],
}


# MiniMax 全球与中国端点共用的模型列表（ID 相同）。
# 完整官方阵容见 platform.minimax.io/docs/api-reference/text-openai-api。
# M3 的上下文窗口为 1M token；M2.x 系列为 204,800 token。
_MINIMAX_MODELS: dict[str, list[ModelOption]] = {
    "quick": [
        ("MiniMax-M3 - 最新版本，1M 上下文，原生多模态", "MiniMax-M3"),
        ("MiniMax-M2.7-highspeed - 高速版 M2.7，204K 上下文，约 100 TPS", "MiniMax-M2.7-highspeed"),
        ("MiniMax-M2.5-highspeed - 上一代高速版，204K 上下文", "MiniMax-M2.5-highspeed"),
        ("自定义模型 ID", "custom"),
    ],
    "deep": [
        ("MiniMax-M3 - 最新旗舰模型，1M 上下文，支持多模态编程与智能体", "MiniMax-M3"),
        ("MiniMax-M2.7 - 上一代旗舰模型，204K 上下文", "MiniMax-M2.7"),
        ("MiniMax-M2.7-highspeed - 与 M2.7 质量相同，约 100 TPS", "MiniMax-M2.7-highspeed"),
        ("MiniMax-M2.5 - 更早的旗舰模型，204K 上下文", "MiniMax-M2.5"),
        ("自定义模型 ID", "custom"),
    ],
}


MODEL_OPTIONS: ProviderModeOptions = {
    "openai": {
        "quick": [
            ("GPT-5.4 Mini - 快速，编程与工具调用能力强", "gpt-5.4-mini"),
            ("GPT-5.4 Nano - 成本最低，适合高吞吐任务", "gpt-5.4-nano"),
            ("GPT-5.5 - 最新前沿模型，1M 上下文", "gpt-5.5"),
        ],
        "deep": [
            ("GPT-5.5 - 最新前沿模型，1M 上下文", "gpt-5.5"),
            ("GPT-5.4 - 上一代前沿模型，1M 上下文，高性价比", "gpt-5.4"),
            ("GPT-5.2 - 推理能力强，性价比高", "gpt-5.2"),
            ("GPT-5.5 Pro - 能力最强，价格较高（每 1M token 30/180 美元）", "gpt-5.5-pro"),
        ],
    },
    "anthropic": {
        "quick": [
            ("Claude Sonnet 5 - 速度与智能程度最均衡", "claude-sonnet-5"),
            ("Claude Haiku 4.5 - 速度最快，智能程度接近前沿模型", "claude-haiku-4-5"),
        ],
        "deep": [
            ("Claude Fable 5 - 能力最强，适合长时运行智能体", "claude-fable-5"),
            ("Claude Opus 4.8 - 前沿级智能体编程与推理", "claude-opus-4-8"),
            ("Claude Sonnet 5 - 接近前沿模型的智能程度，Sonnet 级成本", "claude-sonnet-5"),
            ("Claude Opus 4.7 - 上一代前沿模型，适合长时运行智能体", "claude-opus-4-7"),
        ],
    },
    "google": {
        "quick": [
            ("Gemini 3.5 Flash - 最新版本，前沿级智能体与编程能力（正式版）", "gemini-3.5-flash"),
            ("Gemini 3.1 Flash Lite - 性价比最高", "gemini-3.1-flash-lite"),
        ],
        "deep": [
            ("Gemini 3.1 Pro - 以推理为先，适合复杂工作流（预览版）", "gemini-3.1-pro-preview"),
            ("Gemini 3.5 Flash - 最新正式版，智能体与编程能力强", "gemini-3.5-flash"),
        ],
    },
    "xai": {
        "quick": [
            ("Grok 4.3 - 最新旗舰模型，速度快且内置推理", "grok-4.3"),
            ("Grok 4.20（非推理）- 速度优化", "grok-4.20-0309-non-reasoning"),
            ("Grok Build 0.1 - 编程专用，256K 上下文", "grok-build-0.1"),
        ],
        "deep": [
            ("Grok 4.3 - 最新旗舰模型，内置推理，1M 上下文", "grok-4.3"),
            ("Grok 4.20（推理）- 上一代推理模型", "grok-4.20-0309-reasoning"),
            ("Grok 4.20 Multi-Agent - 多智能体推理", "grok-4.20-multi-agent-0309"),
        ],
    },
    # DeepSeek：deepseek-chat / deepseek-reasoner 别名已于 2026-07-24 弃用，
    # 现在映射到 V4 Flash，因此直接展示 V4 ID。V4 Flash 同时支持非思考与
    # 思考模式（DeepSeekChatOpenAI 客户端负责 reasoning_content 往返）。
    "deepseek": {
        "quick": [
            ("DeepSeek V4 Flash - 最新快速模型，支持思考与非思考", "deepseek-v4-flash"),
            ("自定义模型 ID", "custom"),
        ],
        "deep": [
            ("DeepSeek V4 Pro - 最新旗舰模型", "deepseek-v4-pro"),
            ("DeepSeek V4 Flash - 速度快，支持思考", "deepseek-v4-flash"),
            ("自定义模型 ID", "custom"),
        ],
    },
    # Qwen：全球（dashscope-intl）与中国（dashscope）端点使用相同模型 ID，
    # 因此两个供应商键共用一份模型列表。
    "qwen": _QWEN_MODELS,
    "qwen-cn": _QWEN_MODELS,
    # GLM：Z.AI（国际）与 BigModel（中国）托管相同模型 ID，因此两个供应商键共用一份模型列表。
    "glm": _GLM_MODELS,
    "glm-cn": _GLM_MODELS,
    # MiniMax：全球（.io）与中国（.com）区域使用相同模型 ID，因此两个供应商键共用一份模型列表。
    "minimax": _MINIMAX_MODELS,
    "minimax-cn": _MINIMAX_MODELS,
    # OpenRouter：动态获取。Azure：可使用任意已部署的模型名称。
    # Ollama 显示标签有意不标注“本地”，因为端点现在可通过 OLLAMA_BASE_URL 配置；
    # 无论用户在 localhost 上运行 ollama-serve，还是连接远程主机，都使用相同标签。
    # 实际解析到的端点由 Web 或其他调用方在选择供应商后单独展示。
    # “自定义模型 ID”允许用户选择通过 ollama pull 获取的其他模型。
    "ollama": {
        "quick": [
            ("Qwen3:latest (8B)", "qwen3:latest"),
            ("GPT-OSS:latest (20B)", "gpt-oss:latest"),
            ("GLM-4.7-Flash:latest (30B)", "glm-4.7-flash:latest"),
            ("自定义模型 ID", "custom"),
        ],
        "deep": [
            ("GLM-4.7-Flash:latest (30B)", "glm-4.7-flash:latest"),
            ("GPT-OSS:latest (20B)", "gpt-oss:latest"),
            ("Qwen3:latest (8B)", "qwen3:latest"),
            ("自定义模型 ID", "custom"),
        ],
    },
    # 通用 OpenAI 兼容端点：模型由用户的服务器提供，因此只提供“自定义模型 ID”。
    "openai_compatible": _CUSTOM_ONLY,
    # 托管式 OpenAI 兼容供应商提供的模型数量多且经常变化，因此提供“自定义模型 ID”，
    # 不维护容易过时的列表。端点和密钥由供应商接入，用户选择账号有权访问的模型。
    "mistral": _CUSTOM_ONLY,
    "kimi": _CUSTOM_ONLY,
    "groq": _CUSTOM_ONLY,
    "nvidia": _CUSTOM_ONLY,
    # Bedrock 模型 ID / 跨区域推理配置文件 ID 由用户指定。
    "bedrock": _CUSTOM_ONLY,
}


def get_model_options(provider: str, mode: str) -> list[ModelOption]:
    """返回指定供应商和选择模式对应的共用模型选项。"""
    options = MODEL_OPTIONS[provider.lower()][mode]
    logger.debug("已解析供应商='%s'、模式='%s' 的 %d 个模型选项", provider, mode, len(options))
    return options


def get_known_models() -> dict[str, list[str]]:
    """从共用模型目录构建已知模型名称。"""
    known = {
        provider: sorted(
            {
                value
                for options in mode_options.values()
                for _, value in options
            }
        )
        for provider, mode_options in MODEL_OPTIONS.items()
    }
    logger.debug("已为 %d 个供应商构建已知模型目录", len(known))
    return known
