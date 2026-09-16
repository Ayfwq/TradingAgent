import logging
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .api_key_env import get_api_key_env
from .base_client import BaseLLMClient, normalize_content
from .capabilities import get_capabilities
from .validators import validate_model

logger = logging.getLogger(__name__)


class NormalizedChatOpenAI(ChatOpenAI):
    """输出内容已规范化且支持按能力绑定的 ChatOpenAI。

    Responses API 会将 content 返回为类型化数据块列表（reasoning、text 等），
    ``invoke`` 将其规范化为字符串，便于下游统一处理。

    ``with_structured_output`` 查询按模型能力表（``capabilities.get_capabilities``）
    选择方法，并决定是否可以发送 ``tool_choice``。拒绝 ``tool_choice`` 的模型
   （例如官方工具调用指南中的 DeepSeek V4 和 reasoner）仍会将模式绑定为工具，
    但不发送 ``tool_choice`` 参数。

    结构化输出之外的服务商特殊行为（例如 DeepSeek 的 reasoning_content 往返）
    放在子类中，以保持基类简洁。
    """

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))

    def with_structured_output(self, schema, *, method=None, **kwargs):
        caps = get_capabilities(self.model_name)
        if caps.preferred_structured_method == "none":
            raise NotImplementedError(
                f"{self.model_name} has no structured-output method available; "
                f"agent factories will fall back to free-text generation."
            )
        method = method or caps.preferred_structured_method
        # 模型拒绝 tool_choice 时，抑制 langchain 的硬编码值。模式仍会绑定为工具，
        # 与 DeepSeek 官方工具调用示例完全一致。
        if method == "function_calling" and not caps.supports_tool_choice:
            kwargs.setdefault("tool_choice", None)
        return super().with_structured_output(schema, method=method, **kwargs)


class LocalCompatibleChatOpenAI(NormalizedChatOpenAI):
    """适用于任意本地服务器（LM Studio、vLLM、llama.cpp）的 OpenAI 兼容客户端，
    使用通用 ``openai_compatible`` 服务商。

    各服务器的工具调用支持不同，许多服务器会拒绝 langchain 为函数调用结构化输出
    发送的对象形式 ``tool_choice``。将模式绑定为工具但不强制设置 tool_choice，
    使结构化输出不受模型 ID 能力差异影响，适用于各种本地服务器（#1057）。
    """

    def with_structured_output(self, schema, *, method=None, **kwargs):
        resolved = method or get_capabilities(self.model_name).preferred_structured_method
        if resolved == "function_calling":
            kwargs.setdefault("tool_choice", None)
        return super().with_structured_output(schema, method=method, **kwargs)


def _input_to_messages(input_: Any) -> list:
    """将 langchain LLM 输入规范化为消息对象列表。

    接受消息列表、``ChatPromptValue``（来自 ChatPromptTemplate）或其他值（视为空消息）。
    供需要遍历发出消息历史的服务商使用；尤其是 DeepSeek 思考模式传播必须同时支持
    裸列表调用和 ChatPromptTemplate 调用，因此这里只处理 ``list`` 会静默跳过一半调用点。
    """
    if isinstance(input_, list):
        return input_
    if hasattr(input_, "to_messages"):
        return input_.to_messages()
    return []


class DeepSeekChatOpenAI(NormalizedChatOpenAI):
    """OpenAI 兼容客户端之上的 DeepSeek 专属重载。

    思考模式往返是这里保留的唯一 DeepSeek 专属行为。DeepSeek 思考模型返回带有
    ``reasoning_content`` 的响应时，下一轮必须将该字段作为 assistant 消息的一部分
    回传，否则 API 会返回 HTTP 400。``_create_chat_result`` 在接收时保存，
    ``_get_request_payload`` 在发送时重新附加。

    V4 和 reasoner 的工具选择处理（这些模型拒绝 ``tool_choice`` 参数）由
    ``NormalizedChatOpenAI.with_structured_output`` 中的能力分发负责，不在这里处理。
    """

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        outgoing = payload.get("messages", [])
        for message_dict, message in zip(outgoing, _input_to_messages(input_), strict=False):
            if not isinstance(message, AIMessage):
                continue
            reasoning = message.additional_kwargs.get("reasoning_content")
            if reasoning is not None:
                message_dict["reasoning_content"] = reasoning
        return payload

    def _create_chat_result(self, response, generation_info=None):
        chat_result = super()._create_chat_result(response, generation_info)
        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}}
            )
        )
        for generation, choice in zip(
            chat_result.generations, response_dict.get("choices", []), strict=False
        ):
            reasoning = choice.get("message", {}).get("reasoning_content")
            if reasoning is not None:
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return chat_result


class MinimaxChatOpenAI(NormalizedChatOpenAI):
    """OpenAI 兼容客户端之上的 MiniMax 专属重载。

    M2.x 推理模型默认会将 ``<think>...</think>`` 块直接写入 ``message.content``，
    这会污染保存的报告。根据 platform.minimax.io/docs/api-reference/text-openai-api，
    ``reasoning_split=True`` 会将思考块重定向到 ``reasoning_details``，保持 ``content``
    干净。该参数通过 ``extra_body`` 发送（而不是顶层关键字参数），因为 openai SDK
    会校验顶层参数并拒绝 reasoning_split 等未知参数（#826）。

    该标志由 ``ModelCapabilities.requires_reasoning_split`` 控制，因此只有 M2.x 推理
    模型会收到；非推理 MiniMax 端点（Coding Plan、MiniMax-Text-01）不会收到。

    M2.x 的工具选择处理（这些模型只接受字符串枚举 ``{"none", "auto"}``，拒绝
    langchain 的函数规格字典）由 ``NormalizedChatOpenAI.with_structured_output``
    中的能力分发负责，不在这里处理。
    """

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if get_capabilities(self.model_name).requires_reasoning_split:
            # 通过 extra_body 传递，而不是作为顶层关键字参数：openai SDK（>=1.56）
            # 会依据 Completions.create 校验顶层参数，并拒绝 reasoning_split 等未知参数
            #（#826）。extra_body 会原样转发到请求体。
            extra_body = payload.setdefault("extra_body", {})
            extra_body.setdefault("reasoning_split", True)
        return payload


# 从用户配置转发给 ChatOpenAI 的关键字参数。
_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "reasoning_effort", "temperature",
    "api_key", "callbacks", "http_client", "http_async_client",
)

# OpenAI 的 ``reasoning_effort`` 只被推理模型（GPT-5 系列和 o 系列）接受。非推理
# 模型（gpt-4.1、gpt-4o 等）会返回 400，并提示该参数不受支持。对这些模型删除
# 该参数，避免运行崩溃。
_OPENAI_REASONING_MODEL = re.compile(r"^(gpt-5|o[1-9])")


def _supports_reasoning_effort(model: str) -> bool:
    """判断（原生 OpenAI）模型是否接受 ``reasoning_effort``。"""
    return bool(_OPENAI_REASONING_MODEL.match(model.lower().strip()))


@dataclass(frozen=True)
class ProviderSpec:
    """单个 OpenAI 兼容服务商的声明式配置。

    OpenAI 兼容系列（OpenAI、xAI、DeepSeek、Qwen、GLM、MiniMax、OpenRouter、Ollama
    以及任意用户端点）都使用相同的 Chat Completions API，只在这些字段上有差异；
    因此这里的一行配置取代了原先按服务商划分的基础 URL 字典、认证处理和客户端分支。
    原生 Anthropic / Google 使用自己的客户端（API 确实不同），有意不放入此注册表。

    API 密钥环境变量保留在 ``api_key_env.PROVIDER_API_KEY_ENV`` 中，作为所有模块
    查询的唯一来源；这里只保存服务商专属行为（基础 URL、密钥可选性、
    通过 ``chat_class`` 表示的线路格式差异）。
    """

    chat_class: type = NormalizedChatOpenAI   # 服务商特殊逻辑位于子类。
    base_url: str | None = None            # 默认端点（None -> SDK 默认值）。
    base_url_env: str | None = None        # 覆盖 base_url 的环境变量（如 OLLAMA_BASE_URL）。
    key_optional: bool = False                # 不强制要求/提示；未设置时发送占位值。
    placeholder_key: str = "EMPTY"            # 没有密钥时发送（无密钥本地服务器）。
    require_base_url: bool = False            # 未解析到 base_url 时出错（通用端点）。
    use_responses_api: bool = False           # 原生 OpenAI Responses API。


# OpenAI 兼容服务商系列的唯一事实来源。双区域服务商（qwen/glm/minimax）使用独立
# 端点，因为国际账户和中国账户不能共享凭证（#758）。
OPENAI_COMPATIBLE_PROVIDERS: dict[str, ProviderSpec] = {
    "openai":     ProviderSpec(use_responses_api=True),
    "xai":        ProviderSpec(base_url="https://api.x.ai/v1"),
    "deepseek":   ProviderSpec(base_url="https://api.deepseek.com", chat_class=DeepSeekChatOpenAI),
    "qwen":       ProviderSpec(base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    "qwen-cn":    ProviderSpec(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "glm":        ProviderSpec(base_url="https://api.z.ai/api/paas/v4/"),
    "glm-cn":     ProviderSpec(base_url="https://open.bigmodel.cn/api/paas/v4/"),
    "minimax":    ProviderSpec(base_url="https://api.minimax.io/v1", chat_class=MinimaxChatOpenAI),
    "minimax-cn": ProviderSpec(base_url="https://api.minimaxi.com/v1", chat_class=MinimaxChatOpenAI),
    "openrouter": ProviderSpec(base_url="https://openrouter.ai/api/v1"),
    "mistral":    ProviderSpec(base_url="https://api.mistral.ai/v1"),
    "kimi":       ProviderSpec(base_url="https://api.moonshot.ai/v1"),
    "groq":       ProviderSpec(base_url="https://api.groq.com/openai/v1"),
    "nvidia":     ProviderSpec(base_url="https://integrate.api.nvidia.com/v1"),
    "ollama":     ProviderSpec(base_url="http://localhost:11434/v1", base_url_env="OLLAMA_BASE_URL",
                               key_optional=True, placeholder_key="ollama"),
    # 通用端点：base_url 由用户提供，密钥可选（支持无密钥本地服务）。
    "openai_compatible": ProviderSpec(
        require_base_url=True, key_optional=True, chat_class=LocalCompatibleChatOpenAI
    ),
}


def is_openai_compatible(provider: str) -> bool:
    """判断 ``provider`` 是否由 OpenAI 兼容注册表提供服务。"""
    return provider.lower() in OPENAI_COMPATIBLE_PROVIDERS


def _is_native_openai_base_url(base_url: str | None) -> bool:
    """当 ``base_url`` 未设置或指向 api.openai.com 时返回 True。

    Responses API（/v1/responses）仅存在于原生 OpenAI。``openai`` 服务商使用自定义
    base_url（代理、网关或本地服务器）时只支持 Chat Completions，因此即使服务商配置
    开启了 Responses API，这里也必须关闭（#1024）。
    """
    if not base_url:
        return True
    if "://" not in base_url:
        base_url = "https://" + base_url
    host = urlparse(base_url).hostname or ""
    return host == "api.openai.com" or host.endswith(".openai.com")


class OpenAIClient(BaseLLMClient):
    """OpenAI、Ollama、OpenRouter 和 xAI 服务商客户端。

    对原生 OpenAI 模型使用 Responses API（/v1/responses），该接口在各模型系列
   （GPT-4.1、GPT-5）中支持结合函数工具使用 reasoning_effort。第三方兼容服务商
   （xAI、OpenRouter、Ollama）使用标准 Chat Completions。
    """

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        """根据服务商注册表返回已配置的 ChatOpenAI 实例。"""
        logger.debug("正在构建 OpenAI 兼容 LLM：provider=%s，model=%s，base_url=%s", self.provider, self.model, self.base_url)
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}
        spec = OPENAI_COMPATIBLE_PROVIDERS.get(self.provider)
        chat_cls = NormalizedChatOpenAI

        if spec is not None:
            chat_cls = spec.chat_class

            # base_url 优先级：显式客户端 base_url（承载配置中的
            # TRADINGAGENTS_LLM_BACKEND_URL）> 服务商环境变量覆盖（如 OLLAMA_BASE_URL）
            # > 服务商默认值。None 表示使用 SDK 默认值。
            env_base_url = os.environ.get(spec.base_url_env) if spec.base_url_env else None
            base_url = self.base_url or env_base_url or spec.base_url
            if spec.require_base_url and not base_url:
                logger.error("服务商 '%s' 需要 base_url，但未解析到任何值", self.provider)
                raise ValueError(
                    f"服务商 '{self.provider}' 需要 base_url。请通过 backend_url / "
                    "TRADINGAGENTS_LLM_BACKEND_URL 设置端点，例如 http://localhost:8000/v1 "
                    "（vLLM）或 http://localhost:1234/v1（LM Studio）。"
                )
            if base_url:
                llm_kwargs["base_url"] = base_url

            # 除非 key_optional，否则必须提供 API 密钥；无密钥本地服务器使用占位值。
            # 环境变量名称的唯一来源是 api_key_env。
            api_key_env = get_api_key_env(self.provider)
            api_key = os.environ.get(api_key_env) if api_key_env else None
            if api_key:
                llm_kwargs["api_key"] = api_key
            elif spec.key_optional:
                llm_kwargs["api_key"] = spec.placeholder_key
            elif api_key_env:
                logger.error("服务商 '%s' 的 API 密钥未设置（环境变量 '%s'）", self.provider, api_key_env)
                raise ValueError(
                    f"服务商 '{self.provider}' 的 API 密钥未设置。请设置环境变量 {api_key_env} "
                    f"（例如在 .env 文件中添加 {api_key_env}=your_key）。"
                )

            # Responses API 只存在于原生 OpenAI；如果用户让 openai 服务商使用自定义
            # base_url（代理/网关/本地服务），它只支持 Chat Completions，因此关闭 Responses（#1024）。
            if spec.use_responses_api and _is_native_openai_base_url(base_url):
                llm_kwargs["use_responses_api"] = True
        elif self.base_url:
            llm_kwargs["base_url"] = self.base_url

        # 转发用户提供的关键字参数。
        for key in _PASSTHROUGH_KWARGS:
            if key not in self.kwargs:
                continue
            if key == "reasoning_effort" and not _supports_reasoning_effort(self.model):
                continue
            llm_kwargs[key] = self.kwargs[key]

        # 子类（服务商特殊逻辑）来自注册表配置。
        llm = chat_cls(**llm_kwargs)
        logger.debug("已为 provider=%s、model=%s 构建 %s", self.provider, self.model, chat_cls.__name__)
        return llm

    def validate_model(self) -> bool:
        """校验服务商对应的模型。"""
        result = validate_model(self.provider, self.model)
        logger.debug("provider='%s' 的模型 '%s' 校验结果：%s", self.provider, self.model, result)
        return result
