"""A privacy-gated tool for reading the user's optional background text."""

from __future__ import annotations

from .base import ActionKind, BaseTool, ToolResult, ToolStatus


class ReadUserContextTool(BaseTool):
    """Return user-supplied background only after an explicit approval."""

    name = "read_user_context"
    description = "申请查看用户补充的背景文本；用户批准后才返回内容"
    action_kind = ActionKind.OBSERVE
    requires_authorization = True
    authorization_reason = "实践阶段请求查看你补充的背景文本"
    parameter_schema = {
        "reason": {
            "type": "string",
            "description": "说明为什么这段背景对当前实践检验有必要",
        },
    }

    async def run(
        self,
        reason: str = "",
        _user_context: str = "",
        **kwargs,
    ) -> ToolResult:
        context = str(_user_context or "").strip()
        if not context:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content="本轮没有可供查看的用户补充背景。",
                metadata={"context_available": False},
            )
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content="用户已授权查看的补充背景：\n" + context,
            metadata={"context_available": True, "purpose": "practice_context_review"},
        )
