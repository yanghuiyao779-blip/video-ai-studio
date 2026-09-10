from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.services.setting_store import LLMConfig

logger = logging.getLogger(__name__)


class LLMEmptyContentError(RuntimeError):
    """The provider accepted a request but did not produce a usable final answer."""


@dataclass
class LLMResult:
    content: str


class OpenAICompatibleLLM:
    def __init__(self, config: LLMConfig):
        self.config = config
        self.settings = get_settings()
        self.client = httpx.Client(timeout=self.settings.llm_timeout_seconds)

    def __enter__(self) -> "OpenAICompatibleLLM":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self.client.close()

    @property
    def endpoint(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/chat/completions"

    @property
    def is_deepseek(self) -> bool:
        return self.config.provider == "deepseek" or "api.deepseek.com" in self.config.base_url

    def complete(self, system: str, user: str) -> LLMResult:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        # Let the provider decide its generation budget. A local max_tokens cap
        # makes DeepSeek's reasoning and final answer compete for the same small
        # output allowance, which is especially harmful during long-video
        # map/reduce summarisation.
        if self.is_deepseek:
            # Explicitly request DeepSeek's reasoning mode for both direct and
            # OpenAI-compatible DeepSeek endpoints. DeepSeek ignores temperature
            # while reasoning is enabled, so it is deliberately omitted here.
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "high"
        else:
            payload["temperature"] = self.config.temperature
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        data = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.client.post(self.endpoint, json=payload, headers=headers)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        retry_after = response.headers.get("retry-after")
                        delay = float(retry_after) if retry_after and retry_after.isdigit() else float(2**attempt)
                        time.sleep(min(delay, 8.0))
                        continue
                response.raise_for_status()
                data = response.json()
                try:
                    choice = data["choices"][0]
                    message = choice["message"] or {}
                    content = message.get("content")
                except (KeyError, IndexError, TypeError) as exc:
                    logger.error("Unexpected LLM response shape from provider=%s", self.config.provider)
                    raise RuntimeError("Unexpected LLM response format") from exc
                if isinstance(content, str) and content.strip():
                    return LLMResult(content=content.strip())
                logger.warning(
                    "LLM returned empty final content (provider=%s model=%s finish_reason=%s reasoning_chars=%s attempt=%s)",
                    self.config.provider, self.config.model, choice.get("finish_reason"),
                    len(message.get("reasoning_content") or ""), attempt + 1,
                )
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise LLMEmptyContentError("LLM returned empty final content after retries")
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
        if data is None:
            raise RuntimeError("LLM request failed") from last_error
        raise RuntimeError("LLM request failed")

    def test(self) -> str:
        result = self.complete(
            "You are a connectivity test. Reply with exactly OK.",
            "Return OK.",
        )
        return result.content
