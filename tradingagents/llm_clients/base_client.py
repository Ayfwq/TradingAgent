import logging
import warnings
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


def normalize_content(response):
    """将 LLM 响应内容规范化为纯字符串。

    多个服务商（OpenAI Responses API、Google Gemini 3）会将 content 返回为类型化
    数据块列表，例如 [{'type': 'reasoning', ...}, {'type': 'text', 'text': '...'}]。
    下游 Agent 需要 response.content 为字符串，因此提取并拼接文本块，丢弃推理/元数据块。
    """
    content = response.content
    if isinstance(content, list):
        texts = [
            item.get("text", "") if isinstance(item, dict) and item.get("type") == "text"
            else item if isinstance(item, str) else ""
            for item in content
        ]
        response.content = "\n".join(t for t in texts if t)
        logger.debug("已将列表内容规范化为字符串（%d 个文本块）", len(texts))
    return response


class BaseLLMClient(ABC):
    """LLM 客户端抽象基类。"""

    def __init__(self, model: str, base_url: str | None = None, **kwargs):
        self.model = model
        self.base_url = base_url
        self.kwargs = kwargs
        logger.debug("已初始化 %s：model=%s base_url=%s", self.__class__.__name__, model, base_url)

    def get_provider_name(self) -> str:
        """返回警告消息中使用的服务商名称。"""
        provider = getattr(self, "provider", None)
        if provider:
            return str(provider)
        return self.__class__.__name__.removesuffix("Client").lower()

    def warn_if_unknown_model(self) -> None:
        """当模型不在服务商已知列表中时发出警告。"""
        if self.validate_model():
            return

        message = (
            f"模型 '{self.model}' 不在服务商 '{self.get_provider_name()}' 的已知列表中。将继续运行。"
        )
        logger.warning("%s", message)
        warnings.warn(message, RuntimeWarning, stacklevel=2)

    @abstractmethod
    def get_llm(self) -> Any:
        """返回已配置的 LLM 实例。"""
        pass

    @abstractmethod
    def validate_model(self) -> bool:
        """校验该客户端是否支持此模型。"""
        pass
