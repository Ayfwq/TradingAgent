import contextlib
import warnings

# 在包导入时加载 .env 文件，使 DEFAULT_CONFIG 的环境变量覆盖（以及所有 llm_clients
# 调用方）无论由哪个入口启动进程都能看到用户密钥。find_dotenv(usecwd=True) 从当前
# 工作目录开始查找，因此已安装的 `tradingagents` 控制台脚本会读取项目 .env，
# 不会从 site-packages 向上查找。load_dotenv 默认 override=False，因此不会覆盖调用方
# 已导出的值。
try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
    load_dotenv(find_dotenv(".env.enterprise", usecwd=True), override=False)
except ImportError:
    pass

# langchain-core 1.3.3 会在自己的 __init__ 中调用
# surface_langchain_deprecation_warnings()，为子类警告类别预置 default-action 过滤器。
# 要抑制特定警告，必须在 langchain-core 安装自身过滤器后再安装我们的过滤器，
# 因此先导入它。langgraph 会传递依赖该包。
with contextlib.suppress(ImportError):
    import langchain_core  # noqa: F401

# langgraph-checkpoint 4.0.3 在加载模块时调用 Reviver()，但没有显式传入
# allowed_objects，导致解释器每次启动都收到 langchain-core 1.3.3 的嘈杂待弃用警告。
# 修复已在上游合并（langchain-ai/langgraph#7743，2026-05-08），会随下一版
# langgraph-checkpoint 发布。升级超过该版本后删除此代码块（及上面的 langchain_core 预加载）。
warnings.filterwarnings(
    "ignore",
    # 上游警告文本为协议匹配内容，保持英文正则以便准确过滤。
    message=r"The default value of `allowed_objects`.*",
    category=PendingDeprecationWarning,
)

# 每个进程配置一次统一的控制台 + 按天轮转文件日志。
# 所有入口（main.py、Web 服务器、脚本）都会导入此包，因此运维始终能得到
# 一致且可查询的日志流。
with contextlib.suppress(Exception):
    from .logging_utils import setup_logging as _setup_logging

    _setup_logging()
