import logging
import re
from typing import Any

from langchain_anthropic import ChatAnthropic

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model

logger = logging.getLogger(__name__)

_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "api_key", "max_tokens", "temperature",
    "callbacks", "http_client", "http_async_client", "effort",
)

# Anthropic 的扩展思考 ``effort`` 参数适用于 Opus 4.5+、Sonnet 4.6+ 和 Claude 5
# 系列（Sonnet 5、Fable 5）。Sonnet 4.5 及任何 Haiku 版本会返回
# ``"This model does not support the effort parameter"``（#831）。版本可能带小数
#（``opus-4-8``）或只有一个数字（``sonnet-5``、``fable-5``）；下面的系列最低版本
# 判断具有向前兼容性。
_EFFORT_EXACT = {
    "claude-mythos-preview",  # 非标准的预览名称；支持 effort
    "claude-mythos-5",        # Fable 5 的同源模型（Project Glasswing）；支持 effort
}
_EFFORT_MODEL = re.compile(r"^claude-(opus|sonnet|fable)-(\d+)(?:-(\d+))?$")
_EFFORT_MIN_VERSION = {"opus": (4, 5), "sonnet": (4, 6), "fable": (5, 0)}


def _supports_effort(model: str) -> bool:
    """判断 Anthropic 是否接受该模型的 ``effort`` 参数。"""
    model_lc = model.lower()
    if model_lc in _EFFORT_EXACT:
        return True
    match = _EFFORT_MODEL.match(model_lc)
    if not match:
        return False
    family = match.group(1)
    major = int(match.group(2))
    minor = int(match.group(3)) if match.group(3) else 0
    return (major, minor) >= _EFFORT_MIN_VERSION[family]


class NormalizedChatAnthropic(ChatAnthropic):
    """输出内容已规范化的 ChatAnthropic。

    Claude 扩展思考或工具调用模型会将 content 返回为类型化数据块列表，这里将其
    规范化为字符串，便于下游统一处理。
    """

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude 模型客户端。"""

    def __init__(self, model: str, base_url: str | None = None, **kwargs):
        super().__init__(model, base_url, **kwargs)

    def get_llm(self) -> Any:
        """返回已配置的 ChatAnthropic 实例。"""
        logger.debug("正在构建 Anthropic LLM：provider=anthropic，model=%s，base_url=%s", self.model, self.base_url)
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}

        if self.base_url:
            llm_kwargs["base_url"] = self.base_url

        for key in _PASSTHROUGH_KWARGS:
            if key not in self.kwargs:
                continue
            if key == "effort" and not _supports_effort(self.model):
                continue
            llm_kwargs[key] = self.kwargs[key]

        llm = NormalizedChatAnthropic(**llm_kwargs)
        logger.debug("已为 model=%s 构建标准化 Anthropic 客户端", self.model)
        return llm

    def validate_model(self) -> bool:
        """校验 Anthropic 模型。"""
        result = validate_model("anthropic", self.model)
        logger.debug("provider='anthropic' 的模型 '%s' 校验结果：%s", self.model, result)
        return result
