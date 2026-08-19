"""Gateway health check: verify the LLM endpoint is reachable and the
configured deep/quick models respond.

Usage:  uv run --quiet python scripts/check_gateway.py
Exit code 0 = healthy, 1 = degraded, 2 = down.
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

    print(f"provider={provider}  base_url={base_url}")
    print(f"deep={deep_model}  quick={quick_model}\n")

    rc = 0
    for label, model in (("deep", deep_model), ("quick", quick_model)):
        try:
            client = create_llm_client(
                provider=provider, model=model, base_url=base_url
            )
            llm = client.get_llm()
            resp = llm.invoke("Reply with exactly: OK")
            ok = "OK" in resp.content
            reasoning = bool(resp.additional_kwargs.get("reasoning_content"))
            print(f"[{label}] {model}: {'OK' if ok else 'BAD REPLY'} "
                  f"(reasoning_content={reasoning}) content={resp.content[:40]!r}")
            if not ok:
                rc = max(rc, 1)
        except Exception as exc:  # noqa: BLE001
            print(f"[{label}] {model}: FAIL {type(exc).__name__}: {str(exc)[:160]}")
            rc = 2

    print("\nGATEWAY:", "HEALTHY" if rc == 0 else ("DEGRADED" if rc == 1 else "DOWN"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
