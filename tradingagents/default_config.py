import json
import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# 环境变量 -> 配置键覆盖的唯一事实来源。要增加可通过环境变量覆盖的配置键，
# 只需在这里添加一行，无需修改入口脚本。类型转换由现有默认值的类型驱动，
# 因此用户可以继续在 .env 文件中写入普通字符串。
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_CHECKPOINT_DATABASE_URL": "checkpoint_database_url",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_TEMPERATURE":          "temperature",
    "TRADINGAGENTS_LLM_MAX_RETRIES":      "llm_max_retries",
    # 服务商专属的推理/思考参数（None = 使用各服务商自己的默认值）。可在此设置
    # 以支持非交互运行；Web 和脚本入口直接读取这些配置。
    "TRADINGAGENTS_GOOGLE_THINKING_LEVEL":   "google_thinking_level",
    "TRADINGAGENTS_OPENAI_REASONING_EFFORT": "openai_reasoning_effort",
    "TRADINGAGENTS_ANTHROPIC_EFFORT":        "anthropic_effort",
}


_BOOL_TRUE = ("true", "1", "yes", "on")
_BOOL_FALSE = ("false", "0", "no", "off")


def _coerce(value: str, reference):
    """将环境变量字符串转换为现有默认值的类型。

    无效值会抛出 ``ValueError``，而不是静默回退到默认值；拼写错误的布尔值
   （例如 ``treu``）或非数字整数应在启动时明确失败，而不是静默错误配置无人值守的运行。
    """
    if isinstance(reference, bool):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ValueError(
            f"应为布尔值（{'/'.join(_BOOL_TRUE + _BOOL_FALSE)}），实际为 {value!r}"
        )
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """将 TRADINGAGENTS_* 环境变量原地应用到配置字典。"""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        try:
            config[key] = _coerce(raw, config.get(key))
        except ValueError as exc:
            raise ValueError(f"{env_var} 的值无效：{exc}") from exc
    return config


def apply_data_vendors_env(config: dict) -> dict:
    """将 ``TRADINGAGENTS_DATA_VENDORS`` JSON 覆盖项合并到 ``data_vendors``。

    它不在导入时执行的 ``_apply_env_overrides`` 中，因为 ``data_vendors`` 是嵌套字典，
    通用 ``_coerce`` 只处理标量。图和入口会显式调用，因此重新加载
    ``DEFAULT_CONFIG`` 且期望内置 yfinance 默认值的测试不会受部署 .env 影响。

        示例值（JSON 对象，类别 -> 供应商或供应商链）：
        {"core_stock_apis":"akshare","technical_indicators":"akshare",
         "fundamental_data":"akshare","news_data":"akshare",
         "macro_data":"akshare"}
    """
    raw = os.environ.get("TRADINGAGENTS_DATA_VENDORS")
    if raw is None or raw == "":
        return config
    try:
        overrides = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"TRADINGAGENTS_DATA_VENDORS 的值无效：{exc}") from exc
    if not isinstance(overrides, dict):
        raise ValueError("TRADINGAGENTS_DATA_VENDORS 必须是 JSON 对象")
    vendors = config.setdefault("data_vendors", {})
    vendors.update({str(k): str(v) for k, v in overrides.items()})
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # 已解析记忆日志条目数量的可选上限。设置后，超过上限时删除最旧的已解析条目。
    # 待处理条目永不删除。None 表示完全禁用轮转。
    "memory_log_max_entries": None,
    # LLM 设置。
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.5",
    "quick_think_llm": "gpt-5.4-mini",
    # 为 None 时，各服务商客户端回退到自己的默认端点（OpenAI 使用 api.openai.com，
    # Gemini 使用 generativelanguage.googleapis.com 等）。入口会按服务商覆盖。
    # 若在此保留服务商专属 URL，可能泄漏到其他客户端（例如之前将
    # OpenAI 的 /v1 传给 Gemini，产生格式错误的请求 URL）。
    "backend_url": None,
    # 服务商专属思考配置。
    "google_thinking_level": None,      # 可选值："high"、"minimal" 等。
    "openai_reasoning_effort": None,    # 可选值："medium"、"high"、"low"。
    "anthropic_effort": None,           # 可选值："high"、"medium"、"low"。
    # 设置后转发给所有服务商的采样温度。None 保留各服务商默认值。对支持该参数的
    # 模型，较低值会减少运行间差异；推理模型通常会忽略它，任何设置都不能让 LLM
    # 在不同运行间逐位输出完全相同（见 README）。
    "temperature": None,
    # 转发给所有服务商聊天客户端的 SDK 重试额度。None 保留各服务商/SDK 默认值
    #（通常为 2）。在受限流的部署中可提高该值以应对突发 429，而不是中止运行（#1091）。
    "llm_max_retries": None,
    # 检查点/恢复：为 True 时，LangGraph 在每个节点后保存状态，
    # 崩溃后可从最后一个成功步骤恢复。
    "checkpoint_enabled": False,
    # Checkpoint 统一使用 PostgreSQL。未单独配置时复用资讯模块的数据库连接串；
    # 若启用检查点但两者都未配置，运行时会明确报错，不会回退到本地文件数据库。
    "checkpoint_database_url": os.getenv("TRADINGAGENTS_CHECKPOINT_DATABASE_URL")
    or os.getenv("NEWS_DATABASE_URL"),
    # 分析师报告和最终决策的输出语言。项目默认生成简体中文研报；如需其他语言，
    # 可通过 TRADINGAGENTS_OUTPUT_LANGUAGE 覆盖。
    "output_language": "简体中文",
    # 辩论和讨论设置。
    "max_debate_rounds": 1,
    # 每位调用工具的分析师在被强制输出报告前允许的 LLM->工具->LLM 迭代上限。
    # 限制健谈模型的 Token 消耗；值高可获取更多数据，值低可降低成本/延迟。
    "max_tool_rounds": 3,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # 新闻/数据获取参数。
    # 长回溯策略或希望扩大宏观覆盖范围时提高；要减少 Agent 提示词 Token 使用量时降低。
    "news_article_limit": 20,             # 每个代码最多获取的文章数（ticker-news）
    "global_news_article_limit": 10,      # 全球/宏观新闻最多获取的文章数
    "global_news_lookback_days": 7,       # 宏观新闻回溯窗口
    # get_global_news 用于宏观标题的搜索查询。可扩展或替换以扩大地域/行业覆盖。
    "global_news_queries": [
        "Federal Reserve interest rates inflation",
        "S&P 500 earnings GDP economic outlook",
        "geopolitical risk trade war sanctions",
        "ECB Bank of England BOJ central bank policy",
        "oil commodities supply chain energy",
    ],
    # 数据供应商配置。
    # 类别级配置（该类别所有工具的默认值）。配置值就是精确的供应商链，
    # 请求不会静默路由到未选择的供应商。要按顺序回退可列出多个，例如
    # "yfinance,alpha_vantage"；"default" 使用所有可用供应商。
    "data_vendors": {
        "core_stock_apis": "yfinance",       # 可选值：alpha_vantage、yfinance
        "technical_indicators": "yfinance",  # 可选值：alpha_vantage、yfinance
        "fundamental_data": "yfinance",      # 可选值：alpha_vantage、yfinance
        "news_data": "yfinance",             # 可选值：alpha_vantage、yfinance
        "macro_data": "fred",                # 可选值：fred（需要 FRED_API_KEY）
        "prediction_markets": "polymarket",  # 可选值：polymarket（无需密钥）
    },
    # 工具级配置（优先于类别级配置）。
    "tool_vendors": {
        # 示例："get_stock_data": "alpha_vantage"，覆盖类别默认值。
    },
    # 反思层计算 Alpha 的基准。
    # 设置 ``benchmark_ticker`` 时覆盖所有代码的后缀映射；保持 None 可使用
    # ``benchmark_map``，按股票代码交易所后缀自动检测。SPY 仍是美股默认值，
    # 因此美股代码的反思标签仍显示 "Alpha vs SPY"，非美股代码则自动使用区域指数。
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",       # 印度 NSE（Nifty 50）
        ".BO":  "^BSESN",      # 印度 BSE（Sensex）
        ".T":   "^N225",       # 东京（Nikkei 225）
        ".HK":  "^HSI",        # 香港（Hang Seng）
        ".L":   "^FTSE",       # 伦敦（FTSE 100）
        ".TO":  "^GSPTSE",     # 多伦多（TSX Composite）
        ".AX":  "^AXJO",       # 澳大利亚（ASX 200）
        ".SS":  "000001.SS",   # 上海（SSE Composite）
        ".SZ":  "399001.SZ",   # 深圳（SZSE Component）
        "":     "SPY",         # 美国上市代码的默认值（无后缀）
    },
})
