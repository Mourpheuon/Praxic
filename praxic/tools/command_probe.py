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

import shutil

import structlog

from .base import ActionKind, BaseTool, ToolResult, ToolStatus

log = structlog.get_logger(__name__)


class CommandProbeTool(BaseTool):
    """检查命令是否存在于 PATH（只读），返回完整路径或不存在"""

    name = "command_probe"
    category = "system"
    description = (
        "检查命令是否存在于 PATH（只读），返回完整路径或不存在；"
        "用于判断 lean/lake/where 等命令是否可用"
    )
    requires_network = False
    action_kind = ActionKind.OBSERVE
    is_concurrency_safe = True
    parameter_schema = {
        "command": {"type": "string", "description": "要探测的命令名，例如 lean"},
    }

    async def run(self, command: str = "") -> ToolResult:
        command = str(command or "")
        if not command:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error="command 不能为空",
                action_kind=self.action_kind,
                failure_class="tool_error",
            )
        if "/" in command or "\\" in command:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"command 含路径分隔符，必须是纯命令名：{command!r}",
                action_kind=self.action_kind,
                failure_class="tool_error",
            )
        if any(ch.isspace() for ch in command):
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"command 含空白字符，必须是纯命令名：{command!r}",
                action_kind=self.action_kind,
                failure_class="tool_error",
            )
        try:
            found = shutil.which(command)
        except Exception as exc:  # noqa: BLE001 - 探测失败按工具错误返回
            log.warning("command_probe.error", command=command, error=str(exc))
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"命令探测失败：{exc}",
                action_kind=self.action_kind,
                failure_class="tool_error",
            )
        if found:
            log.debug("command_probe.found", command=command, path=found)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"found: {found}",
                data={"found": True, "command": command, "path": found},
                action_kind=self.action_kind,
            )
        log.debug("command_probe.not_found", command=command)
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"not found: {command}（不在 PATH）",
            data={"found": False, "command": command},
            action_kind=self.action_kind,
        )
