"""Provider-neutral prompt-cache policy and accounting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromptCacheStats:
    requests: int = 0
    cache_reads: int = 0
    cache_writes: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "requests": self.requests,
            "cache_reads": self.cache_reads,
            "cache_writes": self.cache_writes,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
        }


def usage_value(usage, *names: str) -> int:
    """Read provider-specific usage fields without coupling the adapters."""
    if usage is None:
        return 0
    for name in names:
        value = getattr(usage, name, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(name)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return 0
