"""Praxic —— 命令存在性探测工具（只读）

模型想判断"某命令是否存在于 PATH"（如 lean/lake/where）时使用。
python_exec 禁止 import os/shutil（安全检查黑名单），shell_exec 禁止管道
重定向，两者都无法干净地完成纯 PATH 探测。本工具用 shutil.which 只读查询
PATH，无副作用、不产生子进程，OBSERVE 类自动放行。

- found：返回完整路径
- not found：返回未命中（status 仍为 SUCCESS，探测本身成功了）
- 非法命令名（空、含路径分隔符 / 或 \\、含空白）：ERROR
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess

import structlog

from .base import ActionKind, BaseTool, ToolResult, ToolStatus

log = structlog.get_logger(__name__)


class CommandProbeTool(BaseTool):
    """检查命令是否存在于 PATH（只读），兼容单命令并支持批量/版本探测。

    ``command`` 是兼容旧调用的单命令参数；``commands`` 支持批量探测，
    ``with_version`` 会以 --version/-V 安全读取版本（5 秒上限）。
    """

    name = "command_probe"
    category = "system"
    description = (
        "检查命令是否存在于 PATH（只读），支持批量探测与可选版本读取；"
        "用于判断 lean/lake/python 等命令是否可用"
    )
    requires_network = False
    action_kind = ActionKind.OBSERVE
    is_concurrency_safe = True
    parameter_schema = {
        "command": {"type": "string", "default": "", "description": "单个命令名（兼容旧调用），例如 lean"},
        "commands": {"type": "array", "default": [], "description": "批量命令名，例如 lean、lake、python"},
        "with_version": {"type": "boolean", "default": False, "description": "是否读取 --version/-V（每项最多 5 秒）"},
    }

    _VERSION_FLAGS = ("--version", "-V", "version")
    _TIMEOUT_SECONDS = 5.0

    @staticmethod
    def _validate(command: str) -> str | None:
        if not command:
            return "command 不能为空"
        if "/" in command or "\\" in command:
            return f"command 含路径分隔符，必须是纯命令名：{command!r}"
        if any(ch.isspace() for ch in command):
            return f"command 含空白字符，必须是纯命令名：{command!r}"
        return None

    def _probe_version(self, path: str) -> str | None:
        for flag in self._VERSION_FLAGS:
            try:
                result = subprocess.run(
                    [path, flag], capture_output=True, timeout=self._TIMEOUT_SECONDS,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                text = ((result.stdout or b"") + (result.stderr or b"")).decode("utf-8", errors="replace").strip()
                if text:
                    return text.splitlines()[0][:200]
            except Exception:  # noqa: BLE001 - 版本不可读不影响存在性结论
                continue
        return None

    async def run(self, command: str = "", commands=None, with_version: bool = False) -> ToolResult:
        legacy_single = not commands
        # 不 strip：旧契约要求前导/尾随空白也算非法命令名，避免模型把复合命令悄悄洗白。
        requested = [str(command or "")] if legacy_single else [str(x) for x in commands]
        if not requested:
            return ToolResult(status=ToolStatus.ERROR, content="", error="command 或 commands 不能为空", action_kind=self.action_kind, failure_class="tool_error")

        results = {}
        for name in requested:
            invalid = self._validate(name)
            if invalid:
                return ToolResult(status=ToolStatus.ERROR, content="", error=invalid, action_kind=self.action_kind, failure_class="tool_error")
            try:
                found = shutil.which(name)
            except Exception as exc:  # noqa: BLE001
                log.warning("command_probe.error", command=name, error=str(exc))
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"命令探测失败：{exc}", action_kind=self.action_kind, failure_class="tool_error")
            version = await asyncio.to_thread(self._probe_version, found) if found and with_version else None
            results[name] = {"found": bool(found), "command": name, "path": found or None, "version": version}

        if legacy_single:
            entry = results[requested[0]]
            if entry["found"]:
                suffix = f"，版本 {entry["version"]}" if entry["version"] else ""
                content = f"found: {entry["path"]}{suffix}"
            else:
                content = f"not found: {requested[0]}（不在 PATH）"
            return ToolResult(status=ToolStatus.SUCCESS, content=content, data=entry, action_kind=self.action_kind)

        lines = []
        for name, entry in results.items():
            if entry["found"]:
                suffix = f"，版本 {entry["version"]}" if entry["version"] else ""
                lines.append(f"✓ {name}：{entry["path"]}{suffix}")
            else:
                lines.append(f"✗ {name}：未找到")
        return ToolResult(status=ToolStatus.SUCCESS, content="\n".join(lines), data=results, action_kind=self.action_kind)
