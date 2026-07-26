"""
即物穷理 Praxic —— LLM 调用基类
定义统一的 LLM 接口，支持同步/异步调用
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"


class BaseLLM(ABC):
    """LLM 接口基类 —— 所有后端必须实现这个接口"""

    @abstractmethod
    async def call(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
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
        max_tokens: int = 4096,
        **kwargs,
    ) -> AsyncIterator[str]:
        """异步流式调用 LLM，逐块 yield 文本"""
        ...

    def build_user_message(self, content: str) -> dict:
        return {"role": "user", "content": content}

    def build_assistant_message(self, content: str) -> dict:
        return {"role": "assistant", "content": content}
