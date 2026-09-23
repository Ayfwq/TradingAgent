"""OpenAI 兼容服务商的按模型声明式能力表。

这里集中记录哪些模型 ID 拒绝哪些 API 参数，或需要哪种结构化输出方式。LLM 客户端
子类查询 ``get_capabilities(model_name)``，不再硬编码按模型名称判断；新增模型或
服务商特殊行为只需编辑此表，不必修改客户端代码。

该模式参考 DeepSeek 在集成指南中发布的按模型 ``compat:`` 标志（例如 Oh My Pi
配置模式将 ``supportsToolChoice``、``requiresReasoningContentForToolCalls``
记录为按模型声明式字段）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

StructuredMethod = Literal[
    "function_calling",  # 使用工具，并遵循 supports_tool_choice。
    "json_mode",         # 使用 response_format={"type":"json_object"}。
    "json_schema",       # 使用 response_format={"type":"json_schema",...}。
    "none",              # 无结构化输出，调用方回退到自由文本。
]


@dataclass(frozen=True)
class ModelCapabilities:
    """OpenAI 兼容模型在 API 层接受的能力。"""

    supports_tool_choice: bool
    supports_json_mode: bool
    supports_json_schema: bool
    preferred_structured_method: StructuredMethod
    # 如果不在下一次请求中回传前一轮 assistant 消息的 reasoning_content，
    # DeepSeek 思考模式模型会返回 400。
    requires_reasoning_content_roundtrip: bool = False
    # MiniMax M2.x 推理模型需要 ``reasoning_split=True``，让 <think> 块进入
    # ``reasoning_details``，而不是污染 ``content``。非推理 MiniMax 模型
    #（Coding Plan、MiniMax-Text-01 等）会拒绝该标志，因此只对真正使用它的模型开启（#826）。
    requires_reasoning_split: bool = False


# DeepSeek 思考模型接受 ``tools`` 数组，但拒绝 ``tool_choice`` 参数（官方 Oh My Pi
# 集成指南及 issue #678 中的 400 响应）。官方工具调用示例
#（api-docs.deepseek.com/guides/tool_calls）传入 ``tools=[...]`` 而不传 ``tool_choice``；
# 这里将 supports_tool_choice 设为 False，并让客户端抑制该参数。
_DEEPSEEK_THINKING = ModelCapabilities(
    supports_tool_choice=False,
    supports_json_mode=True,
    supports_json_schema=False,
    preferred_structured_method="function_calling",
    requires_reasoning_content_roundtrip=True,
)

_DEEPSEEK_CHAT = ModelCapabilities(
    supports_tool_choice=True,
    supports_json_mode=True,
    supports_json_schema=False,
    preferred_structured_method="function_calling",
)

# MiniMax M2.x 推理模型接受工具数组，但其 tool_choice 参数仅允许 {"none", "auto"}
#（platform.minimax.io/docs/api-reference/text-post）。Langchain 的 function_calling
# 路径会将 tool_choice 作为函数规格字典发送，MiniMax 会返回 400，与 DeepSeek 问题
# 相同。supports_tool_choice=False 会让 NormalizedChatOpenAI 的分发逻辑抑制该参数；
# 模式仍会作为工具发送。json_mode 的 response_format 仅适用于 MiniMax-Text-01，不适用于 M2.x。
_MINIMAX_THINKING = ModelCapabilities(
    supports_tool_choice=False,
    supports_json_mode=False,
    supports_json_schema=False,
    preferred_structured_method="function_calling",
    requires_reasoning_split=True,
)

_DEFAULT = ModelCapabilities(
    supports_tool_choice=True,
    supports_json_mode=True,
    supports_json_schema=True,
    preferred_structured_method="function_calling",
)


# 精确 ID 匹配优先于模式匹配。
_BY_ID: dict[str, ModelCapabilities] = {
    "deepseek-chat": _DEEPSEEK_CHAT,
    "deepseek-reasoner": _DEEPSEEK_THINKING,
    "deepseek-flash": _DEEPSEEK_THINKING,
    "deepseek-v4-flash": _DEEPSEEK_THINKING,
    "deepseek-v4-pro": _DEEPSEEK_THINKING,
    # MiniMax：根据官方文档列出的完整模型系列
    # platform.minimax.io/docs/api-reference/text-openai-api
    "MiniMax-M2.7": _MINIMAX_THINKING,
    "MiniMax-M2.7-highspeed": _MINIMAX_THINKING,
    "MiniMax-M2.5": _MINIMAX_THINKING,
    "MiniMax-M2.5-highspeed": _MINIMAX_THINKING,
    "MiniMax-M2.1": _MINIMAX_THINKING,
    "MiniMax-M2.1-highspeed": _MINIMAX_THINKING,
    "MiniMax-M2": _MINIMAX_THINKING,
}

# 向前兼容模式。新的 ``deepseek-v5-*`` / ``deepseek-reasoner-*`` 或 ``MiniMax-M3*``
# 变体会自动继承思考模式的特殊行为。
_BY_PATTERN: list[tuple[re.Pattern[str], ModelCapabilities]] = [
    (re.compile(r"^deepseek-v\d"), _DEEPSEEK_THINKING),
    (re.compile(r"^deepseek-reasoner"), _DEEPSEEK_THINKING),
    (re.compile(r"^MiniMax-M\d"), _MINIMAX_THINKING),
]


def get_capabilities(model_name: str) -> ModelCapabilities:
    """依次通过精确 ID、模式和默认值解析模型能力。"""
    logger.debug("正在解析模型 '%s' 的能力", model_name)
    if model_name in _BY_ID:
        logger.debug("模型 '%s' 通过精确 ID 匹配能力表", model_name)
        return _BY_ID[model_name]
    for pattern, caps in _BY_PATTERN:
        if pattern.match(model_name):
            logger.debug("模型 '%s' 匹配能力模式 '%s'", model_name, pattern.pattern)
            return caps
    logger.debug("模型 '%s' 不在能力表中，使用默认能力", model_name)
    return _DEFAULT
