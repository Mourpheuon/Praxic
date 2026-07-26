"""
即物穷理 Praxic —— 工具基类
定义所有工具的统一接口
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR   = "error"
    PARTIAL = "partial"


@dataclass
class ToolResult:
    status: ToolStatus
    content: str           # 主要结果文本（供 LLM 消费）
    data: Any = None       # 结构化数据（可选）
    error: str = ""
    source: str = ""       # 来源 URL 或路径
    metadata: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status != ToolStatus.ERROR

    def __str__(self) -> str:
        if not self.ok:
            return f"[ERROR] {self.error}"
        return self.content


class BaseTool(ABC):
    """工具基类 —— 所有工具必须实现这个接口"""

    name: str = "base_tool"
    description: str = "基础工具"
    requires_network: bool = False

    @abstractmethod
    async def run(self, **kwargs) -> ToolResult:
        """执行工具，返回 ToolResult"""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name})"
