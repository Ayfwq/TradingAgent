"""AI 资讯模块：来源清单、分类规则与运行配置。

所有参数均可通过环境变量覆盖（见 DEPLOYMENT.md），此处提供安全默认值。
来源准入遵循 AI_NEWS_MODULE_PLAN.md 第 4.4 节：仅 HTTPS、无需登录、
不绕过反爬、允许聚合读取的官方 RSS/Atom/API。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 分类体系（五个主分类 + 内部"其他"）
# ---------------------------------------------------------------------------

CATEGORY_LABELS: dict[str, str] = {
    "model_tech": "模型与技术",
    "product_open_source": "产品与开源",
    "chips_compute": "芯片与算力",
    "company_capital": "公司与资本",
    "policy_security": "政策与安全",
    "other": "其他",
}

# 分类关键词：命中计数最高者胜出；全部未命中进入 "other"。
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "model_tech": [
        "模型", "大模型", "算法", "论文", "多模态", "智能体", "Agent", "AGI",
        "推理模型", "基准测试", "benchmark", "神经网络", "机器学习", "深度学习",
        "GPT", "Gemini", "Claude", "Llama", "LLaMA", "DeepSeek", "Qwen", "通义",
        "Kimi", "Mistral", "Grok", "LLM", "VLA", "RAG", "微调", "开源模型",
        "model", "reasoning", "multimodal", "research", "paper", "inference",
    ],
    "product_open_source": [
        "产品", "发布", "上线", "工具", "SDK", "API", "应用", "平台", "助手",
        "Copilot", "ChatGPT", "插件", "集成", "开发者", "开源", "GitHub",
        "Hugging Face", "代码", "编程", "浏览器", "搜索", "智能眼镜", "终端",
        "launch", "release", "open source", "tool", "platform", "developer",
    ],
    "chips_compute": [
        "芯片", "GPU", "算力", "CUDA", "NVIDIA", "英伟达", "AMD", "英特尔",
        "Intel", "昇腾", "海光", "寒武纪", "数据中心", "晶圆", "半导体", "台积电",
        "TSMC", "制程", "光刻", "HBM", "显存", "出货", "代工", "封装", "核电",
        "电力", "液冷", "超算", "chip", "datacenter", "data center", "compute",
        "semiconductor",
    ],
    "company_capital": [
        "融资", "收购", "并购", "合作", "财报", "营收", "利润", "股价", "市值",
        "上市", "IPO", "估值", "投资", "轮", "亿美元", "裁员", "高管", "CEO",
        "任命", "离职", "业务", "增长", "亏损", "盈利", "客户", "订单",
        "funding", "raises", "acquisition", "acquires", "valuation", "earnings",
        "revenue", "partnership",
    ],
    "policy_security": [
        "政策", "监管", "立法", "法律", "法规", "网信办", "工信部", "国务院",
        "欧盟", "美国国会", "白宫", "禁令", "限制", "出口管制", "关税", "制裁",
        "版权", "侵权", "诉讼", "隐私", "数据安全", "合规", "备案", "安全漏洞",
        "攻击", "伪造", "深度伪造", "伦理", "就业影响",
        "regulation", "policy", "lawsuit", "copyright", "privacy", "safety",
        "ban", "export control",
    ],
}

# 相关性过滤关键词：综合科技源必须命中其一才算 AI 资讯。
RELEVANCE_KEYWORDS: list[str] = [
    "AI", "人工智能", "大模型", "模型", "LLM", "GPT", "Gemini", "Claude",
    "DeepSeek", "智能体", "Agent", "机器学习", "深度学习", "神经网络", "多模态",
    "算力", "GPU", "AI芯片", "芯片", "英伟达", "NVIDIA", "OpenAI", "DeepMind",
    "Anthropic", "Copilot", "ChatGPT", "生成式", "AIGC", "推理模型",
]

# 标签词典：仅在标题/摘要出现足够证据时生成，不做猜测。
TAG_DICTIONARY: dict[str, str | None] = {
    # 公司 -> 股票代码（有明确上市主体时）
    "OpenAI": None,
    "Anthropic": None,
    "Google": "GOOGL",
    "谷歌": "GOOGL",
    "DeepMind": "GOOGL",
    "Microsoft": "MSFT",
    "微软": "MSFT",
    "Meta": "META",
    "苹果": "AAPL",
    "Apple": "AAPL",
    "NVIDIA": "NVDA",
    "英伟达": "NVDA",
    "AMD": "AMD",
    "英特尔": "INTC",
    "Intel": "INTC",
    "台积电": "TSM",
    "TSMC": "TSM",
    "特斯拉": "TSLA",
    "Tesla": "TSLA",
    "亚马逊": "AMZN",
    "Amazon": "AMZN",
    "华为": None,
    "阿里巴巴": "BABA",
    "阿里云": "BABA",
    "腾讯": "0700.HK",
    "百度": "BIDU",
    "字节跳动": None,
    "DeepSeek": None,
    "月之暗面": None,
    "智谱": None,
    "寒武纪": "688256.SS",
    "中芯国际": "00981.HK",
    "Arm": "ARM",
    "博通": "AVGO",
    "Broadcom": "AVGO",
    "美光": "MU",
    "三星": None,
    # 产品/技术标签 -> 无代码
    "ChatGPT": None,
    "Copilot": None,
    "Gemini": None,
    "GPT-5": None,
    "Claude": None,
    "Sora": None,
    "CUDA": None,
    "Hugging Face": None,
    "GitHub": None,
    "昇腾": None,
    "Groq": None,
}

# 热度加权词：涉及重点公司、政策或芯片时额外加分。
HOT_TERMS: list[str] = [
    "OpenAI", "NVIDIA", "英伟达", "Google", "微软", "DeepSeek", "Anthropic",
    "政策", "监管", "禁令", "芯片", "GPU", "算力", "融资", "并购",
]


# ---------------------------------------------------------------------------
# 来源清单
# ---------------------------------------------------------------------------

@dataclass
class SourceConfig:
    source_id: str
    name: str
    url: str
    kind: str = "feed"                # feed / hacker_news
    language: str = "en"
    vertical: bool = True             # AI 垂直源（免关键词过滤）
    weight: float = 0.8               # 热度计算中的来源权重 0~1
    enabled: bool = True
    interval_minutes: int | None = None  # None 则使用全局间隔


CORE_SOURCES: list[SourceConfig] = [
    SourceConfig("qbitai", "量子位", "https://www.qbitai.com/feed", language="zh", weight=0.9),
    SourceConfig("ithome", "IT之家", "https://www.ithome.com/rss/", language="zh", vertical=False, weight=0.7),
    SourceConfig("infoq", "InfoQ 中文", "https://www.infoq.cn/feed", language="zh", vertical=False, weight=0.75),
    SourceConfig("openai", "OpenAI", "https://openai.com/news/rss.xml", weight=1.0),
    SourceConfig("google_ai", "Google AI", "https://blog.google/technology/ai/rss/", weight=0.9),
    SourceConfig("deepmind", "Google DeepMind", "https://deepmind.google/blog/rss.xml", weight=0.95),
    SourceConfig("huggingface", "Hugging Face", "https://huggingface.co/blog/feed.xml", weight=0.85),
    SourceConfig("nvidia", "NVIDIA", "https://developer.nvidia.com/blog/category/generative-ai/feed/", weight=0.85),
    SourceConfig("techcrunch_ai", "TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", weight=0.8),
]

BACKUP_SOURCES: list[SourceConfig] = [
    SourceConfig("oschina", "开源中国", "https://www.oschina.net/news/rss", language="zh", vertical=False, weight=0.6, enabled=False),
    SourceConfig("venturebeat", "VentureBeat AI", "https://venturebeat.com/category/ai/feed/", weight=0.7, enabled=False),
    SourceConfig("microsoft", "Microsoft", "https://blogs.microsoft.com/feed/", vertical=False, weight=0.6, enabled=False),
    SourceConfig(
        "hackernews", "Hacker News",
        "https://hn.algolia.com/api/v1/search_by_date?tags=story&query=AI",
        kind="hacker_news", weight=0.5, enabled=False,
    ),
]

ALL_SOURCES: list[SourceConfig] = CORE_SOURCES + BACKUP_SOURCES


# ---------------------------------------------------------------------------
# 运行配置（环境变量 -> NewsSettings）
# ---------------------------------------------------------------------------

def _default_database_path() -> Path:
    configured = os.getenv("NEWS_DATABASE_PATH")
    if configured:
        return Path(configured)
    # 容器内 /data 为持久卷；本地开发落到用户目录，避免写入仓库。
    if Path("/data").is_dir():
        return Path("/data/news/news.db")
    return Path.home() / ".tradingagents" / "news" / "news.db"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default
    return max(low, min(high, value))


@dataclass
class NewsSettings:
    enabled: bool = True
    fetch_interval_minutes: int = 15
    request_timeout_seconds: float = 10.0
    max_response_bytes: int = 2 * 1024 * 1024
    max_concurrency: int = 4
    max_entries_per_fetch: int = 200
    retention_days: int = 90
    ai_summary_enabled: bool = True
    ai_max_items_per_run: int = 30
    ai_request_timeout_seconds: float = 60.0
    database_path: Path = field(default_factory=_default_database_path)
    # 可选：专用 AI 摘要端点；未配置时复用现有模型配置（DEFAULT_CONFIG）。
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_base_url: str | None = None

    @classmethod
    def from_env(cls) -> NewsSettings:
        interval = _env_int("NEWS_FETCH_INTERVAL_MINUTES", 15, 10, 30)
        return cls(
            enabled=_env_bool("NEWS_ENABLED", True),
            fetch_interval_minutes=interval,
            request_timeout_seconds=float(
                _env_int("NEWS_REQUEST_TIMEOUT_SECONDS", 10, 3, 60)
            ),
            max_response_bytes=_env_int("NEWS_MAX_RESPONSE_BYTES", 2 * 1024 * 1024, 64 * 1024, 16 * 1024 * 1024),
            max_concurrency=_env_int("NEWS_MAX_CONCURRENCY", 4, 1, 8),
            max_entries_per_fetch=_env_int("NEWS_MAX_ENTRIES_PER_FETCH", 200, 10, 1000),
            retention_days=_env_int("NEWS_RETENTION_DAYS", 90, 7, 365),
            ai_summary_enabled=_env_bool("NEWS_AI_SUMMARY_ENABLED", True),
            ai_max_items_per_run=_env_int("NEWS_AI_MAX_ITEMS_PER_RUN", 30, 0, 200),
            database_path=_default_database_path(),
            ai_provider=os.getenv("NEWS_AI_PROVIDER") or None,
            ai_model=os.getenv("NEWS_AI_MODEL") or None,
            ai_base_url=os.getenv("NEWS_AI_BASE_URL") or None,
        )


def sources_for_settings(settings: NewsSettings) -> list[SourceConfig]:
    """返回当前启用的来源列表（环境变量 NEWS_SOURCES 可覆盖启停）。"""
    override = os.getenv("NEWS_SOURCES", "").strip()
    if not override:
        return [s for s in ALL_SOURCES if s.enabled]
    wanted = {part.strip().lower() for part in override.split(",") if part.strip()}
    return [s for s in ALL_SOURCES if s.source_id in wanted]
