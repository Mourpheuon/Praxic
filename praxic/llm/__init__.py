"""Praxic LLM factory."""
from __future__ import annotations

import json
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


def _config_phase_model(phase_name: str) -> str | None:
    """Read the config.toml [ui].phase_models JSON blob defensively."""
    raw = settings.ui_phase_models
    if not raw:
        return None

    try:
        phase_models = raw if isinstance(raw, dict) else json.loads(raw)
        if not isinstance(phase_models, dict):
            raise TypeError("phase_models must decode to an object")
    except (TypeError, ValueError) as exc:
        log.warning("llm.phase_models_config_invalid", error=str(exc))
        return None

    model = phase_models.get(phase_name)
    return model.strip() if isinstance(model, str) and model.strip() else None


def get_phase_llm(phase_name):
    cfg = settings.phase(phase_name)
    # config.toml 是初始默认值；运行中的 UI 设置拥有更高优先级。
    model = _config_phase_model(phase_name) or cfg.model or None
    try:
        path = settings.data_dir / "ui-settings.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise TypeError("ui-settings.json must contain an object")
            pm = data.get("phase_models", {})
            ui_model = pm.get(phase_name) if isinstance(pm, dict) else None
            if isinstance(ui_model, str) and ui_model.strip():
                model = ui_model.strip()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        log.warning("llm.ui_settings_read_failed", error=str(exc))
    return get_llm(model=model)


__all__ = ["get_llm", "get_phase_llm", "BaseLLM"]
