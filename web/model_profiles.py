"""Encrypted, server-side model endpoint profiles for the web application."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

MODEL_TEMPLATES = [
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1"},
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1"},
    {"id": "qwen-cn", "name": "通义千问（中国区）", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    {"id": "qwen", "name": "通义千问（国际区）", "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"},
    {"id": "glm-cn", "name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4/"},
    {"id": "kimi", "name": "Kimi / Moonshot", "base_url": "https://api.moonshot.ai/v1"},
    {"id": "minimax", "name": "MiniMax", "base_url": "https://api.minimax.io/v1"},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1"},
    {"id": "groq", "name": "Groq", "base_url": "https://api.groq.com/openai/v1"},
    {"id": "custom", "name": "自定义 / Ollama / vLLM", "base_url": ""},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _settings_dir() -> Path:
    configured = os.getenv("TRADINGAGENTS_MODEL_SETTINGS_DIR")
    if configured:
        return Path(configured)
    return Path.home() / ".tradingagents" / "settings"


def _normalise_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Endpoint URL 必须是完整的 http:// 或 https:// 地址")
    return value


class ModelProfileService:
    """Stores endpoint credentials encrypted at rest and performs safe API checks."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _settings_dir()
        self.path = self.root / "model_profiles.json"
        self.key_path = self.root / ".model_profiles.key"
        self._lock = threading.RLock()

    def _fernet(self) -> Fernet:
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())
            os.chmod(self.key_path, 0o600)
        return Fernet(self.key_path.read_bytes())

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError("模型配置文件无法读取，请检查服务器数据卷") from exc
        return data if isinstance(data, list) else []

    def _write(self, profiles: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)

    def _public(self, profile: dict[str, Any]) -> dict[str, Any]:
        return {
            key: profile.get(key)
            for key in (
                "id", "name", "template", "base_url", "quick_model", "deep_model",
                "discovered_models", "created_at", "updated_at",
            )
        } | {"has_api_key": bool(profile.get("api_key_encrypted"))}

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            profiles = [self._public(profile) for profile in self._read()]
        logger.debug("Listed %d model profile(s)", len(profiles))
        return profiles

    def _find(self, profile_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        profiles = self._read()
        for profile in profiles:
            if profile.get("id") == profile_id:
                return profiles, profile
        raise KeyError("未找到该模型配置")

    def _api_key(self, profile: dict[str, Any]) -> str | None:
        encrypted = profile.get("api_key_encrypted")
        if not encrypted:
            return None
        try:
            return self._fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise ValueError("模型密钥无法解密，请重新保存该配置") from exc

    def save(self, payload: dict[str, Any], profile_id: str | None = None) -> dict[str, Any]:
        logger.debug(
            "Save model profile: id=%s name=%r base_url=%s quick_model=%s",
            profile_id, payload.get("name"), payload.get("base_url"), payload.get("quick_model"),
        )
        name = str(payload.get("name", "")).strip()
        base_url = _normalise_base_url(str(payload.get("base_url", "")))
        quick_model = str(payload.get("quick_model", "")).strip()
        deep_model = str(payload.get("deep_model", "")).strip() or quick_model
        if not name or not quick_model:
            raise ValueError("请填写配置名称和默认模型")

        with self._lock:
            profiles = self._read()
            current = next((item for item in profiles if item.get("id") == profile_id), None)
            if profile_id and current is None:
                raise KeyError("未找到该模型配置")
            api_key = payload.get("api_key")
            encrypted_key = current.get("api_key_encrypted") if current else None
            if api_key is not None and str(api_key).strip():
                encrypted_key = self._fernet().encrypt(str(api_key).strip().encode("utf-8")).decode("utf-8")
            profile = {
                "id": profile_id or uuid.uuid4().hex,
                "name": name[:80],
                "template": str(payload.get("template", "custom"))[:40],
                "base_url": base_url,
                "quick_model": quick_model[:160],
                "deep_model": deep_model[:160],
                "api_key_encrypted": encrypted_key,
                "discovered_models": current.get("discovered_models", []) if current else [],
                "created_at": current.get("created_at", _now()) if current else _now(),
                "updated_at": _now(),
            }
            if current:
                profiles[profiles.index(current)] = profile
            else:
                profiles.append(profile)
            self._write(profiles)
            logger.info(
                "Saved model profile %s (name=%r)",
                profile["id"], profile["name"],
            )
            return self._public(profile)

    def delete(self, profile_id: str) -> None:
        logger.debug("Delete model profile %s", profile_id)
        with self._lock:
            profiles, _ = self._find(profile_id)
            self._write([item for item in profiles if item.get("id") != profile_id])
        logger.info("Deleted model profile %s", profile_id)

    @staticmethod
    def _headers(api_key: str | None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def discover(self, profile_id: str) -> dict[str, Any]:
        logger.debug("Discover models for profile %s", profile_id)
        with self._lock:
            profiles, profile = self._find(profile_id)
            api_key = self._api_key(profile)
        response = requests.get(f"{profile['base_url']}/models", headers=self._headers(api_key), timeout=15)
        response.raise_for_status()
        data = response.json().get("data", [])
        models = sorted({str(item.get("id", "")).strip() for item in data if isinstance(item, dict) and item.get("id")})
        with self._lock:
            profiles, profile = self._find(profile_id)
            profile["discovered_models"] = models[:300]
            profile["updated_at"] = _now()
            profiles[profiles.index(profile)] = profile
            self._write(profiles)
            logger.info("Discovered %d model(s) for profile %s", len(models), profile_id)
            return {"profile": self._public(profile), "models": models}

    def test(self, profile_id: str) -> dict[str, Any]:
        logger.debug("Test model profile %s", profile_id)
        with self._lock:
            _, profile = self._find(profile_id)
            api_key = self._api_key(profile)
        response = requests.post(
            f"{profile['base_url']}/chat/completions",
            headers={**self._headers(api_key), "Content-Type": "application/json"},
            json={"model": profile["quick_model"], "messages": [{"role": "user", "content": "Reply with OK."}], "max_tokens": 8, "temperature": 0},
            timeout=25,
        )
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices", [])
        content = ""
        if choices and isinstance(choices[0], dict):
            content = str((choices[0].get("message") or {}).get("content") or "")
        logger.info("Model test succeeded for profile %s (model=%s)", profile_id, profile["quick_model"])
        return {"ok": True, "message": "模型连接正常", "model": profile["quick_model"], "reply": content[:160]}

    def graph_overrides(self, profile_id: str) -> dict[str, str]:
        logger.debug("Build graph overrides for profile %s", profile_id)
        with self._lock:
            _, profile = self._find(profile_id)
            api_key = self._api_key(profile)
        overrides = {
            "llm_provider": "openai_compatible",
            "backend_url": profile["base_url"],
            "quick_think_llm": profile["quick_model"],
            "deep_think_llm": profile["deep_model"],
        }
        if api_key:
            overrides["llm_api_key"] = api_key
        return overrides


model_profile_service = ModelProfileService()
