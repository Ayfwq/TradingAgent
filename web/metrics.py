"""Prometheus 监控指标定义与暴露。

为 TradingAgents 项目提供统一的指标注册表，供 Web 服务、News Worker 和 LLM 调用使用。
"""

from __future__ import annotations

import os

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector

# 使用 prometheus-client 默认注册表，保留其 process_*、python_* 等运行时指标。
# Web 端点由 prometheus-fastapi-instrumentator 注册到同一个默认注册表。


# ============================================================================
# 分析任务状态计数
ANALYSIS_TASKS_TOTAL = Counter(
    "analysis_tasks_total",
    "按状态统计的分析任务总数",
    ["status"],
    registry=REGISTRY,
)

# 分析任务执行时间
ANALYSIS_TASK_DURATION_SECONDS = Histogram(
    "analysis_task_duration_seconds",
    "分析任务执行时间（秒）",
    ["ticker", "asset_type"],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
    registry=REGISTRY,
)

# 当前正在执行的分析任务数
ANALYSIS_TASKS_RUNNING = Gauge(
    "analysis_tasks_running",
    "当前正在运行的分析任务数",
    registry=REGISTRY,
)

# 内存中记录的任务数量
ANALYSIS_RECORDS_COUNT = Gauge(
    "analysis_records_count",
    "内存中的分析记录数",
    registry=REGISTRY,
)


# ============================================================================
# News Worker 指标
# ============================================================================

# News 采集轮次计数
NEWS_FETCH_RUNS_TOTAL = Counter(
    "news_fetch_runs_total",
    "新闻采集轮次总数",
    ["status"],
    registry=REGISTRY,
)

# News 采集时间
NEWS_FETCH_DURATION_SECONDS = Histogram(
    "news_fetch_duration_seconds",
    "新闻采集轮次耗时（秒）",
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0),
    registry=REGISTRY,
)

# 来源处理结果计数
NEWS_SOURCE_RESULTS_TOTAL = Counter(
    "news_source_results_total",
    "新闻来源处理结果总数",
    ["source_id", "status"],
    registry=REGISTRY,
)

# 来源处理时间
NEWS_SOURCE_DURATION_SECONDS = Histogram(
    "news_source_duration_seconds",
    "新闻来源处理耗时（秒）",
    ["source_id"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    registry=REGISTRY,
)

# News 条目统计
NEWS_ITEMS_TOTAL = Counter(
    "news_items_total",
    "已处理的新闻条目总数",
    ["disposition"],
    registry=REGISTRY,
)

# AI 摘要统计
NEWS_AI_SUMMARIES_TOTAL = Counter(
    "news_ai_summaries_total",
    "生成的 AI 摘要总数",
    ["status"],
    registry=REGISTRY,
)

# News 数据库中的总条目数
NEWS_ITEMS_IN_DB = Gauge(
    "news_items_in_db",
    "数据库中的新闻条目总数",
    registry=REGISTRY,
)

# Worker 心跳年龄（秒）
NEWS_WORKER_HEARTBEAT_AGE_SECONDS = Gauge(
    "news_worker_heartbeat_age_seconds",
    "距离上次 Worker 心跳的秒数",
    registry=REGISTRY,
)

# 启用的来源数量
NEWS_ENABLED_SOURCES = Gauge(
    "news_enabled_sources",
    "已启用的新闻来源数",
    registry=REGISTRY,
)


# ============================================================================
# LLM / Agent 指标
# ============================================================================

# LLM 调用计数
LLM_REQUESTS_TOTAL = Counter(
    "llm_requests_total",
    "LLM API 请求总数",
    ["provider", "model", "status"],
    registry=REGISTRY,
)

# LLM 调用时间
LLM_REQUEST_DURATION_SECONDS = Histogram(
    "llm_request_duration_seconds",
    "LLM API 请求耗时（秒）",
    ["provider", "model"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    registry=REGISTRY,
)

# LLM Token 使用量
LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "已使用的 LLM token 总数",
    ["provider", "model", "type"],
    registry=REGISTRY,
)

# Agent 执行步骤计数
AGENT_STEPS_TOTAL = Counter(
    "agent_steps_total",
    "智能体执行步骤总数",
    ["agent_type", "status"],
    registry=REGISTRY,
)

# Agent 执行时间
AGENT_STEP_DURATION_SECONDS = Histogram(
    "agent_step_duration_seconds",
    "智能体步骤执行耗时（秒）",
    ["agent_type"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
    registry=REGISTRY,
)


# ============================================================================
# 系统指标
# ============================================================================

# 应用启动时间
APP_START_TIME = Gauge(
    "app_start_time_seconds",
    "应用启动时间（距 Unix 纪元的秒数）",
    registry=REGISTRY,
)

# 应用运行时间
APP_UPTIME_SECONDS = Gauge(
    "app_uptime_seconds",
    "应用运行时间（秒）",
    registry=REGISTRY,
)


# ============================================================================
# 辅助函数
# ============================================================================


if os.name == "nt":
    class _WindowsProcessCollector(Collector):
        """补充 Windows 上 prometheus-client 默认 ProcessCollector 缺失的指标。

        生产镜像运行在 Linux 时直接使用 prometheus-client 默认 collector；Windows
        本地开发环境没有 /proc，因此默认 collector 不会产生 process_* 样本。
        """

        def collect(self):
            try:
                import psutil
            except ImportError:
                return
            try:
                process = psutil.Process()
                memory = process.memory_info()
                cpu = process.cpu_times()
                yield GaugeMetricFamily(
                    "process_virtual_memory_bytes",
                    "虚拟内存大小（字节）。",
                    value=float(memory.vms),
                )
                yield GaugeMetricFamily(
                    "process_resident_memory_bytes",
                    "驻留内存大小（字节）。",
                    value=float(memory.rss),
                )
                yield GaugeMetricFamily(
                    "process_start_time_seconds",
                    "进程启动时间（距 Unix 纪元的秒数）。",
                    value=float(process.create_time()),
                )
                yield CounterMetricFamily(
                    "process_cpu_seconds_total",
                    "用户态和系统态 CPU 总耗时（秒）。",
                    value=float(cpu.user + cpu.system),
                )
                yield GaugeMetricFamily(
                    "process_open_fds",
                    "进程打开的句柄数。",
                    value=float(process.num_handles()),
                )
            except (OSError, psutil.Error):
                return


    REGISTRY.register(_WindowsProcessCollector())

def generate_metrics() -> bytes:
    """生成 Prometheus 格式的指标数据。"""
    return generate_latest(REGISTRY)


def get_registry() -> CollectorRegistry:
    """获取指标注册表。"""
    return REGISTRY
