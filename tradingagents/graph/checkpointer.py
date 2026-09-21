"""支持可恢复分析运行的 LangGraph PostgreSQL 检查点。"""

from __future__ import annotations

import hashlib
from collections.abc import Generator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver


def _require_database_url(database_url: str | None) -> str:
    """校验 Checkpoint 数据库配置，禁止回退到本地文件数据库。"""
    if not database_url or not str(database_url).strip():
        raise RuntimeError(
            "未配置 TRADINGAGENTS_CHECKPOINT_DATABASE_URL，"
            "Checkpoint 必须使用 PostgreSQL，不能回退到本地文件数据库。"
        )
    normalized = str(database_url).strip()
    if not normalized.startswith(("postgresql://", "postgres://")):
        raise ValueError(
            "TRADINGAGENTS_CHECKPOINT_DATABASE_URL 必须是 PostgreSQL 连接串，"
            f"实际为：{normalized.split('://', 1)[0]}://..."
        )
    return normalized


def thread_id(ticker: str, date: str, signature: str = "") -> str:
    """返回股票代码+日期组合的确定性线程 ID。

    ``signature`` 会纳入影响图结构的运行选项，避免不同图错误复用检查点（#1089）；
    省略它则保持旧版 ID。
    """
    base = f"{ticker.upper()}:{date}"
    if signature:
        base = f"{base}:{signature}"
    return hashlib.sha256(base.encode()).hexdigest()[:16]


@contextmanager
def get_checkpointer(database_url: str | None) -> Generator[PostgresSaver, None, None]:
    """返回由 PostgreSQL 支持的 LangGraph Checkpoint saver。

    ``setup()`` 是幂等的，首次运行会创建 PostgreSQL 所需的检查点表和迁移。
    """
    uri = _require_database_url(database_url)
    with PostgresSaver.from_conn_string(uri) as saver:
        saver.setup()
        yield saver


def has_checkpoint(database_url: str | None, ticker: str, date: str, signature: str = "") -> bool:
    """检查指定股票代码+日期是否存在可恢复检查点。"""
    return checkpoint_step(database_url, ticker, date, signature) is not None


def checkpoint_step(
    database_url: str | None,
    ticker: str,
    date: str,
    signature: str = "",
) -> int | None:
    """返回最新检查点的步骤编号，不存在时返回 None。"""
    tid = thread_id(ticker, date, signature)
    with get_checkpointer(database_url) as saver:
        checkpoint = saver.get_tuple({"configurable": {"thread_id": tid}})
    if checkpoint is None:
        return None
    return checkpoint.metadata.get("step")


def clear_checkpoint(
    database_url: str | None,
    ticker: str,
    date: str,
    signature: str = "",
) -> None:
    """删除指定股票代码+日期对应的 PostgreSQL 检查点线程。"""
    tid = thread_id(ticker, date, signature)
    with get_checkpointer(database_url) as saver:
        saver.delete_thread(tid)
