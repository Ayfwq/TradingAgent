"""由磁盘报告目录支持的持久化报告历史。

分析 Worker 已将每次完成的运行写入
``<results_dir>/reports/<ticker>_<timestamp>``.  This module indexes those
本模块按需为这些目录建立索引，而不是维护第二个内存数据库，因此 Web 服务器重启后
旧报告仍可用，已有报告也会自动发现。
"""

from __future__ import annotations

import json
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.utils import safe_ticker_component

_REPORT_ID_RE = re.compile(r"^(?P<ticker>.+)_(?P<stamp>\d{8}_\d{6})$")
_REPORT_DELETE_LOCK = threading.Lock()
_FIELD_RE = re.compile(r"\*\*(?P<name>[^*]+)\*\*:\s*(?P<value>[^\n]+)")

_SECTION_FILES = {
    "market": "1_analysts/market.md",
    "sentiment": "1_analysts/sentiment.md",
    "news": "1_analysts/news.md",
    "fundamentals": "1_analysts/fundamentals.md",
}
_RESEARCH_FILES = {
    "bull": "2_research/bull.md",
    "bear": "2_research/bear.md",
    "manager": "2_research/manager.md",
}
_RISK_FILES = {
    "aggressive": "4_risk/aggressive.md",
    "neutral": "4_risk/neutral.md",
    "conservative": "4_risk/conservative.md",
}


def reports_root() -> Path:
    return Path(DEFAULT_CONFIG["results_dir"]) / "reports"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _parse_fields(markdown: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _FIELD_RE.finditer(markdown or ""):
        key = match.group("name").strip().lower().replace(" ", "_")
        fields[key] = match.group("value").strip().strip("*")
    return fields


def _metadata(directory: Path, ticker: str, stamp: str) -> dict[str, Any]:
    generated_at = datetime.strptime(stamp, "%Y%m%d_%H%M%S").isoformat(sep=" ")
    metadata_path = directory / "metadata.json"
    if metadata_path.exists():
        try:
            saved = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                generated_at = saved.get("generated_at") or generated_at
                return {
                    "ticker": saved.get("ticker") or ticker,
                    "trade_date": saved.get("trade_date") or generated_at[:10],
                    "asset_type": saved.get("asset_type") or "stock",
                    "generated_at": generated_at,
                }
        except (OSError, UnicodeError, ValueError):
            pass
    return {
        "ticker": ticker,
        "trade_date": generated_at[:10],
        "asset_type": "stock",
        "generated_at": generated_at,
    }


def _iter_report_dirs() -> list[tuple[str, Path, dict[str, Any]]]:
    root = reports_root()
    if not root.exists():
        return []
    entries = []
    for directory in root.iterdir():
        if not directory.is_dir() or not (directory / "complete_report.md").exists():
            continue
        match = _REPORT_ID_RE.fullmatch(directory.name)
        if not match:
            continue
        metadata = _metadata(directory, match.group("ticker"), match.group("stamp"))
        entries.append((directory.name, directory, metadata))
    return sorted(entries, key=lambda item: item[2]["generated_at"], reverse=True)


def list_reports(
    *,
    query: str = "",
    ticker: str = "",
    start_date: str = "",
    end_date: str = "",
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    query_norm = query.strip().casefold()
    ticker_norm = ticker.strip().casefold()
    items = []
    for report_id, _directory, metadata in _iter_report_dirs():
        name = str(metadata["ticker"])
        if ticker_norm and name.casefold() != ticker_norm:
            continue
        if query_norm and query_norm not in f"{name} {report_id}".casefold():
            continue
        trade_date = str(metadata["trade_date"])
        if start_date and trade_date < start_date:
            continue
        if end_date and trade_date > end_date:
            continue
        items.append({
            "id": report_id,
            **metadata,
            "title": "投资研究报告",
        })
    total = len(items)
    start = max(0, offset)
    return {
        "reports": items[start : start + max(1, limit)],
        "total": total,
        "offset": start,
        "limit": max(1, limit),
        "root": str(reports_root()),
    }


def get_report(report_id: str) -> dict[str, Any] | None:
    if not _REPORT_ID_RE.fullmatch(report_id):
        return None
    root = reports_root().resolve()
    directory = (root / report_id).resolve()
    if directory.parent != root or not directory.is_dir():
        return None
    match = _REPORT_ID_RE.fullmatch(report_id)
    if match is None or not (directory / "complete_report.md").exists():
        return None
    metadata = _metadata(directory, match.group("ticker"), match.group("stamp"))
    final_report = _read(directory / "5_portfolio/decision.md")
    trader_report = _read(directory / "3_trading/trader.md")
    decision_fields = _parse_fields(final_report)
    trader_fields = _parse_fields(trader_report)
    return {
        "id": report_id,
        **metadata,
        "result": {
            "decision": decision_fields.get("rating", "—"),
            "decision_fields": decision_fields,
            "trader_fields": trader_fields,
            "final_report": final_report,
            "complete_report": _read(directory / "complete_report.md"),
            "reports": {key: _read(directory / path) for key, path in _SECTION_FILES.items()},
            "research": {key: _read(directory / path) for key, path in _RESEARCH_FILES.items()},
            "trader_report": trader_report,
            "risk": {key: _read(directory / path) for key, path in _RISK_FILES.items()},
        },
    }


def _delete_report_sidecars(ticker: str, trade_date: str) -> None:
    """Remove persisted analysis copies when no archived report still owns them.

    The state snapshot and decision-memory entry are keyed by ticker + trade date,
    not by report ID. Keep them while a same-day report remains; otherwise remove
    them together with the last report for that key.
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", trade_date):
        return
    try:
        safe_ticker = safe_ticker_component(ticker)
    except ValueError:
        # Do not construct a path from malformed metadata.
        return

    state_root = (Path(DEFAULT_CONFIG["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs").resolve()
    results_root = Path(DEFAULT_CONFIG["results_dir"]).resolve()
    if state_root.is_relative_to(results_root):
        state_snapshot = state_root / f"full_states_log_{trade_date}.json"
        if state_snapshot.is_file():
            state_snapshot.unlink()

    memory_log = Path(DEFAULT_CONFIG.get("memory_log_path") or "").expanduser()
    if not str(memory_log):
        return
    if not memory_log.is_file():
        return

    separator = "\n\n<!-- ENTRY_END -->\n\n"
    original = memory_log.read_text(encoding="utf-8")
    blocks = original.split(separator)
    kept = []
    for block in blocks:
        first_line = block.strip().splitlines()[0] if block.strip() else ""
        fields = first_line[1:-1].split("|") if first_line.startswith("[") and first_line.endswith("]") else []
        if len(fields) >= 2 and fields[0].strip() == trade_date and fields[1].strip() == ticker:
            continue
        kept.append(block)
    updated = separator.join(kept)
    if updated != original:
        temp_path = memory_log.with_suffix(memory_log.suffix + ".tmp")
        temp_path.write_text(updated, encoding="utf-8")
        temp_path.replace(memory_log)


def delete_report(report_id: str) -> bool:
    """Delete a report and any remaining ticker/date analysis sidecars."""
    # Serialize the sibling-report check and removal so concurrent deletes of
    # every same-day report cannot each leave the shared sidecars behind.
    with _REPORT_DELETE_LOCK:
        return _delete_report_locked(report_id)


def _delete_report_locked(report_id: str) -> bool:
    if not _REPORT_ID_RE.fullmatch(report_id):
        return False
    root = reports_root().resolve()
    directory = (root / report_id).resolve()
    if directory.parent != root or not directory.is_dir():
        return False
    if not (directory / "complete_report.md").is_file():
        return False

    match = _REPORT_ID_RE.fullmatch(report_id)
    metadata = _metadata(directory, match.group("ticker"), match.group("stamp"))
    ticker = str(metadata["ticker"])
    trade_date = str(metadata["trade_date"])
    same_day_reports_remain = any(
        other_id != report_id
        and str(other_metadata["ticker"]).casefold() == ticker.casefold()
        and str(other_metadata["trade_date"]) == trade_date
        for other_id, _other_directory, other_metadata in _iter_report_dirs()
    )

    # These legacy sidecars are shared by ticker/date, so deleting them while a
    # sibling report still exists would erase data that report may rely on.
    if not same_day_reports_remain:
        _delete_report_sidecars(ticker, trade_date)
    shutil.rmtree(directory)
    return True
