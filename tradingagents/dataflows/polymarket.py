"""Polymarket 预测市场供应商。

向新闻分析师提供前瞻事件（美联储决策、衰退、选举、地缘政治、加密货币）的实时
市场隐含概率，作为新闻（发生了什么）和 FRED 宏观数据（当前情况）的补充：
展示市场参与者实际定价的下一步事件概率。

使用 Polymarket 公共 Gamma API（https://gamma-api.polymarket.com），无需密钥和认证。
每个市场的 ``outcomePrices`` 是各结果的隐含概率（例如 "Yes" 为 0.76 表示市场
定价该事件发生的概率为 76%）。
"""
import json
import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"

# 网络超时时间（秒）。对于无需密钥的公共 API，30 秒过长；在无法访问
# gamma-api.polymarket.com 的网络（例如中国大陆）上会让可选增强每次调用阻塞 30 秒。
# 路由器无论如何都会将该错误视为可选类别哨兵，因此短超时可以快速失败并优雅降级，
# 不会阻塞运行。
REQUEST_TIMEOUT = 6

# 默认返回的市场数量，按交易量排序。
DEFAULT_LIMIT = 6


def _request(path: str, params: dict) -> dict:
    response = requests.get(
        f"{GAMMA_BASE}/{path}", params=params, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def _parse_json_list(value) -> list:
    """Gamma 将 ``outcomes``/``outcomePrices`` 编码为 JSON 字符串数组。"""
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def _is_forward_looking(market: dict, now: datetime) -> bool:
    """仅保留开放且未来才结算的市场。

    ``closed`` 是可靠的已结算标志（已结算市场的 ``active`` 仍可能为 True），
    过去的 ``endDate`` 也表示事件已经结算；两者都不属于前瞻信号。
    """
    if market.get("closed"):
        return False
    end_date = market.get("endDate")
    if end_date:
        try:
            if datetime.fromisoformat(end_date.replace("Z", "+00:00")) < now:
                return False
        except ValueError:
            pass
    return bool(_parse_json_list(market.get("outcomePrices"))) and bool(
        _parse_json_list(market.get("outcomes"))
    )


def get_prediction_markets(topic: str, limit: int | None = None) -> str:
    """返回某个事件主题的实时预测市场概率。

    Args:
        topic：事件关键词，例如 "Fed rate cut"、"recession 2026"、"US election"，
            或行业/公司事件。
        limit：最多返回的市场数（按交易量排序）；``None`` 使用 DEFAULT_LIMIT。

    Returns:
        匹配主题且交易量最高的开放市场 Markdown 报告，包括隐含概率、交易量、
        结算日期和近期（一周）变化。
    """
    if limit is None:
        limit = DEFAULT_LIMIT

    try:
        data = _request("public-search", {"q": topic, "limit_per_type": 20})
    except requests.RequestException as e:
        logger.warning("Polymarket 搜索失败 %r：%s", topic, e)
        return (
            f"Polymarket 数据当前不可用（网络错误：{e}）。"
            f"请在没有 '{topic}' 预测市场信号的情况下继续。"
        )

    now = datetime.now(timezone.utc)
    candidates = [
        m
        for event in data.get("events", [])
        for m in event.get("markets", [])
        if _is_forward_looking(m, now)
    ]
    candidates.sort(key=lambda m: m.get("volumeNum") or 0, reverse=True)

    header = (
        f'## Polymarket 预测市场："{topic}"\n'
        f"实时市场隐含概率（交易量越高，市场深度越好，通常越可靠）。概率是市场参与者"
        f"对事件的定价赔率，不应视为确定性预测。\n\n"
    )

    if not candidates:
        return header + (
            f"没有开放的预测市场匹配 '{topic}'。Polymarket 主要覆盖宏观、政治、地缘政治和"
            f"加密货币事件，某只股票可能没有对应市场。"
        )

    lines = []
    for m in candidates[:limit]:
        prices = _parse_json_list(m.get("outcomePrices"))
        outcomes = _parse_json_list(m.get("outcomes"))
        try:
            prob = float(prices[0])
        except (ValueError, IndexError):
            continue
        label = outcomes[0] if outcomes else "Yes"
        volume = m.get("volumeNum") or 0
        end_date = (m.get("endDate") or "")[:10]
        wk = m.get("oneWeekPriceChange")
        wk_str = (
            f", 1-week {wk * 100:+.1f}pp"
            if isinstance(wk, (int, float)) and wk
            else ""
        )
        lines.append(
            f"- **{m.get('question')}** — {label} {prob:.0%} "
            f"（交易量 ${volume:,.0f}，结算日期 {end_date}{wk_str}）"
        )

    return header + "\n".join(lines) + "\n"
