"""Praxic LLM -- Generic OpenAI-compatible API provider.

Use this for any API that speaks the OpenAI chat-completions protocol:
DeepSeek, OpenAI, Ollama, vLLM, LiteLM, any proxy or gateway.

Usage in config.toml:

    [llm]
    provider = "openai_compatible"
    base_url = "https://api.deepseek.com"   # or http://localhost:11434/v1 for Ollama
    api_key  = ""                            # or set PRAXIC_LLM_API_KEY / OPENAI_API_KEY env var
    model    = "deepseek-v4-pro"
"""
from __future__ import annotations

from typing import AsyncIterator, Optional

import structlog

from .base import BaseLLM, LLMResponse
from .cache import usage_value

log = structlog.get_logger(__name__)


class OpenAICompatibleLLM(BaseLLM):
    """Generic provider for any OpenAI-compatible chat-completions endpoint.

    Works with DeepSeek, OpenAI, Ollama, vLLM, LiteLLM, and any
    proxy/gateway that speaks the /v1/chat/completions protocol.
    """

    provider_name = "openai_compatible"
    # OpenAI-compatible gateways do not share one prompt-cache contract.
    # The adapter exposes opt-in forwarding and otherwise falls back cleanly.
    supports_prompt_cache = False

    def __init__(self, base_url: str, api_key: str, default_model: str):
        from openai import AsyncOpenAI

        self.default_model = default_model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=300.0, max_retries=2)

    # ── call ──────────────────────────────────────────────────────
    async def call(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        model: Optional[str] = None,
        **kwargs,
    ) -> LLMResponse:
        model = model or self.default_model
        log.debug("openai_compatible.call", model=model, n_messages=len(messages))

        full_messages: list[dict] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        params: dict = {
            "model": model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if kwargs.pop("use_provider_prompt_cache", False):
            cache_key = kwargs.pop("cache_key", None)
            if cache_key:
                params["prompt_cache_key"] = cache_key
            retention = kwargs.pop("prompt_cache_retention", None)
            if retention:
                params["prompt_cache_retention"] = retention

        response = await self._client.chat.completions.create(**params)
        choice = response.choices[0]
        content = choice.message.content or ""

        # Some providers (e.g. DeepSeek) return reasoning in a separate field.
        # Harmless no-op for providers that don't — getattr returns None.
        reasoning = getattr(choice.message, "reasoning_content", None)
        if reasoning:
            log.debug("openai_compatible.reasoning_tokens", len=len(reasoning))
        if not content and reasoning:
            content = reasoning

        usage = response.usage
        cache_read = usage_value(getattr(usage, "prompt_tokens_details", None), "cached_tokens")
        response_result = LLMResponse(
            content=content,
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            stop_reason=choice.finish_reason or "stop",
            cache_read_tokens=cache_read,
            cache_hit=cache_read > 0,
            metadata={"provider": self.provider_name},
        )
        self._record_cache_response(response_result)
        return response_result

    # ── stream ────────────────────────────────────────────────────
    async def stream(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        model: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        model = model or self.default_model

        full_messages: list[dict] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        params: dict = {
            "model": model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        async with await self._client.chat.completions.create(**params) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
