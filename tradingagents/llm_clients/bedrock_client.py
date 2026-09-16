import logging
import os
from typing import Any

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model

logger = logging.getLogger(__name__)

# Bedrock 没有全局默认区域；us-west-2 承载的模型最丰富。
_DEFAULT_REGION = "us-west-2"
_BEDROCK_CLASS = None


def _bedrock_class():
    """延迟导入 langchain-aws（可选的 ``[bedrock]`` 扩展），并返回输出内容已规范化的
    ChatBedrockConverse 子类。

    按需导入，因此其余包不要求可选依赖（及 boto3）；首次调用后会缓存结果。
    """
    global _BEDROCK_CLASS
    if _BEDROCK_CLASS is not None:
        return _BEDROCK_CLASS

    try:
        from langchain_aws import ChatBedrockConverse
    except ImportError as exc:
        logger.exception("导入 langchain_aws 以支持 Bedrock 失败")
        raise ImportError(
            "AWS Bedrock support requires the optional 'langchain-aws' dependency. "
            'Install it with: pip install "tradingagents[bedrock]"'
        ) from exc

    class NormalizedChatBedrockConverse(ChatBedrockConverse):
        """输出内容已规范化为字符串的 ChatBedrockConverse。"""

        def invoke(self, input, config=None, **kwargs):
            return normalize_content(super().invoke(input, config, **kwargs))

    _BEDROCK_CLASS = NormalizedChatBedrockConverse
    return _BEDROCK_CLASS


class BedrockClient(BaseLLMClient):
    """通过 Converse API（langchain-aws）访问 Amazon Bedrock 的客户端。

    认证方式可以是 ``AWS_BEARER_TOKEN_BEDROCK`` 中的 Bedrock API 密钥（Bearer token，
    不需要 AWS 访问密钥），也可以是标准 AWS 凭证链（环境变量、``~/.aws/credentials``
    或 IAM role），并可选使用 ``AWS_PROFILE``。无论采用哪种方式都应设置 ``AWS_REGION`` /
    ``AWS_DEFAULT_REGION``（令牌本身不携带区域）。模型名称是 Bedrock 模型 ID 或跨区域
    推理配置 ID，例如 ``us.anthropic.claude-opus-4-8-v1:0``。
    """

    def get_llm(self) -> Any:
        """返回已配置的 ChatBedrockConverse 实例。"""
        logger.debug("正在构建 Bedrock LLM：provider=bedrock，model=%s，base_url=%s", self.model, self.base_url)
        self.warn_if_unknown_model()
        chat_cls = _bedrock_class()

        region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or _DEFAULT_REGION
        )
        llm_kwargs = {"model": self.model, "region_name": region}
        # Bedrock API 密钥无需 AWS 访问密钥即可认证。作为 api_key 传入后，
        # langchain-aws 会优先使用 Bearer 认证，因此环境中的 AWS_PROFILE / SigV4
        # 凭证不会覆盖它（#1103）。
        bearer_token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
        if bearer_token:
            llm_kwargs["api_key"] = bearer_token
        for key in ("temperature", "max_tokens", "max_retries", "callbacks"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]
        llm = chat_cls(**llm_kwargs)
        logger.debug("已为 model=%s、region=%s 构建 %s", self.model, region, chat_cls.__name__)
        return llm

    def validate_model(self) -> bool:
        """校验 Bedrock 模型（接受任意模型 ID）。"""
        result = validate_model("bedrock", self.model)
        logger.debug("provider='bedrock' 的模型 '%s' 校验结果：%s", self.model, result)
        return result
