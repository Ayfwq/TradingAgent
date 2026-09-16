import logging
import os
from typing import Any

from langchain_openai import AzureChatOpenAI

from .base_client import BaseLLMClient, normalize_content

logger = logging.getLogger(__name__)

_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "api_key", "reasoning_effort", "temperature",
    "callbacks", "http_client", "http_async_client",
)


class NormalizedAzureChatOpenAI(AzureChatOpenAI):
    """输出内容已规范化的 AzureChatOpenAI。"""

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))


class AzureOpenAIClient(BaseLLMClient):
    """Azure OpenAI 部署客户端。

    需要以下环境变量：
        AZURE_OPENAI_API_KEY：API 密钥。
        AZURE_OPENAI_ENDPOINT：端点 URL（例如 https://<resource>.openai.azure.com/）。
        AZURE_OPENAI_DEPLOYMENT_NAME：部署名称。
        OPENAI_API_VERSION：API 版本（例如 2025-03-01-preview）。
    """

    def __init__(self, model: str, base_url: str | None = None, **kwargs):
        super().__init__(model, base_url, **kwargs)

    def get_llm(self) -> Any:
        """返回已配置的 AzureChatOpenAI 实例。"""
        logger.debug("正在构建 Azure OpenAI LLM：provider=azure，model=%s，base_url=%s", self.model, self.base_url)
        self.warn_if_unknown_model()

        llm_kwargs = {
            "model": self.model,
            "azure_deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", self.model),
        }

        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        llm = NormalizedAzureChatOpenAI(**llm_kwargs)
        logger.debug("已为 model=%s 构建标准化 Azure ChatOpenAI 客户端", self.model)
        return llm

    def validate_model(self) -> bool:
        """Azure 接受任意已部署的模型名称。"""
        logger.debug("Azure 接受任意已部署模型名称（model='%s'）", self.model)
        return True
