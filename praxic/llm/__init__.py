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


def get_phase_llm(phase_name):
    """返回认知循环各阶段使用的 LLM。

    深度体系改造后全部阶段统一使用同一模型（settings.default_model），
    不再按阶段路由、不再读 ui_phase_models / ui-settings.json。参数保留以兼容
    外部调用。settings.ui_phase_models 字段仍保留在配置里但不再被消费。
    """
    del phase_name  # unused：全阶段同一模型
    return get_llm()


__all__ = ["get_llm", "get_phase_llm", "BaseLLM"]
