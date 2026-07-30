"""Portable local KV-cache capability and prefix reuse primitives.

The generic chat API used by Praxic does not expose model hidden states.  This
module therefore keeps the backend contract explicit: a backend may reuse
compiled text prefixes, while hidden-state reuse is advertised only when a
real local inference engine provides that capability.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from threading import RLock
from time import perf_counter
from typing import Any


@dataclass(frozen=True)
class KVCacheCapabilities:
    backend: str
    available: bool
    mode: str
    supports_hidden_states: bool = False
    supports_prefix_reuse: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "available": self.available,
            "mode": self.mode,
            "supports_hidden_states": self.supports_hidden_states,
            "supports_prefix_reuse": self.supports_prefix_reuse,
            "reason": self.reason,
        }


@dataclass
class KVCacheEntry:
    key: str
    model: str
    prefix: str
    token_count: int = 0
    stable_prefix_tokens: int = 0
    created_at: float = field(default_factory=perf_counter)


class KVCacheBackend(ABC):
    """Backend contract shared by local inference and portable fallback modes."""

    @property
    @abstractmethod
    def capabilities(self) -> KVCacheCapabilities: ...

    @abstractmethod
    def get(self, key: str, *, model: str = "") -> KVCacheEntry | None: ...

    @abstractmethod
    def put(self, entry: KVCacheEntry) -> None: ...

    @abstractmethod
    def invalidate(self, keys: list[str] | tuple[str, ...]) -> int: ...

    @abstractmethod
    def stats(self) -> dict: ...


class NullKVCacheBackend(KVCacheBackend):
    def __init__(self, reason: str = "未配置本地推理 KV cache backend"):
        self._capabilities = KVCacheCapabilities(
            backend="none",
            available=False,
            mode="disabled",
            reason=reason,
        )

    @property
    def capabilities(self) -> KVCacheCapabilities:
        return self._capabilities

    def get(self, key: str, *, model: str = "") -> KVCacheEntry | None:
        return None

    def put(self, entry: KVCacheEntry) -> None:
        return None

    def invalidate(self, keys: list[str] | tuple[str, ...]) -> int:
        return 0

    def stats(self) -> dict:
        return {"backend": "none", "hits": 0, "misses": 0, "writes": 0, "entries": 0}


class InMemoryPrefixKVCache(KVCacheBackend):
    """Portable in-process prefix cache; it does not store hidden tensors."""

    def __init__(self, max_entries: int = 256):
        self.max_entries = max(1, max_entries)
        self._entries: dict[str, KVCacheEntry] = {}
        self._order: list[str] = []
        self._lock = RLock()
        self._hits = 0
        self._misses = 0
        self._writes = 0
        self._invalidations = 0
        self._capabilities = KVCacheCapabilities(
            backend="memory_prefix",
            available=True,
            mode="text_prefix",
            supports_hidden_states=False,
            supports_prefix_reuse=True,
            reason="通用 API 不暴露隐藏状态，只复用已编译的稳定文本前缀",
        )

    @property
    def capabilities(self) -> KVCacheCapabilities:
        return self._capabilities

    def get(self, key: str, *, model: str = "") -> KVCacheEntry | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or (model and entry.model != model):
                self._misses += 1
                return None
            self._hits += 1
            if key in self._order:
                self._order.remove(key)
            self._order.append(key)
            return entry

    def put(self, entry: KVCacheEntry) -> None:
        with self._lock:
            self._entries[entry.key] = entry
            if entry.key in self._order:
                self._order.remove(entry.key)
            self._order.append(entry.key)
            while len(self._order) > self.max_entries:
                oldest = self._order.pop(0)
                self._entries.pop(oldest, None)
            self._writes += 1

    def invalidate(self, keys: list[str] | tuple[str, ...]) -> int:
        with self._lock:
            removed = 0
            for key in keys:
                if key in self._entries:
                    self._entries.pop(key, None)
                    if key in self._order:
                        self._order.remove(key)
                    removed += 1
            self._invalidations += removed
            return removed

    def stats(self) -> dict:
        with self._lock:
            return {
                "backend": self._capabilities.backend,
                "hits": self._hits,
                "misses": self._misses,
                "writes": self._writes,
                "invalidations": self._invalidations,
                "entries": len(self._entries),
            }


def detect_kv_cache_backend(
    preferred: str = "",
    *,
    max_entries: int = 256,
    local_engine: Any = None,
) -> KVCacheBackend:
    """Select a backend without importing heavyweight inference runtimes.

    A caller can pass a local engine exposing ``kv_cache_backend``.  Otherwise
    ``memory``/``prefix`` selects the portable fallback and ``none`` disables
    it.  The default remains the portable fallback because it gives useful
    accounting without claiming hidden-state reuse.
    """
    if local_engine is not None:
        candidate = getattr(local_engine, "kv_cache_backend", None)
        if isinstance(candidate, KVCacheBackend):
            return candidate
    name = (preferred or os.environ.get("PRAXIC_KV_CACHE_BACKEND", "memory")).strip().lower()
    if name in {"none", "disabled", "off"}:
        return NullKVCacheBackend()
    if name in {"memory", "prefix", "text_prefix", "auto"}:
        return InMemoryPrefixKVCache(max_entries=max_entries)
    return NullKVCacheBackend(reason=f"未知 KV cache backend：{preferred}")
