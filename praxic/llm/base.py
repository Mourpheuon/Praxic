"""
即物穷理 Praxic —— LLM 调用基类
定义统一的 LLM 接口，支持同步/异步调用
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from .cache import PromptCacheStats


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_hit: bool = False
    metadata: dict = field(default_factory=dict)


class BaseLLM(ABC):
    """LLM 接口基类 —— 所有后端必须实现这个接口"""

    @abstractmethod
    async def call(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        """异步调用 LLM，返回完整响应"""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        """异步流式调用 LLM，逐块 yield 文本"""
        if False:
            yield ""
        raise NotImplementedError

    def build_user_message(self, content: str) -> dict:
        return {"role": "user", "content": content}

    def build_assistant_message(self, content: str) -> dict:
        return {"role": "assistant", "content": content}

    provider_name: str = "unknown"
    supports_prompt_cache: bool = False

    def _record_cache_response(self, response: LLMResponse) -> None:
        stats = getattr(self, "_prompt_cache_stats", None)
        if stats is None:
            stats = PromptCacheStats()
            self._prompt_cache_stats = stats
        stats.requests += 1
        stats.cache_read_tokens += response.cache_read_tokens
        stats.cache_creation_tokens += response.cache_creation_tokens
        if response.cache_read_tokens or response.cache_hit:
            stats.cache_reads += 1
        if response.cache_creation_tokens:
            stats.cache_writes += 1

    def cache_capabilities(self) -> dict:
        return {
            "provider": self.provider_name,
            "supports_prompt_cache": self.supports_prompt_cache,
            "kv_cache": self.kv_cache_capabilities(),
            "stats": getattr(self, "_prompt_cache_stats", PromptCacheStats()).to_dict(),
        }

    def cache_stats(self) -> dict:
        return self.cache_capabilities()["stats"]

    def kv_cache_capabilities(self) -> dict:
        """Describe hidden-state KV support separately from prompt caching."""
        return {
            "backend": "provider_api",
            "available": False,
            "supports_hidden_states": False,
            "supports_prefix_reuse": self.supports_prompt_cache,
            "reason": "通用供应商接口没有跨请求 past_key_values 契约",
        }
