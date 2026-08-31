"""Persistent report history backed by the report tree on disk.

The analysis worker already writes every completed run under
``<results_dir>/reports/<ticker>_<timestamp>``.  This module indexes those
directories on demand instead of keeping a second in-memory database, so old
reports remain available after a web-server restart and existing reports are
discovered automatically.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from tradingagents.default_config import DEFAULT_CONFIG

_REPORT_ID_RE = re.compile(r"^(?P<ticker>.+)_(?P<stamp>\d{8}_\d{6})$")
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
    limit: int = 50,
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
        if len(items) >= limit:
            break
    return {"reports": items, "total": len(items), "root": str(reports_root())}


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
