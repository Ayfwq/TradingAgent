from unittest.mock import Mock, patch

import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph
from web.model_profiles import ModelProfileService


def _payload(**overrides):
    payload = {
        "name": "DeepSeek research",
        "template": "deepseek",
        "base_url": "https://api.example.com/v1",
        "quick_model": "research-chat",
        "deep_model": "research-reasoner",
        "api_key": "secret-key",
    }
    payload.update(overrides)
    return payload


def test_profile_encrypts_key_and_produces_graph_overrides(tmp_path):
    service = ModelProfileService(tmp_path)
    public = service.save(_payload())

    stored = (tmp_path / "model_profiles.json").read_text(encoding="utf-8")
    assert "secret-key" not in stored
    assert public["has_api_key"] is True
    assert "api_key_encrypted" not in public

    overrides = service.graph_overrides(public["id"])
    assert overrides["llm_provider"] == "openai_compatible"
    assert overrides["backend_url"] == "https://api.example.com/v1"
    assert overrides["llm_api_key"] == "secret-key"


def test_profile_update_without_key_preserves_secret(tmp_path):
    service = ModelProfileService(tmp_path)
    created = service.save(_payload())
    updated = service.save(_payload(name="Updated", api_key=""), created["id"])

    assert updated["name"] == "Updated"
    assert service.graph_overrides(created["id"])["llm_api_key"] == "secret-key"


def test_profile_saves_discovered_models_from_unsaved_form(tmp_path):
    service = ModelProfileService(tmp_path)
    profile = service.save(_payload(discovered_models=["model-b", "model-a", "model-a"]))

    assert profile["discovered_models"] == ["model-a", "model-b"]


def test_discover_models_persists_provider_response(tmp_path):
    service = ModelProfileService(tmp_path)
    profile = service.save(_payload())
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": [{"id": "model-b"}, {"id": "model-a"}, {"id": "model-a"}]}

    with patch("web.model_profiles.requests.get", return_value=response) as request:
        result = service.discover(profile["id"])

    assert result["models"] == ["model-a", "model-b"]
    assert request.call_args.args[0] == "https://api.example.com/v1/models"
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer secret-key"
    assert service.list()[0]["discovered_models"] == ["model-a", "model-b"]


def test_unsaved_connection_can_discover_before_model_is_selected(tmp_path):
    service = ModelProfileService(tmp_path)
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": [{"id": "model-b"}, {"id": "model-a"}]}

    with patch("web.model_profiles.requests.get", return_value=response) as request:
        result = service.discover_connection("https://api.example.com/v1/", "new-secret")

    assert result == {"models": ["model-a", "model-b"]}
    assert request.call_args.args[0] == "https://api.example.com/v1/models"
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer new-secret"


def test_connection_without_model_uses_models_endpoint(tmp_path):
    service = ModelProfileService(tmp_path)
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": [{"id": "model-a"}]}

    with patch("web.model_profiles.requests.get", return_value=response):
        result = service.test_connection("https://api.example.com/v1", "secret-key")

    assert result["ok"] is True
    assert result["models"] == ["model-a"]


def test_unsaved_connection_reuses_saved_key_while_editing(tmp_path):
    service = ModelProfileService(tmp_path)
    profile = service.save(_payload())
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": []}

    with patch("web.model_profiles.requests.get", return_value=response) as request:
        service.discover_connection(profile["base_url"], "", profile["id"])

    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer secret-key"


def test_test_profile_calls_chat_completion(tmp_path):
    service = ModelProfileService(tmp_path)
    profile = service.save(_payload())
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"choices": [{"message": {"content": "OK"}}]}

    with patch("web.model_profiles.requests.post", return_value=response) as request:
        result = service.test(profile["id"])

    assert result == {"ok": True, "message": "模型连接正常", "model": "research-chat", "reply": "OK"}
    assert request.call_args.args[0] == "https://api.example.com/v1/chat/completions"
    assert request.call_args.kwargs["json"]["model"] == "research-chat"


def test_invalid_endpoint_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Endpoint URL"):
        ModelProfileService(tmp_path).save(_payload(base_url="not-a-url"))


def test_graph_forwards_profile_api_key():
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"llm_provider": "openai_compatible", "llm_api_key": "per-profile-key", "temperature": None, "llm_max_retries": None}
    assert graph._get_provider_kwargs()["api_key"] == "per-profile-key"
