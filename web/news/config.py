"""AI 资讯模块：来源清单、分类规则与运行配置。

所有参数均可通过环境变量覆盖（见 DEPLOYMENT.md），此处提供安全默认值。
来源准入遵循 AI_NEWS_MODULE_PLAN.md 第 4.4 节：仅 HTTPS、无需登录、
不绕过反爬、允许聚合读取的官方 RSS/Atom/API。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
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
    # A 股 AI 产业链：政策、算力硬件、端侧应用与数字基础设施。
    "人形机器人", "机器人", "脑机接口", "智能驾驶", "自动驾驶",
    "智算", "智算中心", "算力中心", "数据要素", "工业互联网", "智能制造",
    "光模块", "CPO", "HBM", "液冷", "半导体", "先进封装", "信创", "国产替代",
    "科大讯飞", "中科曙光", "浪潮信息", "工业富联", "海光信息",
    "中际旭创", "新易盛", "天孚通信", "北方华创", "中微公司", "澜起科技",
    "昆仑万维", "金山办公", "云从科技", "寒武纪", "中芯国际",
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
    "海光信息": "688041.SS",
    "科大讯飞": "002230.SZ",
    "中科曙光": "603019.SS",
    "浪潮信息": "000977.SZ",
    "工业富联": "601138.SS",
    "中际旭创": "300308.SZ",
    "新易盛": "300502.SZ",
    "天孚通信": "300394.SZ",
    "北方华创": "002371.SZ",
    "中微公司": "688012.SS",
    "澜起科技": "688008.SS",
    "昆仑万维": "300418.SZ",
    "金山办公": "688111.SS",
    "云从科技": "688327.SS",
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
    "人形机器人", "脑机接口", "智算中心", "科大讯飞", "寒武纪", "海光信息",
]


# ---------------------------------------------------------------------------
# 来源清单
# ---------------------------------------------------------------------------


@dataclass
class SourceConfig:
    source_id: str
    name: str
    url: str
    kind: str = "feed"  # feed / cls_finance / eastmoney_finance / hacker_news
    language: str = "en"
    vertical: bool = True  # AI 垂直源（免关键词过滤）
    weight: float = 0.8  # 热度计算中的来源权重 0~1
    source_type: str = "specialist"  # primary / major_media / specialist / aggregator
    authority_score: int = 70  # 编辑信誉分，用于精选与跨源去重 0~100
    region: str = "global"  # cn / global
    a_share_relevance: int = 30  # 对 A 股政策、产业链与上市公司的关联度 0~100
    enabled: bool = True
    interval_minutes: int | None = None  # None 则使用全局间隔


SOURCE_TYPE_LABELS: dict[str, str] = {
    "primary": "官方一手",
    "major_media": "权威媒体",
    "specialist": "专业媒体",
    "aggregator": "综合聚合",
}


CORE_SOURCES: list[SourceConfig] = [
    # 国内官方与 A 股财经源：默认优先，覆盖政策、产业链和上市公司动态。
    SourceConfig(
        "miit_news",
        "工业和信息化部·工信动态",
        "https://www.miit.gov.cn/api-gateway/jpaas-plugins-web-server/front/rss/getinfo?"
        "webId=8d828e408d90447786ddbe128d495e9e&"
        "columnIds=d3e2bede1bc045e2875fc7161c01db7d",
        language="zh",
        vertical=False,
        weight=1.0,
        source_type="primary",
        authority_score=100,
        region="cn",
        a_share_relevance=100,
    ),
    SourceConfig(
        "miit_policy",
        "工业和信息化部·征求意见",
        "https://www.miit.gov.cn/api-gateway/jpaas-plugins-web-server/front/rss/getinfo?"
        "webId=8d828e408d90447786ddbe128d495e9e&"
        "columnIds=ff3aac0962cb45e48e8e4da69450e847",
        language="zh",
        vertical=False,
        weight=1.0,
        source_type="primary",
        authority_score=100,
        region="cn",
        a_share_relevance=100,
    ),
    SourceConfig(
        "cls_finance",
        "财联社·A股电报",
        "https://www.cls.cn/v1/roll/get_roll_list",
        kind="cls_finance",
        language="zh",
        vertical=False,
        weight=0.9,
        source_type="major_media",
        authority_score=90,
        region="cn",
        a_share_relevance=98,
    ),
    SourceConfig(
        "eastmoney_finance",
        "东方财富·7×24",
        "https://np-weblist.eastmoney.com/comm/web/getFastNewsList",
        kind="eastmoney_finance",
        language="zh",
        vertical=False,
        weight=0.82,
        source_type="specialist",
        authority_score=80,
        region="cn",
        a_share_relevance=95,
    ),
    SourceConfig(
        "chinanews_finance",
        "中国新闻网·财经",
        "https://www.chinanews.com.cn/rss/finance.xml",
        language="zh",
        vertical=False,
        weight=0.93,
        source_type="major_media",
        authority_score=94,
        region="cn",
        a_share_relevance=92,
    ),
    SourceConfig(
        "chinanews_latest",
        "中国新闻网·即时",
        "https://www.chinanews.com.cn/rss/scroll-news.xml",
        language="zh",
        vertical=False,
        weight=0.92,
        source_type="major_media",
        authority_score=93,
        region="cn",
        a_share_relevance=88,
    ),
    # 一手来源：适合确认产品发布、研究进展与公司立场；不代表独立评论。
    SourceConfig(
        "openai",
        "OpenAI",
        "https://openai.com/news/rss.xml",
        weight=1.0,
        source_type="primary",
        authority_score=100,
    ),
    SourceConfig(
        "deepmind",
        "Google DeepMind",
        "https://deepmind.google/blog/rss.xml",
        weight=0.98,
        source_type="primary",
        authority_score=100,
    ),
    SourceConfig(
        "google_ai",
        "Google AI",
        "https://blog.google/technology/ai/rss/",
        weight=0.97,
        source_type="primary",
        authority_score=98,
    ),
    SourceConfig(
        "google_research",
        "Google Research",
        "https://research.google/blog/rss/",
        weight=0.97,
        source_type="primary",
        authority_score=98,
        enabled=False,
    ),
    SourceConfig(
        "microsoft",
        "Microsoft 官方博客",
        "https://blogs.microsoft.com/feed/",
        vertical=False,
        weight=0.96,
        source_type="primary",
        authority_score=98,
    ),
    SourceConfig(
        "microsoft_research",
        "Microsoft Research",
        "https://www.microsoft.com/en-us/research/feed/",
        vertical=False,
        weight=0.97,
        source_type="primary",
        authority_score=99,
        enabled=False,
    ),
    SourceConfig(
        "aws_ml",
        "AWS Machine Learning",
        "https://aws.amazon.com/blogs/machine-learning/feed/",
        weight=0.94,
        source_type="primary",
        authority_score=96,
        enabled=False,
    ),
    SourceConfig(
        "nvidia",
        "NVIDIA",
        "https://developer.nvidia.com/blog/category/generative-ai/feed/",
        weight=0.95,
        source_type="primary",
        authority_score=97,
    ),
    SourceConfig(
        "huggingface",
        "Hugging Face",
        "https://huggingface.co/blog/feed.xml",
        weight=0.9,
        source_type="primary",
        authority_score=92,
        enabled=False,
    ),
    # 独立编辑/学术来源：用于交叉核对官方说法并补充影响分析。
    SourceConfig(
        "nature_ml",
        "Nature · Machine Learning",
        "https://www.nature.com/subjects/machine-learning.rss",
        weight=0.98,
        source_type="major_media",
        authority_score=98,
    ),
    SourceConfig(
        "mit_tech_review_ai",
        "MIT Technology Review · AI",
        "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
        weight=0.95,
        source_type="major_media",
        authority_score=96,
    ),
    SourceConfig(
        "bbc_technology",
        "BBC Technology",
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
        vertical=False,
        weight=0.94,
        source_type="major_media",
        authority_score=95,
        enabled=False,
    ),
    SourceConfig(
        "guardian_ai",
        "The Guardian · AI",
        "https://www.theguardian.com/technology/artificialintelligenceai/rss",
        weight=0.9,
        source_type="major_media",
        authority_score=91,
        enabled=False,
    ),
    SourceConfig(
        "techcrunch_ai",
        "TechCrunch AI",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        weight=0.84,
        source_type="major_media",
        authority_score=84,
    ),
    # 中文专业媒体：保留中文可读性，但精选优先级低于官方与权威媒体。
    SourceConfig(
        "infoq",
        "InfoQ 中文",
        "https://www.infoq.cn/feed",
        language="zh",
        vertical=False,
        weight=0.8,
        source_type="specialist",
        authority_score=80,
        region="cn",
        a_share_relevance=82,
    ),
    SourceConfig(
        "qbitai",
        "量子位",
        "https://www.qbitai.com/feed",
        language="zh",
        weight=0.78,
        source_type="specialist",
        authority_score=76,
        region="cn",
        a_share_relevance=85,
    ),
]

BACKUP_SOURCES: list[SourceConfig] = [
    # 综合/聚合源默认不采集；只能通过 NEWS_SOURCES 显式启用。
    SourceConfig(
        "ithome",
        "IT之家",
        "https://www.ithome.com/rss/",
        language="zh",
        vertical=False,
        weight=0.45,
        source_type="aggregator",
        authority_score=45,
        region="cn",
        a_share_relevance=65,
        enabled=False,
    ),
    SourceConfig(
        "oschina",
        "开源中国",
        "https://www.oschina.net/news/rss",
        language="zh",
        vertical=False,
        weight=0.55,
        source_type="aggregator",
        authority_score=55,
        region="cn",
        a_share_relevance=65,
        enabled=False,
    ),
    SourceConfig(
        "venturebeat",
        "VentureBeat AI",
        "https://venturebeat.com/category/ai/feed/",
        weight=0.68,
        source_type="specialist",
        authority_score=68,
        enabled=False,
    ),
    SourceConfig(
        "hackernews",
        "Hacker News",
        "https://hn.algolia.com/api/v1/search_by_date?tags=story&query=AI",
        kind="hacker_news",
        weight=0.4,
        source_type="aggregator",
        authority_score=35,
        enabled=False,
    ),
]

ALL_SOURCES: list[SourceConfig] = CORE_SOURCES + BACKUP_SOURCES
SOURCE_BY_ID: dict[str, SourceConfig] = {source.source_id: source for source in ALL_SOURCES}


def source_metadata(source_id: str) -> dict[str, str | int]:
    """返回可公开的来源信誉元数据；未登记源按中性值处理。"""
    source = SOURCE_BY_ID.get(source_id)
    source_type = source.source_type if source else "specialist"
    return {
        "source_type": source_type,
        "authority_label": SOURCE_TYPE_LABELS.get(source_type, "未评级来源"),
        "authority_score": source.authority_score if source else 50,
        "region": source.region if source else "global",
        "region_label": "国内来源" if source and source.region == "cn" else "海外来源",
        "a_share_relevance": source.a_share_relevance if source else 20,
    }


def source_authority_score(source_id: str) -> int:
    return int(source_metadata(source_id)["authority_score"])


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
    max_items_per_source_per_day: int = 8
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
            request_timeout_seconds=float(_env_int("NEWS_REQUEST_TIMEOUT_SECONDS", 10, 3, 60)),
            max_response_bytes=_env_int(
                "NEWS_MAX_RESPONSE_BYTES", 2 * 1024 * 1024, 64 * 1024, 16 * 1024 * 1024
            ),
            max_concurrency=_env_int("NEWS_MAX_CONCURRENCY", 4, 1, 8),
            max_entries_per_fetch=_env_int("NEWS_MAX_ENTRIES_PER_FETCH", 200, 10, 1000),
            retention_days=_env_int("NEWS_RETENTION_DAYS", 90, 7, 365),
            ai_summary_enabled=_env_bool("NEWS_AI_SUMMARY_ENABLED", True),
            ai_max_items_per_run=_env_int("NEWS_AI_MAX_ITEMS_PER_RUN", 30, 0, 200),
            max_items_per_source_per_day=_env_int("NEWS_MAX_ITEMS_PER_SOURCE_PER_DAY", 8, 1, 50),
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
    return [replace(s, enabled=True) for s in ALL_SOURCES if s.source_id in wanted]


def all_sources_enabled() -> list[SourceConfig]:
    """仅供显式 --all-sources 调试模式使用。"""
    return [replace(source, enabled=True) for source in ALL_SOURCES]
