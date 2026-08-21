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

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from web.instrument_search import instrument_search_service
from web.model_profiles import MODEL_TEMPLATES, model_profile_service

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
    model_profile_id: str | None = Field(default=None, max_length=64)

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


class InstrumentSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    market: Literal["auto", "a_share", "hk", "us"] = "auto"
    use_ai: bool = True

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("请输入公司名称、股票代码或公司描述")
        return normalized


class ModelProfilePayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    template: str = Field(default="custom", max_length=40)
    base_url: str = Field(min_length=8, max_length=300)
    quick_model: str = Field(min_length=1, max_length=160)
    deep_model: str = Field(default="", max_length=160)
    api_key: str | None = Field(default=None, max_length=1000)


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
    logger.debug(
        "Running analysis: ticker=%s trade_date=%s asset_type=%s analysts=%s profile_id=%s",
        payload.ticker, payload.trade_date.isoformat(), payload.asset_type,
        payload.analysts, payload.model_profile_id,
    )
    config = deepcopy(DEFAULT_CONFIG)
    config["checkpoint_enabled"] = True
    if payload.model_profile_id:
        try:
            config.update(model_profile_service.graph_overrides(payload.model_profile_id))
        except KeyError as exc:
            raise ValueError("所选模型配置不存在，请重新选择") from exc
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
    logger.debug("Serving index page")
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    logger.debug("Health check requested")
    return {"status": "ok"}


@app.post("/api/instruments/search")
async def search_instruments(payload: InstrumentSearchRequest) -> dict:
    logger.debug(
        "Instrument search request: query=%r market=%s use_ai=%s",
        payload.query, payload.market, payload.use_ai,
    )
    try:
        result = await asyncio.to_thread(
            instrument_search_service.search,
            payload.query,
            payload.market,
            use_ai=payload.use_ai,
        )
        logger.debug(
            "Instrument search completed for %r: %d result(s)",
            payload.query, len(result.get("results", [])),
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.warning("Instrument directory unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="证券目录暂时不可用，请稍后重试") from exc


@app.get("/api/model-templates")
async def get_model_templates() -> dict:
    logger.debug("Model templates requested: %d template(s)", len(MODEL_TEMPLATES))
    return {"templates": MODEL_TEMPLATES}


@app.get("/api/model-profiles")
async def list_model_profiles() -> dict:
    logger.debug("Model profiles listed")
    return {"profiles": model_profile_service.list()}


@app.post("/api/model-profiles", status_code=201)
async def create_model_profile(payload: ModelProfilePayload) -> dict:
    logger.debug("Create model profile: name=%r base_url=%s", payload.name, payload.base_url)
    try:
        profile = model_profile_service.save(payload.model_dump())
        logger.info("Created model profile %r (id=%s)", payload.name, profile.get("id"))
        return {"profile": profile}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/model-profiles/{profile_id}")
async def update_model_profile(profile_id: str, payload: ModelProfilePayload) -> dict:
    logger.debug("Update model profile %s: name=%r", profile_id, payload.name)
    try:
        profile = model_profile_service.save(payload.model_dump(), profile_id)
        logger.info("Updated model profile %s (name=%r)", profile_id, payload.name)
        return {"profile": profile}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/model-profiles/{profile_id}", status_code=204)
async def delete_model_profile(profile_id: str) -> None:
    logger.debug("Delete model profile %s", profile_id)
    try:
        model_profile_service.delete(profile_id)
        logger.info("Deleted model profile %s", profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/model-profiles/{profile_id}/discover")
async def discover_models(profile_id: str) -> dict:
    logger.debug("Discover models for profile %s", profile_id)
    try:
        result = await asyncio.to_thread(model_profile_service.discover, profile_id)
        logger.info(
            "Discovered %d model(s) for profile %s",
            len(result.get("models", [])), profile_id,
        )
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.info("Model discovery failed for %s: %s", profile_id, exc)
        raise HTTPException(status_code=502, detail="无法读取模型列表，请检查 Endpoint、密钥和网络") from exc


@app.post("/api/model-profiles/{profile_id}/test")
async def test_model_profile(profile_id: str) -> dict:
    logger.debug("Test model profile %s", profile_id)
    try:
        result = await asyncio.to_thread(model_profile_service.test, profile_id)
        logger.info("Model test succeeded for profile %s", profile_id)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.info("Model test failed for %s: %s", profile_id, exc)
        raise HTTPException(status_code=502, detail="模型连接失败，请检查 Endpoint、模型名、密钥或账户余额") from exc


@app.post("/api/analyses", status_code=202)
async def create_analysis(payload: AnalysisRequest) -> dict[str, str]:
    logger.info(
        "Analysis queued: ticker=%s trade_date=%s asset_type=%s analysts=%s profile_id=%s",
        payload.ticker, payload.trade_date.isoformat(), payload.asset_type,
        payload.analysts, payload.model_profile_id,
    )
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
    logger.debug("Analysis status requested for %s", task_id)
    with _records_lock:
        record = _records.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="分析任务不存在或服务已重启")
    return record
