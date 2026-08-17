"""Praxic LLM factory."""
from __future__ import annotations

from functools import lru_cache

import structlog

from ..config import settings
from .base import BaseLLM

_PROVIDER_ALIASES = {"deepseek": "openai_compatible", "openai": "openai_compatible"}
log = structlog.get_logger(__name__)


@lru_cache(maxsize=8)
def get_llm(provider=None, model=None):
    p = (provider or settings.llm_provider).lower()
    p = _PROVIDER_ALIASES.get(p, p)
    if p == "openai_compatible":
        from .openai_compatible import OpenAICompatibleLLM

        return OpenAICompatibleLLM(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            default_model=model or settings.default_model,
        )
    if p == "anthropic":
        from .claude import ClaudeLLM

        return ClaudeLLM(
            api_key=settings.anthropic_api_key or None,
            default_model=model or settings.default_model,
        )
    raise ValueError(f"Unknown provider: {p!r}")


__all__ = ["get_llm", "BaseLLM"]
