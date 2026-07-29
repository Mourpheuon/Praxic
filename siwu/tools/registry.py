"""
思悟 Agent —— 工具注册中心
管理所有可用工具的注册、查找和调用。
"""
from __future__ import annotations
from typing import Any
import structlog

from .base import BaseTool, ToolResult, ToolStatus

log = structlog.get_logger(__name__)


class ToolRegistry:
    """全局工具注册表。"""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """注册一个工具实例。"""
        self._tools[tool.name] = tool
        log.info("tool_registry.registered", name=tool.name, cls=tool.__class__.__name__)

    def get(self, name: str) -> BaseTool | None:
        """按名称查找工具。"""
        return self._tools.get(name)

    def get_names(self) -> list[str]:
        """返回所有已注册的工具名。"""
        return list(self._tools.keys())

    def call_sync(self, name: str, **params) -> ToolResult:
        """
        同步调用工具（内部用 asyncio.run 包裹）。
        当调用方本身不在 async 上下文时使用。
        """
        import asyncio
        return asyncio.run(self.call(name, **params))

    async def call(self, name: str, **params) -> ToolResult:
        """异步调用工具。"""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                status=ToolStatus.ERROR, content="",
                error=f"未知工具: {name}，可用工具: {', '.join(self._tools.keys())}",
            )
        try:
            return await tool.run(**params)
        except Exception as e:
            log.warning("tool_registry.call_error", tool=name, error=str(e))
            return ToolResult(
                status=ToolStatus.ERROR, content="",
                error=f"工具 {name} 调用失败: {e}",
            )

    def tool_descriptions(self) -> list[dict]:
        """返回所有工具的 JSON 描述列表，供 LLM 规划工具调用时参考。"""
        descs = []
        for name, tool in self._tools.items():
            desc = {"name": name, "description": getattr(tool, "description", "")}
            # 尝试获取参数类型信息（BaseTool 子类可通过 run 方法的签名暴露参数）
            import inspect
            sig = inspect.signature(tool.run)
            params = {}
            for pname, param in sig.parameters.items():
                if pname == "self" or pname == "kwargs":
                    continue
                ptype = "string"
                if param.annotation is not inspect.Parameter.empty:
                    ann = str(param.annotation)
                    if "int" in ann: ptype = "integer"
                    elif "float" in ann: ptype = "number"
                    elif "bool" in ann: ptype = "boolean"
                    elif "list" in ann: ptype = "array"
                    elif "dict" in ann: ptype = "object"
                default = None
                if param.default is not inspect.Parameter.empty:
                    default = param.default
                params[pname] = {"type": ptype, "default": None if default is inspect.Parameter.empty else default}
            desc["parameters"] = params
            descs.append(desc)
        return descs

    def format_for_prompt(self) -> str:
        """格式化为 LLM 可读的工具列表字符串。"""
        lines = ["## 可用工具\n"]
        for name, tool in self._tools.items():
            lines.append(f"### {name}")
            lines.append(f"{getattr(tool, 'description', '')}")
            import inspect
            sig = inspect.signature(tool.run)
            sig_params = [p for p in sig.parameters if p not in ("self", "kwargs")]
            if sig_params:
                lines.append("参数：")
                for pname in sig_params:
                    param = sig.parameters[pname]
                    default = ""
                    if param.default is not inspect.Parameter.empty:
                        default = f" (默认={param.default})"
                    lines.append(f"  - {pname}{default}")
            lines.append("")
        return "\n".join(lines)
