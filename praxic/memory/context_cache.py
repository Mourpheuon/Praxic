"""Application-level context compilation and cache accounting.

This cache stores compiled prompt blocks, not model hidden states.  That keeps
it portable across OpenAI-compatible providers while still avoiding repeated
assembly of unchanged session context.  Provider-specific prompt caching is a
separate capability exposed by the LLM adapters.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import RLock
from typing import Iterable

from ..llm.kv_cache import KVCacheBackend, KVCacheEntry, detect_kv_cache_backend


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        import tiktoken

        encoder = tiktoken.get_encoding("cl100k_base")
        return len(encoder.encode(text))
    except Exception:
        return max(1, (len(text) + 3) // 4)


def _truncate_to_token_budget(text: str, token_budget: int) -> tuple[str, int]:
    """Return the longest visible prefix whose estimate fits the budget."""
    if token_budget <= 0 or not text:
        return "", 0
    current_tokens = estimate_tokens(text)
    if current_tokens <= token_budget:
        return text, current_tokens

    marker = "\n[上下文预算截断]"
    suffix = marker if estimate_tokens(marker) < token_budget else ""
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(text[:mid] + suffix) <= token_budget:
            low = mid
        else:
            high = mid - 1
    truncated = text[:low] + suffix
    if not truncated:
        return "", 0
    return truncated, estimate_tokens(truncated)


@dataclass(frozen=True)
class ContextBlock:
    name: str
    content: str
    stable: bool = True

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass
class CacheMetrics:
    hits: int = 0
    misses: int = 0
    writes: int = 0
    invalidations: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    tokens_saved: int = 0
    assembly_tokens_reused: int = 0

    def snapshot(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "invalidations": self.invalidations,
            "input_tokens": self.input_tokens,
            "cached_tokens": self.cached_tokens,
            "tokens_saved": self.tokens_saved,
            "assembly_tokens_reused": self.assembly_tokens_reused,
            "token_savings_verified": False,
        }


@dataclass
class CompiledContext:
    content: str
    key: str
    block_hashes: dict[str, str] = field(default_factory=dict)
    token_count: int = 0
    cache_hit: bool = False
    kv_cache_hit: bool = False
    stable_prefix_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "token_count": self.token_count,
            "cache_hit": self.cache_hit,
            "kv_cache_hit": self.kv_cache_hit,
            "stable_prefix_tokens": self.stable_prefix_tokens,
            "block_hashes": dict(self.block_hashes),
        }


class ContextCache:
    """Small bounded cache with session/project/model/prompt isolation."""

    def __init__(self, max_entries: int = 256):
        self.max_entries = max(1, max_entries)
        self._entries: OrderedDict[str, CompiledContext] = OrderedDict()
        self._lock = RLock()
        self._metrics = CacheMetrics()

    @staticmethod
    def make_key(
        *,
        session_id: str,
        project_id: str,
        model: str,
        prompt_version: str,
        blocks: Iterable[ContextBlock],
        token_budget: int = 0,
    ) -> str:
        block_data = [{"name": b.name, "digest": b.digest, "stable": b.stable} for b in blocks]
        raw = json.dumps(
            {
                "session_id": session_id,
                "project_id": project_id,
                "model": model,
                "prompt_version": prompt_version,
                "token_budget": max(0, int(token_budget)),
                "blocks": block_data,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> CompiledContext | None:
        with self._lock:
            value = self._entries.get(key)
            if value is None:
                self._metrics.misses += 1
                return None
            self._entries.move_to_end(key)
            self._metrics.hits += 1
            self._metrics.cached_tokens += value.stable_prefix_tokens
            self._metrics.assembly_tokens_reused += value.stable_prefix_tokens
            return value

    def put(self, key: str, value: CompiledContext) -> CompiledContext:
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            self._metrics.writes += 1
            self._metrics.input_tokens += value.token_count
            return value

    def invalidate(self, *, session_id: str = "", project_id: str = "", reason: str = "") -> int:
        """Invalidate all entries whose key was created under a scope.

        Keys are opaque hashes, so callers use the compiler's scope index.  A
        blank scope clears the whole cache and is useful after a global config
        or prompt-version change.
        """
        with self._lock:
            count = len(self._entries) if not session_id and not project_id else 0
            if not session_id and not project_id:
                self._entries.clear()
            # Scoped invalidation is performed by ContextCompiler's key index.
            self._metrics.invalidations += count or (1 if reason else 0)
            return count

    def clear(self) -> None:
        self.invalidate(reason="clear")

    def invalidate_keys(self, keys: Iterable[str], reason: str = "") -> int:
        with self._lock:
            removed = 0
            for key in keys:
                if key in self._entries:
                    del self._entries[key]
                    removed += 1
            if removed or reason:
                self._metrics.invalidations += removed or 1
            return removed

    def stats(self) -> dict:
        with self._lock:
            snapshot = self._metrics.snapshot()
            snapshot["entries"] = len(self._entries)
            return snapshot


class ContextCompiler:
    def __init__(
        self,
        cache: ContextCache | None = None,
        prompt_version: str = "praxic-context-v1",
        kv_backend: KVCacheBackend | None = None,
    ):
        self.cache = cache or ContextCache()
        self.prompt_version = prompt_version
        self.kv_backend = kv_backend or detect_kv_cache_backend()
        self._key_scope: dict[str, tuple[str, str]] = {}
        self._lock = RLock()

    def compile(
        self,
        blocks: Iterable[ContextBlock],
        *,
        session_id: str = "",
        project_id: str = "",
        model: str = "",
        token_budget: int = 0,
    ) -> CompiledContext:
        block_list = [block for block in blocks if block.content]
        normalized_budget = max(0, int(token_budget))
        key = self.cache.make_key(
            session_id=session_id,
            project_id=project_id,
            model=model,
            prompt_version=self.prompt_version,
            blocks=block_list,
            token_budget=normalized_budget,
        )
        cached = self.cache.get(key)
        if cached is not None:
            return CompiledContext(**{**cached.__dict__, "cache_hit": True})

        prefix_entry = self.kv_backend.get(key, model=model)
        if prefix_entry is not None:
            compiled = CompiledContext(
                content=prefix_entry.prefix,
                key=key,
                block_hashes={block.name: block.digest for block in block_list},
                token_count=prefix_entry.token_count,
                cache_hit=True,
                kv_cache_hit=True,
                stable_prefix_tokens=prefix_entry.stable_prefix_tokens,
            )
            with self._lock:
                self._key_scope[key] = (session_id, project_id)
            self.cache.put(key, compiled)
            return compiled

        parts: list[str] = []
        stable_prefix = 0
        stable_prefix_open = True
        total_tokens = 0
        for block in block_list:
            rendered = block.content.strip()
            if not rendered:
                continue
            piece = rendered if rendered.startswith("## ") else f"## {block.name}\n{rendered}"
            piece_tokens = estimate_tokens(piece)
            truncated = False
            if normalized_budget and total_tokens + piece_tokens > normalized_budget:
                remaining = max(0, normalized_budget - total_tokens)
                if remaining <= 0:
                    break
                piece, piece_tokens = _truncate_to_token_budget(piece, remaining)
                if not piece:
                    break
                truncated = True
            parts.append(piece)
            total_tokens += piece_tokens
            if stable_prefix_open and block.stable:
                stable_prefix += piece_tokens
            else:
                stable_prefix_open = False
            if truncated:
                break
        compiled = CompiledContext(
            content="\n\n".join(parts),
            key=key,
            block_hashes={block.name: block.digest for block in block_list},
            token_count=total_tokens,
            cache_hit=False,
            kv_cache_hit=False,
            stable_prefix_tokens=stable_prefix,
        )
        with self._lock:
            self._key_scope[key] = (session_id, project_id)
        self.kv_backend.put(
            KVCacheEntry(
                key=key,
                model=model,
                prefix=compiled.content,
                token_count=compiled.token_count,
                stable_prefix_tokens=compiled.stable_prefix_tokens,
            )
        )
        return self.cache.put(key, compiled)

    def invalidate_scope(
        self, session_id: str = "", project_id: str = "", reason: str = "world_changed"
    ) -> int:
        with self._lock:
            keys = [
                key
                for key, scope in self._key_scope.items()
                if (not session_id or scope[0] == session_id)
                and (not project_id or scope[1] == project_id)
            ]
            for key in keys:
                self._key_scope.pop(key, None)
        if not keys:
            return 0
        removed = self.cache.invalidate_keys(keys, reason=reason)
        self.kv_backend.invalidate(keys)
        return removed

    def cache_report(self) -> dict:
        return {
            "context": self.cache.stats(),
            "kv_cache": self.kv_backend.stats(),
            "kv_capabilities": self.kv_backend.capabilities.to_dict(),
        }


GLOBAL_CONTEXT_CACHE = ContextCache()
GLOBAL_CONTEXT_COMPILER = ContextCompiler(GLOBAL_CONTEXT_CACHE)
