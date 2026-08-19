from __future__ import annotations

import asyncio
import logging
import re
import threading
import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TICKER_RE = re.compile(r"^[A-Za-z0-9.^=_-]{1,24}$")
FIELD_RE = re.compile(r"\*\*(?P<name>[^*]+)\*\*:\s*(?P<value>[^\n]+)")


class AnalysisRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=24)
    trade_date: date
    asset_type: Literal["stock", "crypto"] = "stock"
    analysts: list[Literal["market", "social", "news", "fundamentals"]] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not TICKER_RE.fullmatch(normalized):
            raise ValueError("股票代码只能包含字母、数字以及 . ^ = _ -")
        return normalized

    @field_validator("trade_date")
    @classmethod
    def validate_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("分析日期不能晚于今天")
        return value

    @field_validator("analysts")
    @classmethod
    def validate_analysts(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("至少选择一位分析师")
        return list(dict.fromkeys(value))


class AnalysisRecord(BaseModel):
    id: str
    ticker: str
    trade_date: str
    status: Literal["queued", "running", "completed", "failed"]
    phase: str
    created_at: str
    updated_at: str
    result: dict | None = None
    error: str | None = None


app = FastAPI(
    title="TradingAgents AI 研报",
    description="面向普通投资者的多智能体股票研究报告服务",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_records: dict[str, AnalysisRecord] = {}
_records_lock = threading.Lock()
_analysis_gate = asyncio.Semaphore(1)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_record(task_id: str, **changes) -> None:
    with _records_lock:
        current = _records[task_id]
        _records[task_id] = current.model_copy(
            update={**changes, "updated_at": _utc_now()}
        )


def _parse_fields(markdown: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in FIELD_RE.finditer(markdown or ""):
        key = match.group("name").strip().lower().replace(" ", "_")
        fields[key] = match.group("value").strip().strip("*")
    return fields


def _present_result(final_state: dict, decision: str) -> dict:
    final_text = final_state.get("final_trade_decision", "")
    trader_text = final_state.get("trader_investment_plan", "")
    debate = final_state.get("investment_debate_state") or {}
    risk = final_state.get("risk_debate_state") or {}
    return {
        "decision": decision,
        "decision_fields": _parse_fields(final_text),
        "trader_fields": _parse_fields(trader_text),
        "final_report": final_text,
        "reports": {
            "market": final_state.get("market_report", ""),
            "sentiment": final_state.get("sentiment_report", ""),
            "news": final_state.get("news_report", ""),
            "fundamentals": final_state.get("fundamentals_report", ""),
        },
        "research": {
            "bull": debate.get("bull_history", ""),
            "bear": debate.get("bear_history", ""),
            "manager": debate.get("judge_decision", ""),
        },
        "trader_report": trader_text,
        "risk": {
            "aggressive": risk.get("aggressive_history", ""),
            "neutral": risk.get("neutral_history", ""),
            "conservative": risk.get("conservative_history", ""),
        },
    }


def _run_analysis(payload: AnalysisRequest) -> dict:
    config = deepcopy(DEFAULT_CONFIG)
    config["checkpoint_enabled"] = True
    graph = TradingAgentsGraph(
        selected_analysts=payload.analysts,
        debug=False,
        config=config,
    )
    final_state, decision = graph.propagate(
        payload.ticker,
        payload.trade_date.isoformat(),
        asset_type=payload.asset_type,
    )
    graph.save_reports(final_state, payload.ticker)
    return _present_result(final_state, decision)


async def _execute(task_id: str, payload: AnalysisRequest) -> None:
    async with _analysis_gate:
        _update_record(task_id, status="running", phase="多智能体正在协作分析")
        try:
            result = await asyncio.to_thread(_run_analysis, payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Analysis %s failed", task_id)
            _update_record(
                task_id,
                status="failed",
                phase="分析未完成",
                error=f"分析失败：{type(exc).__name__}。请检查模型密钥、网络和数据源配置。",
            )
            return
        _update_record(
            task_id,
            status="completed",
            phase="研报已生成",
            result=result,
        )


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyses", status_code=202)
async def create_analysis(payload: AnalysisRequest) -> dict[str, str]:
    task_id = uuid.uuid4().hex
    now = _utc_now()
    record = AnalysisRecord(
        id=task_id,
        ticker=payload.ticker,
        trade_date=payload.trade_date.isoformat(),
        status="queued",
        phase="等待分析资源",
        created_at=now,
        updated_at=now,
    )
    with _records_lock:
        _records[task_id] = record
    asyncio.create_task(_execute(task_id, payload))
    return {"id": task_id, "status": "queued"}


@app.get("/api/analyses/{task_id}", response_model=AnalysisRecord)
async def get_analysis(task_id: str) -> AnalysisRecord:
    with _records_lock:
        record = _records.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="分析任务不存在或服务已重启")
    return record
