"""Siwu LLM -- Anthropic Claude API wrapper (lazy import)"""
from __future__ import annotations
import asyncio
from typing import AsyncIterator, Optional
import structlog
from ..config import settings
from .base import BaseLLM, LLMResponse

log = structlog.get_logger(__name__)


class ClaudeLLM(BaseLLM):
    """Anthropic Claude API (lazy import to avoid error when not used)"""

    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        import anthropic  # lazy -- only imported when provider=anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key, timeout=120.0)
        self.default_model = default_model or settings.default_model

    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, model=None, **kwargs):
        model = model or self.default_model
        log.debug("llm.call", model=model, n_messages=len(messages))
        params = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
        if system:
            params["system"] = system
        if "reasoning_effort" in kwargs:
            tm = {"low": 1024, "medium": 4096, "high": 8192}
            budget = tm.get(kwargs.pop("reasoning_effort"), 4096)
            params["thinking"] = {"type": "enabled", "budget_tokens": budget}
            params["temperature"] = 1
        resp = await self._client.messages.create(**params)
        content = "".join(block.text for block in resp.content if hasattr(block, "text"))
        return LLMResponse(content=content, model=resp.model,
                           input_tokens=resp.usage.input_tokens,
                           output_tokens=resp.usage.output_tokens,
                           stop_reason=resp.stop_reason or "end_turn")

    async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, model=None, **kwargs):
        model = model or self.default_model
        params = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
        if system:
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
