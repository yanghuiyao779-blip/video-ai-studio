from types import SimpleNamespace

import app.services.llm as llm_module
from app.services.llm import OpenAICompatibleLLM
from app.services.setting_store import LLMConfig


class _Response:
    status_code = 200
    headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "summary"}, "finish_reason": "stop"}]}


class _Client:
    last_payload: dict | None = None

    def __init__(self, **_: object) -> None:
        pass

    def post(self, _: str, *, json: dict, headers: dict) -> _Response:
        self.last_payload = json
        return _Response()

    def close(self) -> None:
        return None


def _client_for(monkeypatch) -> _Client:
    monkeypatch.setattr(
        llm_module,
        "get_settings",
        lambda: SimpleNamespace(llm_timeout_seconds=1),
    )
    monkeypatch.setattr(llm_module.httpx, "Client", _Client)
    return _Client()


def test_deepseek_enables_reasoning_without_a_local_output_cap(monkeypatch):
    _client_for(monkeypatch)
    client = OpenAICompatibleLLM(
        LLMConfig(
            provider="deepseek",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            api_key="test-key",
            temperature=0.2,
            custom_prompt=None,
        )
    )

    assert client.complete("system", "user").content == "summary"
    payload = client.client.last_payload
    assert payload is not None
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"
    assert "max_tokens" not in payload
    assert "temperature" not in payload


def test_non_deepseek_keeps_temperature_without_a_local_output_cap(monkeypatch):
    _client_for(monkeypatch)
    client = OpenAICompatibleLLM(
        LLMConfig(
            provider="custom",
            base_url="https://example.com/v1",
            model="test-model",
            api_key="test-key",
            temperature=0.4,
            custom_prompt=None,
        )
    )

    assert client.complete("system", "user").content == "summary"
    payload = client.client.last_payload
    assert payload is not None
    assert payload["temperature"] == 0.4
    assert "thinking" not in payload
    assert "max_tokens" not in payload
