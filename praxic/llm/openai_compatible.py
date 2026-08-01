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

_UNSUPPORTED_PARAMETER_MARKERS = (
    "unsupported",
    "not support",
    "unknown parameter",
    "unrecognized parameter",
    "unexpected keyword",
    "unexpected argument",
    "extra inputs",
    "not permitted",
    "invalid parameter",
)


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

    @staticmethod
    def _unsupported_reasoning_controls(exc: Exception, controls: set[str]) -> set[str]:
        """Return only controls explicitly implicated by an unsupported-param error."""
        details = " ".join(
            str(value)
            for value in (exc, getattr(exc, "body", None), getattr(exc, "code", None))
            if value
        ).lower()
        if not any(marker in details for marker in _UNSUPPORTED_PARAMETER_MARKERS):
            return set()

        named = {name for name in controls if name in details}
        if named:
            return named
        if controls and ("reasoning" in details or "thinking" in details):
            return set(controls)
        return set()

    @staticmethod
    def _remove_reasoning_controls(params: dict, controls: set[str]) -> dict:
        retry_params = dict(params)
        if "reasoning_effort" in controls:
            retry_params.pop("reasoning_effort", None)
        if "enable_reasoning" in controls:
            extra_body = dict(retry_params.get("extra_body") or {})
            extra_body.pop("enable_reasoning", None)
            if extra_body:
                retry_params["extra_body"] = extra_body
            else:
                retry_params.pop("extra_body", None)
        return retry_params

    async def _create_with_reasoning_fallback(
        self, params: dict, controls: set[str]
    ):
        try:
            return await self._client.chat.completions.create(**params)
        except Exception as exc:
            unsupported = self._unsupported_reasoning_controls(exc, controls)
            if not unsupported:
                raise
            log.warning(
                "openai_compatible.reasoning_controls_degraded",
                controls=sorted(unsupported),
                error=str(exc)[:200],
            )
            retry_params = self._remove_reasoning_controls(params, unsupported)
            return await self._client.chat.completions.create(**retry_params)

    # ── call ──────────────────────────────────────────────────────
    async def call(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: Optional[int] = None,
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
            "temperature": temperature,
        }
        if max_tokens is not None and max_tokens > 0:
            params["max_tokens"] = max_tokens
        reasoning_controls: set[str] = set()
        if "reasoning_effort" in kwargs:
            params["reasoning_effort"] = kwargs.pop("reasoning_effort")
            reasoning_controls.add("reasoning_effort")
        if "enable_reasoning" in kwargs:
            extra_body = dict(params.get("extra_body") or {})
            extra_body["enable_reasoning"] = kwargs.pop("enable_reasoning")
            params["extra_body"] = extra_body
            reasoning_controls.add("enable_reasoning")
        if kwargs.pop("use_provider_prompt_cache", False):
            cache_key = kwargs.pop("cache_key", None)
            if cache_key:
                params["prompt_cache_key"] = cache_key
            retention = kwargs.pop("prompt_cache_retention", None)
            if retention:
                params["prompt_cache_retention"] = retention

        response = await self._create_with_reasoning_fallback(params, reasoning_controls)
        choice = response.choices[0]
        content = choice.message.content or ""

        # Some providers (e.g. DeepSeek) return reasoning in a separate field.
        # Reasoning is a thinking-chain draft; it is never valid as evaluable
        # output (a thought trace fed to a JSON parser is a source of empty/half
        # plans). Keep it for logging only and let empty content ("") propagate
        # so the caller can retry or degrade instead of parsing a draft.
        reasoning = getattr(choice.message, "reasoning_content", None)
        if reasoning:
            log.debug("openai_compatible.reasoning_tokens", len=len(reasoning))
        if not content:
            log.warning(
                "openai_compatible.empty_content",
                model=model,
                finish_reason=choice.finish_reason,
                reasoning_len=len(reasoning) if reasoning else 0,
            )

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
        max_tokens: Optional[int] = None,
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
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None and max_tokens > 0:
            params["max_tokens"] = max_tokens
        reasoning_controls: set[str] = set()
        if "reasoning_effort" in kwargs:
            params["reasoning_effort"] = kwargs.pop("reasoning_effort")
            reasoning_controls.add("reasoning_effort")
        if "enable_reasoning" in kwargs:
            extra_body = dict(params.get("extra_body") or {})
            extra_body["enable_reasoning"] = kwargs.pop("enable_reasoning")
            params["extra_body"] = extra_body
            reasoning_controls.add("enable_reasoning")

        stream = await self._create_with_reasoning_fallback(params, reasoning_controls)
        async with stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
