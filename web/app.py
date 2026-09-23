from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import threading
import time
import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field, field_validator

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from web.instrument_search import instrument_search_service
from web.metrics import (
    ANALYSIS_RECORDS_COUNT,
    ANALYSIS_TASK_DURATION_SECONDS,
    ANALYSIS_TASKS_RUNNING,
    ANALYSIS_TASKS_TOTAL,
    APP_START_TIME,
    APP_UPTIME_SECONDS,
)
from web.model_profiles import MODEL_TEMPLATES, model_profile_service
from web.news.api import router as news_router
from web.news.config import NewsSettings
from web.report_history import delete_report, get_report, list_reports

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
    model_profile_id: str = Field(min_length=1, max_length=64)

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

    @field_validator("model_profile_id")
    @classmethod
    def validate_model_profile_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("请先选择一个已添加的模型")
        return normalized


class AnalysisRecord(BaseModel):
    id: str
    ticker: str
    trade_date: str
    status: Literal["queued", "running", "completed", "failed"]
    phase: str
    created_at: str
    updated_at: str
    artifacts: list[dict] = Field(default_factory=list)
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
    quick_model: str = Field(default="", max_length=160)
    deep_model: str = Field(default="", max_length=160)
    api_key: str | None = Field(default=None, max_length=1000)
    discovered_models: list[str] | None = Field(default=None, max_length=300)


class ModelConnectionPayload(BaseModel):
    """尚未保存的模型连接信息，用于先发现模型、再完成配置。"""

    profile_id: str | None = Field(default=None, max_length=64)
    base_url: str = Field(min_length=8, max_length=300)
    api_key: str | None = Field(default=None, max_length=1000)
    model: str = Field(default="", max_length=160)


app = FastAPI(
    title="投研智报 · AI 股票投研与资讯日报",
    description="面向普通投资者的多智能体股票研究报告服务",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

# 使用 FastAPI 专用的 Prometheus instrumentation。handler 是 FastAPI 路由模板，
# 不会把 task_id、profile_id 等动态值作为高基数标签；健康检查与 metrics 自身不计入
# 业务请求统计，避免 Oncall 轮询污染业务指标。
instrumentator = Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    excluded_handlers=("/health", "/api/health", "/metrics"),
)
instrumentator.instrument(app)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(news_router)

_records: dict[str, AnalysisRecord] = {}
_records_lock = threading.Lock()
_analysis_gate = asyncio.Semaphore(1)

# 记录应用启动时间
APP_START_TIME.set(time.time())


@app.on_event("startup")
async def startup_metrics():
    """启动时初始化指标更新任务。"""
    async def update_uptime():
        while True:
            APP_UPTIME_SECONDS.set(time.time() - APP_START_TIME._value.get())
            ANALYSIS_RECORDS_COUNT.set(len(_records))
            await asyncio.sleep(10)
    asyncio.create_task(update_uptime())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_critical_dependencies() -> bool:
    """执行快速、无敏感信息的关键依赖检查。"""
    try:
        settings = NewsSettings.from_env()
        if not settings.enabled:
            return True
        # 数据库是本项目资讯 API 的关键依赖；只执行 SELECT 1，
        # 不访问外部 API，也不会把连接串、密钥或路径写入响应。
        if settings.database_url:
            import psycopg
            with psycopg.connect(settings.database_url, connect_timeout=2) as connection:
                connection.execute("SELECT 1").fetchone()
        else:
            with sqlite3.connect(str(settings.database_path), timeout=0.2) as connection:
                connection.execute("SELECT 1").fetchone()
    except Exception:  # noqa: BLE001 - health endpoint must fail closed
        return False
    return True


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


_PROGRESS_ARTIFACT_SPECS = (
    ("market_report", "技术分析", "analyst"),
    ("fundamentals_report", "基本面分析", "analyst"),
    ("news_report", "新闻分析", "analyst"),
    ("sentiment_report", "市场情绪", "analyst"),
    ("investment_debate_state", "多空研究", "research"),
    ("trader_investment_plan", "交易方案", "trader"),
    ("risk_debate_state", "风险评估", "risk"),
    ("final_trade_decision", "最终决策", "final"),
)


def _progress_value(state: dict, key: str) -> str:
    value = state.get(key)
    if isinstance(value, dict):
        for nested_key in (
            "current_response", "judge_decision", "history",
            "bull_history", "bear_history", "aggressive_history",
            "neutral_history", "conservative_history",
        ):
            nested_value = str(value.get(nested_key) or "").strip()
            if nested_value:
                return nested_value
        return ""
    return str(value or "").strip()


def _progress_phase(artifacts: list[dict]) -> str:
    artifact_ids = {item["id"] for item in artifacts}
    if "final_trade_decision" in artifact_ids:
        return "最终研报正在收束"
    if "risk_debate_state" in artifact_ids:
        return "风险团队正在评估"
    if "trader_investment_plan" in artifact_ids:
        return "交易团队正在整理方案"
    if "investment_debate_state" in artifact_ids:
        return "研究团队正在进行多空研究"
    if artifact_ids:
        return "分析师正在整理研究产物"
    return "研究团队正在收集市场资料"


def _build_progress_artifacts(state: dict, cache: dict[str, dict]) -> list[dict]:
    """将图状态压缩成可安全展示在 Web 轮询响应中的产物摘要。"""
    artifacts: list[dict] = []
    for key, title, kind in _PROGRESS_ARTIFACT_SPECS:
        value = _progress_value(state, key)
        if not value:
            continue
        cached = cache.get(key)
        if cached is None or cached["fingerprint"] != value:
            cache[key] = {"fingerprint": value, "updated_at": _utc_now()}
        preview = " ".join(value.split())
        if len(preview) > 260:
            preview = preview[:260].rstrip() + "…"
        artifacts.append({
            "id": key,
            "title": title,
            "kind": kind,
            "preview": preview,
            "chars": len(value),
            "updated_at": cache[key]["updated_at"],
        })
    return artifacts


def _run_analysis(payload: AnalysisRequest, progress_callback=None) -> dict:
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
        progress_callback=progress_callback,
    )
    final_state, decision = graph.propagate(
        payload.ticker,
        payload.trade_date.isoformat(),
        asset_type=payload.asset_type,
    )
    report_path = graph.save_reports(final_state, payload.ticker)
    result = _present_result(final_state, decision)
    result["report_id"] = report_path.parent.name
    return result


async def _execute(task_id: str, payload: AnalysisRequest) -> None:
    async with _analysis_gate:
        ANALYSIS_TASKS_RUNNING.set(1)
        ANALYSIS_TASKS_TOTAL.labels(status="running").inc()
        _update_record(task_id, status="running", phase="多智能体正在协作分析")
        start = time.time()
        logger.info(
            "分析任务开始：task_id=%s ticker=%s trade_date=%s asset_type=%s analysts=%s profile_id=%s",
            task_id, payload.ticker, payload.trade_date.isoformat(), payload.asset_type,
            payload.analysts, payload.model_profile_id,
        )
        try:
            progress_cache: dict[str, dict] = {}
            last_progress_signature = None
            last_progress_phase = ""

            def on_progress(state: dict) -> None:
                nonlocal last_progress_signature, last_progress_phase
                artifacts = _build_progress_artifacts(state, progress_cache)
                phase = _progress_phase(artifacts)
                signature = tuple(
                    (item["id"], item["preview"], item["chars"], item["updated_at"])
                    for item in artifacts
                )
                if signature == last_progress_signature and phase == last_progress_phase:
                    return
                last_progress_signature = signature
                last_progress_phase = phase
                _update_record(task_id, phase=phase, artifacts=artifacts)

            result = await asyncio.to_thread(_run_analysis, payload, on_progress)
        except Exception as exc:  # noqa: BLE001
            duration = time.time() - start
            logger.exception(
                "分析任务失败：task_id=%s ticker=%s trade_date=%s duration=%.1fs error=%s",
                task_id, payload.ticker, payload.trade_date.isoformat(), duration,
                type(exc).__name__,
            )
            ANALYSIS_TASKS_TOTAL.labels(status="failed").inc()
            ANALYSIS_TASK_DURATION_SECONDS.labels(
                ticker=payload.ticker, asset_type=payload.asset_type
            ).observe(time.time() - start)
            ANALYSIS_TASKS_RUNNING.set(0)
            _update_record(
                task_id,
                status="failed",
                phase="分析未完成",
                error=f"分析失败：{type(exc).__name__}。请检查模型密钥、网络和数据源配置。",
            )
            return
        ANALYSIS_TASKS_TOTAL.labels(status="completed").inc()
        ANALYSIS_TASK_DURATION_SECONDS.labels(
            ticker=payload.ticker, asset_type=payload.asset_type
        ).observe(time.time() - start)
        ANALYSIS_TASKS_RUNNING.set(0)
        _update_record(
            task_id,
            status="completed",
            phase="研报已生成",
            result=result,
        )
        logger.info(
            "分析任务完成：task_id=%s ticker=%s trade_date=%s decision=%s report_id=%s duration=%.1fs",
            task_id, payload.ticker, payload.trade_date.isoformat(), result.get("decision"),
            result.get("report_id"), time.time() - start,
        )


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    logger.debug("正在提供首页")
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
@app.get("/api/health", include_in_schema=False)
async def health() -> JSONResponse:
    if not _check_critical_dependencies():
        return JSONResponse(
            status_code=503,
            content={"ok": False, "status": "unhealthy"},
        )
    return JSONResponse(content={"ok": True, "status": "healthy"})


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
        logger.warning("标的目录不可用：%s", exc)
        raise HTTPException(status_code=503, detail="证券目录暂时不可用，请稍后重试") from exc


@app.get("/api/model-templates")
async def get_model_templates() -> dict:
    logger.debug("收到模型模板请求：%d 个模板", len(MODEL_TEMPLATES))
    return {"templates": MODEL_TEMPLATES}


@app.get("/api/reports")
async def reports(
    query: str = Query(default="", max_length=100),
    ticker: str = Query(default="", max_length=24),
    start_date: str = Query(default="", max_length=10),
    end_date: str = Query(default="", max_length=10),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    return await asyncio.to_thread(
        list_reports,
        query=query,
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@app.get("/api/reports/{report_id}")
async def report_detail(report_id: str) -> dict:
    result = await asyncio.to_thread(get_report, report_id)
    if result is None:
        raise HTTPException(status_code=404, detail="历史报告不存在或已损坏")
    return result


@app.delete("/api/reports/{report_id}")
async def delete_report_detail(report_id: str) -> dict[str, bool]:
    deleted = await asyncio.to_thread(delete_report, report_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="历史报告不存在或已损坏")
    logger.info("历史研报已删除：%s", report_id)
    return {"ok": True}


@app.get("/api/model-profiles")
async def list_model_profiles() -> dict:
    logger.debug("已列出模型配置")
    return {"profiles": model_profile_service.list()}


@app.post("/api/model-profiles", status_code=201)
async def create_model_profile(payload: ModelProfilePayload) -> dict:
    logger.debug("创建模型配置：名称=%r，base_url=%s", payload.name, payload.base_url)
    try:
        profile = model_profile_service.save(payload.model_dump())
        logger.info("已创建模型配置 %r（id=%s）", payload.name, profile.get("id"))
        return {"profile": profile}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/model-profiles/{profile_id}")
async def update_model_profile(profile_id: str, payload: ModelProfilePayload) -> dict:
    logger.debug("更新模型配置 %s：名称=%r", profile_id, payload.name)
    try:
        profile = model_profile_service.save(payload.model_dump(), profile_id)
        logger.info("已更新模型配置 %s（名称=%r）", profile_id, payload.name)
        return {"profile": profile}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/model-profiles/{profile_id}", status_code=204)
async def delete_model_profile(profile_id: str) -> None:
    logger.debug("删除模型配置 %s", profile_id)
    try:
        model_profile_service.delete(profile_id)
        logger.info("已删除模型配置 %s", profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/model-profiles/{profile_id}/discover")
async def discover_models(profile_id: str) -> dict:
    logger.debug("发现配置 %s 的模型", profile_id)
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
        logger.warning("发现配置 %s 的模型失败：%s", profile_id, exc)
        raise HTTPException(status_code=502, detail="无法读取模型列表，请检查 Endpoint、密钥和网络") from exc


@app.post("/api/model-profiles/{profile_id}/test")
async def test_model_profile(profile_id: str) -> dict:
    logger.debug("测试模型配置 %s", profile_id)
    try:
        result = await asyncio.to_thread(model_profile_service.test, profile_id)
        logger.info("模型配置测试成功：%s", profile_id)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.warning("模型配置测试失败：%s：%s", profile_id, exc)
        raise HTTPException(status_code=502, detail="模型连接失败，请检查 Endpoint、模型名、密钥或账户余额") from exc


def _model_request_error(exc: requests.RequestException, action: str) -> str:
    """把供应商 HTTP 错误转换为可操作、但不泄露凭据的提示。"""
    response = getattr(exc, "response", None)
    if response is None:
        return f"{action}失败：无法连接 Endpoint，请检查地址、网络或代理设置"
    status = response.status_code
    messages = {
        401: "API Key 无效或已过期",
        402: "账户余额不足或计费未开通",
        403: "API Key 没有访问该服务或模型的权限",
        404: "Endpoint 路径或模型名不存在",
        429: "请求过于频繁或额度已用尽",
    }
    message = messages.get(status, f"服务商返回 HTTP {status}")
    try:
        body = response.json()
        provider_message = body.get("error", {}).get("message") if isinstance(body, dict) else None
        if provider_message:
            message = f"{message}（{str(provider_message)[:240]}）"
    except (ValueError, AttributeError):
        pass
    return f"{action}失败：{message}"


@app.post("/api/model-connections/discover")
async def discover_model_connection(payload: ModelConnectionPayload) -> dict:
    """无需先保存配置，直接使用表单里的 Endpoint 和密钥读取模型。"""
    try:
        return await asyncio.to_thread(
            model_profile_service.discover_connection,
            payload.base_url,
            payload.api_key,
            payload.profile_id,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.warning("发现未保存连接的模型失败：%s", exc)
        raise HTTPException(status_code=502, detail=_model_request_error(exc, "发现模型")) from exc


@app.post("/api/model-connections/test")
async def test_model_connection(payload: ModelConnectionPayload) -> dict:
    """模型为空时验证 /models；选择模型后再验证对话能力。"""
    try:
        return await asyncio.to_thread(
            model_profile_service.test_connection,
            payload.base_url,
            payload.api_key,
            payload.model,
            payload.profile_id,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.warning("测试未保存的模型连接失败：%s", exc)
        raise HTTPException(status_code=502, detail=_model_request_error(exc, "测试连接")) from exc


@app.post("/api/analyses", status_code=202)
async def create_analysis(payload: AnalysisRequest) -> dict[str, str]:
    task_id = uuid.uuid4().hex
    logger.info(
        "分析任务已排队：task_id=%s ticker=%s trade_date=%s asset_type=%s analysts=%s profile_id=%s",
        task_id, payload.ticker, payload.trade_date.isoformat(), payload.asset_type,
        payload.analysts, payload.model_profile_id,
    )
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
    ANALYSIS_TASKS_TOTAL.labels(status="queued").inc()
    asyncio.create_task(_execute(task_id, payload))
    return {"id": task_id, "status": "queued"}


@app.get("/api/analyses/{task_id}", response_model=AnalysisRecord)
async def get_analysis(task_id: str) -> AnalysisRecord:
    logger.debug("收到 %s 的分析状态请求", task_id)
    with _records_lock:
        record = _records.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="分析任务不存在或服务已重启")
    return record


# 必须在所有业务路由注册后暴露，instrumentator 才能按 FastAPI 路由模板生成
# handler 标签；/health 和 /metrics 已在上方配置为不参与业务请求统计。
instrumentator.expose(app, include_in_schema=False)
