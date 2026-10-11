"""LLM provider abstraction layer."""

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class LLMUsage(BaseModel):
    """Usage metrics from LLM calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0


class LLMResponse(BaseModel):
    """Standardized LLM response."""

    text: str
    usage: LLMUsage
    model: str
    latency_ms: float
    finish_reason: Optional[str] = None


@runtime_checkable
class LLMProvider(Protocol):
    """Interface for LLM providers."""

    async def chat_completion(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        system_message: Optional[str] = None,
        structured_output: bool = False,
        structured_schema: Optional[BaseModel] = None,
    ) -> LLMResponse:
        """Get chat completion from LLM."""
        ...

    async def structured_completion(
        self,
        prompt: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
        max_tokens: int = 2048,
        system_message: Optional[str] = None,
    ) -> BaseModel:
        """Get structured completion with JSON schema validation."""
        ...


class LLMError(Exception):
    """Base exception for LLM-related errors."""

    def __init__(self, message: str, provider: str, model: str):
        self.message = message
        self.provider = provider
        self.model = model
        super().__init__(f"{provider}/{model}: {message}")


class LLMProviderError(LLMError):
    """Error from LLM provider (API errors, timeouts)."""

    pass


class LLMParseError(LLMError):
    """Error parsing LLM response."""

    pass


class LegacyOpenAIChatClient:
    """Compatibility wrapper around the LangChain OpenAI client used in the existing graph tests."""

    def __init__(self, model: Optional[str] = None, **kwargs: Any):
        self.model = model or kwargs.get("model") or "gpt-4o-mini"
        self.temperature = kwargs.get("temperature", 0.0)
        self.max_tokens = kwargs.get("max_tokens", 2048)
        self.api_key = kwargs.get("api_key")
        self.base_url = kwargs.get("base_url")
        self.client = None

        try:
            from langchain_openai import ChatOpenAI

            self.client = ChatOpenAI(
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                api_key=self.api_key,
                base_url=self.base_url,
            )
        except Exception:
            # Keep the wrapper usable in tests that patch ChatOpenAI and assign a fake client object.
            self.client = None

    async def chat_completion(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        system_message: Optional[str] = None,
        structured_output: bool = False,
        structured_schema: Optional[type[BaseModel]] = None,
    ) -> LLMResponse:
        if self.client is None:
            raise LLMProviderError("OpenAI client is not configured", "openai", self.model)

        text_prompt = prompt
        if system_message:
            text_prompt = f"{system_message}\n\n{text_prompt}"

        response = self.client.invoke(text_prompt)
        content = getattr(response, "content", str(response))
        usage = LLMUsage(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            model=self.model,
            cost_usd=0.0,
        )
        return LLMResponse(
            text=str(content),
            usage=usage,
            model=self.model,
            latency_ms=0.0,
        )

    async def structured_completion(
        self,
        prompt: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
        max_tokens: int = 2048,
        system_message: Optional[str] = None,
    ) -> BaseModel:
        response = await self.chat_completion(
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system_message=system_message,
            structured_output=True,
            structured_schema=schema,
        )
        try:
            payload = _extract_json_object(response.text)
            data = json.loads(payload)
            return schema.model_validate(data)
        except (TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            raise LLMParseError(f"Malformed JSON for schema {schema.__name__}: {exc}", "openai", self.model) from exc


class FakeLLMProvider:
    """Minimal fake provider used by tests that do not want a real provider."""

    def __init__(self, model: Optional[str] = None):
        self.model = model or "fake-model"

    async def chat_completion(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        system_message: Optional[str] = None,
        structured_output: bool = False,
        structured_schema: Optional[type[BaseModel]] = None,
    ) -> LLMResponse:
        payload = {"plan": [], "needs_schema": False, "ambiguity_flag": False, "clarifying_question": ""}
        return LLMResponse(
            text=json.dumps(payload),
            usage=LLMUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0, model=self.model, cost_usd=0.0),
            model=self.model,
            latency_ms=0.0,
        )

    async def structured_completion(
        self,
        prompt: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
        max_tokens: int = 2048,
        system_message: Optional[str] = None,
    ) -> BaseModel:
        value = {"plan": [], "needs_schema": False, "ambiguity_flag": False, "clarifying_question": ""}
        return schema.model_validate(value)


def _extract_json_object(text: str) -> str:
    """Strip markdown fences or extra prose and return the JSON payload."""
    if text is None:
        raise ValueError("No response content")

    cleaned = str(text).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)

    first_brace = max(cleaned.find("{"), cleaned.find("["))
    last_brace = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if first_brace != -1 and last_brace > first_brace:
        return cleaned[first_brace : last_brace + 1]

    return cleaned


def _should_retry_exception(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    message = str(exc).lower()
    if "429" in message or "rate limit" in message or "too many requests" in message:
        return True
    if "500" in message or "502" in message or "503" in message or "504" in message:
        return True
    return False


def get_llm_provider(
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
    *,
    node_name: Optional[str] = None,
) -> Any:
    """Create an LLM provider instance based on the configured provider."""
    from app.config import get_config

    config = get_config()
    provider = (provider_name or config.llm_provider or "openrouter").lower()
    target_model = model or config.get_model_for_node(node_name or "default")

    if provider == "fake":
        return FakeLLMProvider(model=target_model)
    if provider == "openrouter":
        from app.llm.openrouter import OpenRouterProvider

        return OpenRouterProvider(model=target_model)
    if provider == "openai":
        return LegacyOpenAIChatClient(model=target_model, api_key=config.openai_api_key)

    if provider == "anthropic":
        raise LLMProviderError(f"Provider '{provider}' is not implemented in this workspace", provider, target_model)

    if provider == "bedrock":
        raise LLMProviderError(f"Provider '{provider}' is not implemented in this workspace", provider, target_model)

    raise LLMProviderError(f"Unsupported LLM provider '{provider}'", provider, target_model)


__all__ = [
    "LLMProvider",
    "LLMResponse",
    "LLMUsage",
    "LLMError",
    "LLMProviderError",
    "LLMParseError",
    "LegacyOpenAIChatClient",
    "FakeLLMProvider",
    "get_llm_provider",
    "_extract_json_object",
    "_should_retry_exception",
]
