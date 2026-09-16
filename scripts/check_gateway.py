"""网关健康检查：验证 LLM 端点可访问，且配置的深度/快速模型能够响应。

用法：uv run --quiet python scripts/check_gateway.py
退出码 0 = 健康，1 = 降级，2 = 不可用。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tradingagents  # noqa: F401  (loads .env)

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client


def main() -> int:
    provider = DEFAULT_CONFIG["llm_provider"]
    base_url = DEFAULT_CONFIG.get("backend_url")
    deep_model = DEFAULT_CONFIG["deep_think_llm"]
    quick_model = DEFAULT_CONFIG["quick_think_llm"]

    print(f"供应商={provider}  base_url={base_url}")
    print(f"深度模型={deep_model}  快速模型={quick_model}\n")

    rc = 0
    for label, model in (("deep", deep_model), ("quick", quick_model)):
        try:
            client = create_llm_client(
                provider=provider, model=model, base_url=base_url
            )
            llm = client.get_llm()
            resp = llm.invoke("只回复：OK")
            ok = "OK" in resp.content
            reasoning = bool(resp.additional_kwargs.get("reasoning_content"))
            print(f"[{label}] {model}：{'正常' if ok else '回复异常'} "
                  f"（reasoning_content={reasoning}）内容={resp.content[:40]!r}")
            if not ok:
                rc = max(rc, 1)
        except Exception as exc:  # noqa: BLE001
            print(f"[{label}] {model}：失败 {type(exc).__name__}：{str(exc)[:160]}")
            rc = 2

    print("\n网关：", "健康" if rc == 0 else ("降级" if rc == 1 else "不可用"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
