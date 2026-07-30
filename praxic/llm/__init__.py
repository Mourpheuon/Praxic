"""Praxic LLM factory."""
from __future__ import annotations
from functools import lru_cache
from typing import Optional
from ..config import settings
from .base import BaseLLM

_PROVIDER_ALIASES = {"deepseek": "openai_compatible", "openai": "openai_compatible"}

@lru_cache(maxsize=8)
def get_llm(provider=None, model=None):
    p = (provider or settings.llm_provider).lower()
    p = _PROVIDER_ALIASES.get(p, p)
    if p == "openai_compatible":
        from .openai_compatible import OpenAICompatibleLLM
        return OpenAICompatibleLLM(base_url=settings.llm_base_url, api_key=settings.llm_api_key, default_model=model or settings.default_model)
    if p == "anthropic":
        from .claude import ClaudeLLM
        return ClaudeLLM(api_key=settings.anthropic_api_key or None, default_model=model or settings.default_model)
    raise ValueError(f"Unknown provider: {p!r}")

def get_phase_llm(phase_name):
    cfg = settings.phase(phase_name)
    model = cfg.model or None
    # 智能路由：检查 UI 设置中是否有针对此阶段的模型覆盖
    try:
        import json
        from ..config import settings as _s
        path = _s.data_dir / "ui-settings.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            pm = data.get("phase_models", {})
            if phase_name in pm and pm[phase_name]:
                model = pm[phase_name]
    except Exception:
        pass
    return get_llm(model=model)

__all__ = ["get_llm", "get_phase_llm", "BaseLLM"]
