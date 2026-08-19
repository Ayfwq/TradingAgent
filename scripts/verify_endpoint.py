"""Verify TradingAgents framework wiring against the custom endpoint.

Exercises exactly the path TradingAgentsGraph uses: DEFAULT_CONFIG env
overrides -> create_llm_client(provider, model, base_url) -> get_llm() ->
invoke. No network data vendors involved.
"""

import tradingagents  # noqa: F401  (loads .env)

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client

print("=== Resolved config ===")
print("llm_provider    :", DEFAULT_CONFIG["llm_provider"])
print("deep_think_llm  :", DEFAULT_CONFIG["deep_think_llm"])
print("quick_think_llm :", DEFAULT_CONFIG["quick_think_llm"])
print("backend_url     :", DEFAULT_CONFIG["backend_url"])

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
print("\n=== Clients built ===")
print("deep client  :", type(deep_llm).__name__, "| model:", deep_llm.model_name)
print("              base_url:", getattr(deep_llm, "openai_api_base", "n/a"))
print("quick client :", type(quick_llm).__name__, "| model:", quick_llm.model_name)
print("              base_url:", getattr(quick_llm, "openai_api_base", "n/a"))

print("\n=== Live call (deep client) ===")
resp = deep_llm.invoke("Reply with exactly: FRAMEWORK-OK")
print("content:", repr(resp.content))
print("reasoning_content present:", bool(
    resp.additional_kwargs.get("reasoning_content")
))
assert "FRAMEWORK-OK" in resp.content, "unexpected reply"
print("\nWIRING TEST PASSED")
