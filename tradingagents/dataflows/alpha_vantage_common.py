import json
import logging
import os
from datetime import datetime
from io import StringIO

import pandas as pd
import requests

from .errors import VendorNotConfiguredError, VendorRateLimitError

logger = logging.getLogger(__name__)

API_BASE_URL = "https://www.alphavantage.co/query"

# 网络超时时间（秒），避免 Alpha Vantage 请求卡住调用方/Agent（#990）。
REQUEST_TIMEOUT = 30


class AlphaVantageNotConfiguredError(VendorNotConfiguredError):
    """选择 Alpha Vantage 但未配置 API 密钥时抛出。

    该异常继承 VendorNotConfiguredError（因此仍是 ValueError），可以继续兼容
    路由层的“供应商不可用”处理和现有 ValueError 调用方。
    """
    pass


def get_api_key() -> str:
    """从环境变量读取 Alpha Vantage API 密钥。"""
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        logger.warning("未设置 ALPHA_VANTAGE_API_KEY 环境变量")
        raise AlphaVantageNotConfiguredError(
            "未设置 ALPHA_VANTAGE_API_KEY 环境变量。"
        )
    return api_key

def format_datetime_for_api(date_input) -> str:
    """将多种日期格式转换为 Alpha Vantage API 要求的 YYYYMMDDTHHMM 格式。"""
    if isinstance(date_input, str):
        # 如果已经是正确格式，直接返回。
        if len(date_input) == 13 and 'T' in date_input:
            return date_input
        # 尝试解析常见日期格式。
        try:
            dt = datetime.strptime(date_input, "%Y-%m-%d")
            return dt.strftime("%Y%m%dT0000")
        except ValueError:
            try:
                dt = datetime.strptime(date_input, "%Y-%m-%d %H:%M")
                return dt.strftime("%Y%m%dT%H%M")
            except ValueError:
                raise ValueError(f"不支持的日期格式：{date_input}") from None
    elif isinstance(date_input, datetime):
        return date_input.strftime("%Y%m%dT%H%M")
    else:
        raise ValueError(f"日期必须是字符串或 datetime 对象，实际类型为 {type(date_input)}")

class AlphaVantageRateLimitError(VendorRateLimitError):
    """超过 Alpha Vantage API 限流阈值时抛出。"""
    pass

def _make_api_request(function_name: str, params: dict) -> dict | str:
    """发起 API 请求并处理响应。

    Raises:
        AlphaVantageRateLimitError：超过 API 限流阈值时抛出。
    """
    logger.debug("Alpha Vantage API 请求：function=%s，params=%s", function_name, params)
    # 复制 params，避免修改原始参数。
    api_params = params.copy()
    api_params.update({
        "function": function_name,
        "apikey": get_api_key(),
        "source": "trading_agents",
    })

    # 处理 params 或全局变量中的 entitlement 参数。
    current_entitlement = globals().get('_current_entitlement')
    entitlement = api_params.get("entitlement") or current_entitlement

    if entitlement:
        api_params["entitlement"] = entitlement
    elif "entitlement" in api_params:
        # 如果 entitlement 为空，则删除。
        api_params.pop("entitlement", None)

    response = requests.get(API_BASE_URL, params=api_params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    response_text = response.text

    # 错误响应为 JSON；数据响应通常是 CSV（或以数据为键的 JSON）。
    # 非 JSON 响应体属于正常数据。
    try:
        response_json = json.loads(response_text)
    except json.JSONDecodeError:
        logger.debug("Alpha Vantage API 的 function=%s 响应不是 JSON（%d 字节）", function_name, len(response_text))
        return response_text

    # Alpha Vantage 通过 "Information" / "Note" 报告问题。分类处理，避免将
    # 真正的限流与密钥无效/缺失混淆（#991）。先检查限流措辞，因为这些提示也会
    # 提到 "API key"（例如“你的 API key 每天可请求 25 次”）。
    notice = response_json.get("Information") or response_json.get("Note")
    if notice:
        low = notice.lower()
        if any(m in low for m in ("rate limit", "requests per day", "call frequency", "premium")):
            logger.warning("Alpha Vantage 的 function=%s 触发限流：%s", function_name, notice)
            raise AlphaVantageRateLimitError(f"已超过 Alpha Vantage 限流阈值：{notice}")
        if "api key" in low or "apikey" in low:
            logger.warning("Alpha Vantage 的 function=%s API 密钥无效或缺失：%s", function_name, notice)
            # 复用现有“未配置”异常，让错误密钥显示为真实且可处理的失败，
            # 而不是被错误标记为限流（#991）。
            raise AlphaVantageNotConfiguredError(f"Alpha Vantage API 密钥无效或缺失：{notice}")

    logger.debug("Alpha Vantage API 的 function=%s 响应为 JSON（%d 字节）", function_name, len(response_text))
    return response_text



def _filter_csv_by_date_range(csv_data: str, start_date: str, end_date: str) -> str:
    """
    过滤 CSV 数据，仅保留指定日期范围内的行。

    Args:
        csv_data：来自 Alpha Vantage API 的 CSV 字符串。
        start_date：yyyy-mm-dd 格式的开始日期。
        end_date：yyyy-mm-dd 格式的结束日期。

    Returns:
        过滤后的 CSV 字符串。
    """
    logger.debug("_filter_csv_by_date_range called for %s..%s", start_date, end_date)
    if not csv_data or csv_data.strip() == "":
        logger.debug("Alpha Vantage CSV 数据为空：%s..%s", start_date, end_date)
        return csv_data

    try:
        # 解析 CSV 数据。
        df = pd.read_csv(StringIO(csv_data))

        # 假设第一列是日期列（时间戳）。
        date_col = df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col])

        # 按日期范围过滤。
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)

        filtered_df = df[(df[date_col] >= start_dt) & (df[date_col] <= end_dt)]
        logger.debug("Alpha Vantage CSV 已从 %d 行过滤为 %d 行（%s..%s）", len(df), len(filtered_df), start_date, end_date)

        # 转回 CSV 字符串。
        return filtered_df.to_csv(index=False)

    except Exception as e:
        # 过滤失败时返回原始数据并记录警告。
        logger.warning("按日期范围 %s..%s 过滤 Alpha Vantage CSV 失败：%s", start_date, end_date, e)
        return csv_data
