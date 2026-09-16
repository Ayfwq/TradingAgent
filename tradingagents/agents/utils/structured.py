"""调用智能体并生成结构化输出、同时优雅回退的共用辅助函数。

投资组合经理、交易员和研究经理都遵循相同的标准模式：

1. 创建智能体时，用 ``with_structured_output(Schema)`` 包装 LLM，使模型返回
   类型明确的 Pydantic 实例。如果供应商不支持结构化输出（较少见，主要是
   较旧的 Ollama 模型），则跳过包装，改用自由文本生成。
2. 调用时执行结构化请求，再将结果渲染为 Markdown。如果结构化请求因任何
   原因失败（弱模型返回格式错误的 JSON、供应商暂时异常等），则回退到普通
   ``llm.invoke``，保证流水线不会阻塞。

将模式集中在此处可以简化智能体工厂，并确保三个智能体在回退时记录一致的警告。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# 仅绑定 Schema 的结构化输出实际上只绑定一个工具（Schema 本身）。如果模型
# 尝试调用搜索工具，就会产生未知工具调用，整个结构化尝试会被丢弃并改为自由
# 文本重试。因此走这条路径时，智能体会明确说明约束，而不是只依赖绑定关系
#（#1130）。
NO_EXTERNAL_TOOLS = (
    "只使用本提示词中提供的证据。不要调用外部工具或搜索网页；如果缺少信息，"
    "请明确说明。所有自然语言字段必须使用简体中文。"
)


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Any | None:
    """返回 ``llm.with_structured_output(schema)``；不支持时返回 ``None``。

    绑定失败时记录警告，让用户知道智能体的每次调用都会使用自由文本生成，
    而不是只在单次调用失败时回退。
    """
    try:
        return llm.with_structured_output(schema)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning(
            "%s：供应商不支持 with_structured_output（%s）；"
            "回退到自由文本生成",
            agent_name, exc,
        )
        return None


def invoke_structured_or_freetext(
    structured_llm: Any | None,
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
) -> str:
    """执行结构化调用并渲染为 Markdown；任意失败都会回退到自由文本。

    ``prompt`` 可以是底层 LLM 接受的任意形式（聊天调用使用字符串，
    接受该形态的聊天模型使用消息字典列表）。同一个值会转发给自由文本路径，
    因此回退调用看到的输入与结构化调用完全一致。
    """
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            if result is None:
                # 思考模型可能直接以纯文本回答而不调用工具，导致解析器没有结果。
                # 将其视为结构化输出未命中，并说明原因后回退。
                raise ValueError("结构化输出未返回解析结果")
            return render(result)
        except Exception as exc:
            logger.warning(
                "%s：结构化输出调用失败（%s）；将以自由文本重试一次",
                agent_name, exc,
            )

    response = plain_llm.invoke(prompt)
    return response.content
