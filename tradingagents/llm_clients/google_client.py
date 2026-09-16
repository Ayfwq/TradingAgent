import logging
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model

logger = logging.getLogger(__name__)


class NormalizedChatGoogleGenerativeAI(ChatGoogleGenerativeAI):
    """输出内容已规范化的 ChatGoogleGenerativeAI。

    Gemini 3 模型会将 content 返回为类型化数据块列表，这里将其规范化为字符串，
    便于下游统一处理。
    """

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))


class GoogleClient(BaseLLMClient):
    """Google Gemini 模型客户端。"""

    def __init__(self, model: str, base_url: str | None = None, **kwargs):
        super().__init__(model, base_url, **kwargs)

    def get_llm(self) -> Any:
        """返回已配置的 ChatGoogleGenerativeAI 实例。"""
        logger.debug("正在构建 Google LLM：provider=google，model=%s，base_url=%s", self.model, self.base_url)
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}

        if self.base_url:
            llm_kwargs["base_url"] = self.base_url

        for key in ("timeout", "max_retries", "temperature", "callbacks", "http_client", "http_async_client"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        # 统一的 api_key 映射为服务商专属的 google_api_key。
        google_api_key = self.kwargs.get("api_key") or self.kwargs.get("google_api_key")
        if google_api_key:
            llm_kwargs["google_api_key"] = google_api_key

        # Gemini 3.x 使用字符串 ``thinking_level``（整数 ``thinking_budget`` 属于
        # 已退出的 2.5 系列）。Pro 接受 low/high；Flash 还接受 minimal/medium，
        # 因此将 Pro 不支持的 "minimal" 映射到其接受的最接近等级。
        thinking_level = self.kwargs.get("thinking_level")
        if thinking_level:
            if "pro" in self.model.lower() and thinking_level == "minimal":
                thinking_level = "low"
            llm_kwargs["thinking_level"] = thinking_level

        llm = NormalizedChatGoogleGenerativeAI(**llm_kwargs)
        logger.debug("已为 model=%s 构建标准化 Google Generative AI 客户端", self.model)
        return llm

    def validate_model(self) -> bool:
        """校验 Google 模型。"""
        result = validate_model("google", self.model)
        logger.debug("provider='google' 的模型 '%s' 校验结果：%s", self.model, result)
        return result
