"""Praxic LLM -- Anthropic Claude API wrapper (lazy import)"""
from __future__ import annotations
import asyncio
from typing import AsyncIterator, Optional
import structlog
from ..config import settings
from .base import BaseLLM, LLMResponse
from .cache import usage_value

log = structlog.get_logger(__name__)
_DEFAULT_UNBOUNDED_MAX_TOKENS = 32768


class ClaudeLLM(BaseLLM):
    """Anthropic Claude API (lazy import to avoid error when not used)"""

    provider_name = "anthropic"
    supports_prompt_cache = True

    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        import anthropic  # lazy -- only imported when provider=anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key, timeout=120.0)
        self.default_model = default_model or settings.default_model

    async def call(self, messages, system=None, temperature=0.5, max_tokens=None, model=None, **kwargs):
        model = model or self.default_model
        log.debug("llm.call", model=model, n_messages=len(messages))
        # Anthropic requires a positive max_tokens value; use a generous provider
        # fallback while keeping the application default free of a short cap.
        max_tokens = max_tokens if max_tokens and max_tokens > 0 else _DEFAULT_UNBOUNDED_MAX_TOKENS
        params = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
        if system:
            if kwargs.pop("cache_prompt", True):
                params["system"] = [{
                    "type": "text", "text": system,
                    "cache_control": {"type": "ephemeral"},
                }]
            else:
                params["system"] = system
        if "reasoning_effort" in kwargs:
            tm = {"low": 1024, "medium": 4096, "high": 8192}
            budget = tm.get(kwargs.pop("reasoning_effort"), 4096)
            params["thinking"] = {"type": "enabled", "budget_tokens": budget}
            params["temperature"] = 1
        resp = await self._client.messages.create(**params)
        content = "".join(block.text for block in resp.content if hasattr(block, "text"))
        cache_read = usage_value(resp.usage, "cache_read_input_tokens")
        cache_create = usage_value(resp.usage, "cache_creation_input_tokens")
        result = LLMResponse(content=content, model=resp.model,
                             input_tokens=resp.usage.input_tokens,
                             output_tokens=resp.usage.output_tokens,
                             stop_reason=resp.stop_reason or "end_turn",
                             cache_read_tokens=cache_read,
                             cache_creation_tokens=cache_create,
                             cache_hit=cache_read > 0,
                             metadata={"provider": self.provider_name})
        self._record_cache_response(result)
        return result

    async def stream(self, messages, system=None, temperature=0.5, max_tokens=None, model=None, **kwargs):
        model = model or self.default_model
        max_tokens = max_tokens if max_tokens and max_tokens > 0 else _DEFAULT_UNBOUNDED_MAX_TOKENS
        params = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
        if system:
            if kwargs.pop("cache_prompt", True):
                params["system"] = [{
                    "type": "text", "text": system,
                    "cache_control": {"type": "ephemeral"},
                }]
            else:
                params["system"] = system
        async with self._client.messages.stream(**params) as stream:
            async for text in stream.text_stream:
                yield text


_default_llm: Optional[ClaudeLLM] = None


def get_default_llm() -> ClaudeLLM:
    """全局默认 ClaudeLLM（仅供其他模块回退使用）"""
    global _default_llm
    if _default_llm is None:
        _default_llm = ClaudeLLM()
    return _default_llm
