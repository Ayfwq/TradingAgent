"""验证 TradingAgents 框架与自定义端点的连接。

执行 TradingAgentsGraph 使用的完整路径：DEFAULT_CONFIG 环境变量覆盖 ->
create_llm_client(provider, model, base_url) -> get_llm() -> invoke。
不涉及网络数据供应商。
"""

import tradingagents  # noqa: F401  (loads .env)

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client

print("=== 已解析配置 ===")
print("llm_provider    ：", DEFAULT_CONFIG["llm_provider"])
print("deep_think_llm  ：", DEFAULT_CONFIG["deep_think_llm"])
print("quick_think_llm ：", DEFAULT_CONFIG["quick_think_llm"])
print("backend_url     ：", DEFAULT_CONFIG["backend_url"])

deep_client = create_llm_client(
    provider=DEFAULT_CONFIG["llm_provider"],
    model=DEFAULT_CONFIG["deep_think_llm"],
    base_url=DEFAULT_CONFIG.get("backend_url"),
)
quick_client = create_llm_client(
    provider=DEFAULT_CONFIG["llm_provider"],
    model=DEFAULT_CONFIG["quick_think_llm"],
    base_url=DEFAULT_CONFIG.get("backend_url"),
)

deep_llm = deep_client.get_llm()
quick_llm = quick_client.get_llm()
print("\n=== 客户端已构建 ===")
print("深度客户端：", type(deep_llm).__name__, "| 模型：", deep_llm.model_name)
print("              base_url：", getattr(deep_llm, "openai_api_base", "n/a"))
print("快速客户端：", type(quick_llm).__name__, "| 模型：", quick_llm.model_name)
print("              base_url：", getattr(quick_llm, "openai_api_base", "n/a"))

print("\n=== 实时调用（深度客户端） ===")
resp = deep_llm.invoke("只回复：FRAMEWORK-OK")
print("内容：", repr(resp.content))
print("是否包含 reasoning_content：", bool(
    resp.additional_kwargs.get("reasoning_content")
))
assert "FRAMEWORK-OK" in resp.content, "回复内容不符合预期"
print("\n连接测试通过")
