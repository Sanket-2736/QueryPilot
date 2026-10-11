"""OpenRouter provider implementation using the OpenAI-compatible API."""

import asyncio
import json
import logging
import time
from typing import Any, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import get_config
from app.llm import LLMError, LLMParseError, LLMProviderError, LLMResponse, LLMUsage, _extract_json_object, _should_retry_exception

logger = logging.getLogger(__name__)


class OpenRouterProvider:
    """OpenRouter-backed chat provider using the OpenAI-compatible python SDK."""

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        config = get_config()
        self.provider_name = "openrouter"
        self.model = model or config.get_model_for_node("default")
        self.api_key = api_key or config.openrouter_api_key
        self.base_url = "https://openrouter.ai/api/v1"
        self.timeout_seconds = config.llm_timeout_seconds
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=config.llm_timeout_seconds,
        )

    async def chat_completion(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        system_message: Optional[str] = None,
        structured_output: bool = False,
        structured_schema: Optional[type[BaseModel]] = None,
    ) -> LLMResponse:
        config = get_config()
        chosen_model = config.get_model_for_node("default")
        request_model = self.model or chosen_model

        messages: list[dict[str, str]] = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})

        extra_headers = {}
        if config.openrouter_http_referer:
            extra_headers["HTTP-Referer"] = config.openrouter_http_referer
        if config.openrouter_x_title:
            extra_headers["X-Title"] = config.openrouter_x_title

        request_kwargs: dict[str, Any] = {
            "model": request_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra_headers": extra_headers,
        }

        if structured_output and structured_schema is not None:
            request_kwargs["response_format"] = {"type": "json_object"}

        fallback_models = config.llm_fallback_models
        if fallback_models:
            request_kwargs["models"] = list(fallback_models)

        attempt = 0
        last_exc: Optional[Exception] = None
        while attempt < 3:
            attempt += 1
            start = time.perf_counter()
            try:
                response = await self.client.chat.completions.create(**request_kwargs)
                usage = getattr(response, "usage", None)
                completion = response.choices[0].message.content or ""
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                total_tokens = prompt_tokens + completion_tokens
                model_name = getattr(response, "model", request_model) or request_model
                cost_usd = 0.0
                usage_data = getattr(response, "usage", None)
                if usage_data is not None:
                    prompt_t = getattr(usage_data, "prompt_tokens", 0) or 0
                    comp_t = getattr(usage_data, "completion_tokens", 0) or 0
                    total_t = getattr(usage_data, "total_tokens", 0) or 0
                    if total_t > 0 and (prompt_t or comp_t):
                        cost_usd = float((prompt_t + comp_t) / 1000000.0) * 0.0
                    else:
                        cost_usd = 0.0
                latency_ms = (time.perf_counter() - start) * 1000
                return LLMResponse(
                    text=str(completion),
                    usage=LLMUsage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        model=model_name,
                        cost_usd=cost_usd,
                    ),
                    model=model_name,
                    latency_ms=latency_ms,
                    finish_reason=getattr(response.choices[0].finish_reason, "value", None) if getattr(response, "choices", None) else None,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not _should_retry_exception(exc) or attempt >= 3:
                    raise LLMProviderError(f"OpenRouter request failed: {exc}", self.provider_name, request_model) from exc
                await asyncio.sleep(2 ** (attempt - 1))

        if last_exc is not None:
            raise LLMProviderError(f"OpenRouter request failed: {last_exc}", self.provider_name, request_model)
        raise LLMProviderError("OpenRouter request failed", self.provider_name, request_model)

    async def structured_completion(
        self,
        prompt: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
        max_tokens: int = 2048,
        system_message: Optional[str] = None,
    ) -> BaseModel:
        last_error: Optional[Exception] = None
        for attempt in range(2):
            try:
                response = await self.chat_completion(
                    prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_message=system_message,
                    structured_output=True,
                    structured_schema=schema,
                )
                json_text = _extract_json_object(response.text)
                payload = json.loads(json_text)
                return schema.model_validate(payload)
            except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
                last_error = exc
                if attempt == 1:
                    raise LLMParseError(f"Failed to parse JSON response for {schema.__name__}: {exc}", self.provider_name, self.model) from exc
                continue

        if last_error is not None:
            raise LLMParseError(f"Failed to parse JSON response for {schema.__name__}: {last_error}", self.provider_name, self.model)
        raise LLMParseError(f"Failed to parse JSON response for {schema.__name__}", self.provider_name, self.model)
