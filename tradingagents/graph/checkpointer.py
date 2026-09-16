"""支持可恢复分析运行的 LangGraph 检查点。

每个股票代码使用独立的 SQLite 数据库，避免并发代码之间互相争用。
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from tradingagents.dataflows.utils import safe_ticker_component

logger = logging.getLogger(__name__)


def _db_path(data_dir: str | Path, ticker: str) -> Path:
    """返回指定股票代码的 SQLite 检查点数据库路径。"""
    # 拒绝会逃逸出检查点目录的股票代码。
    safe = safe_ticker_component(ticker).upper()
    p = Path(data_dir) / "checkpoints"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{safe}.db"


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
def get_checkpointer(data_dir: str | Path, ticker: str) -> Generator[SqliteSaver, None, None]:
    """上下文管理器：返回由每个股票代码独立数据库支持的 SqliteSaver。"""
    db = _db_path(data_dir, ticker)
    conn = sqlite3.connect(str(db), check_same_thread=False)
    try:
        saver = SqliteSaver(conn)
        saver.setup()
        logger.debug("已为 %s 打开检查点：%s", ticker, db)
        yield saver
    finally:
        conn.close()
        logger.debug("已关闭 %s 的检查点", ticker)


def has_checkpoint(data_dir: str | Path, ticker: str, date: str, signature: str = "") -> bool:
    """检查指定股票代码+日期是否存在可恢复检查点。"""
    return checkpoint_step(data_dir, ticker, date, signature) is not None


def checkpoint_step(data_dir: str | Path, ticker: str, date: str, signature: str = "") -> int | None:
    """返回最新检查点的步骤编号，不存在时返回 None。"""
    db = _db_path(data_dir, ticker)
    if not db.exists():
        logger.debug("%s 没有检查点数据库：%s", ticker, db)
        return None
    tid = thread_id(ticker, date, signature)
    with get_checkpointer(data_dir, ticker) as saver:
        config = {"configurable": {"thread_id": tid}}
        cp = saver.get_tuple(config)
        if cp is None:
            logger.debug("%s 在 %s 没有检查点元组（tid=%s）", ticker, date, tid)
            return None
        step = cp.metadata.get("step")
        logger.info("找到 %s 在 %s 的检查点，步骤为 %s", ticker, date, step)
        return step


def clear_all_checkpoints(data_dir: str | Path) -> int:
    """删除所有检查点数据库，并返回删除的文件数。"""
    cp_dir = Path(data_dir) / "checkpoints"
    if not cp_dir.exists():
        return 0
    dbs = list(cp_dir.glob("*.db"))
    for db in dbs:
        db.unlink()
    if dbs:
        logger.info("已从 %s 清除 %d 个检查点数据库", cp_dir, len(dbs))
    return len(dbs)


def clear_checkpoint(data_dir: str | Path, ticker: str, date: str, signature: str = "") -> None:
    """通过删除线程记录，清除指定股票代码+日期的检查点。"""
    db = _db_path(data_dir, ticker)
    if not db.exists():
        return
    tid = thread_id(ticker, date, signature)
    conn = sqlite3.connect(str(db))
    try:
        for table in ("writes", "checkpoints"):
            conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (tid,))
        conn.commit()
        logger.info("已清除 %s 在 %s 的检查点（tid=%s）", ticker, date, tid)
    except sqlite3.OperationalError:
        logger.warning("清除 %s 在 %s 的检查点失败", ticker, date)
    finally:
        conn.close()
