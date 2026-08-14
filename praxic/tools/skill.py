"""
Praxic Agent —— 技能按需加载工具（E1）

渐进式披露的第二步：技能管理器只在上下文注入摘要（名称+一句话描述）；
模型需要完整指令时，显式调用 skill(name) 按名加载 SKILL.md 正文。

配合 SkillManager.get_phase_skill_catalog()：技能注入只含摘要，
完整指令经工具命中后才进入会话。
"""

from __future__ import annotations

from typing import Optional

from .base import ActionKind, BaseTool, ToolResult, ToolStatus


class SkillLoadTool(BaseTool):
    """按名加载技能完整指令（只读）"""

    name = "skill"
    category = "knowledge"
    description = (
        "按名称加载指定技能的完整操作指令。用法：skill(name=\"技能名\")。"
        "技能清单里的每个技能都有摘要，只有当你要真正使用某个技能的方法时，"
        "才调用本工具取回完整内容，避免无谓的上下文开销（少存多指路）。"
    )
    requires_network = False
    action_kind = ActionKind.OBSERVE
    is_concurrency_safe = True
    parameter_schema = {"name": {"type": "string", "description": "要加载的技能名"}}

    def __init__(self, manager=None):
        self.manager = manager

    async def run(self, name: str = "") -> ToolResult:
        name = str(name or "").strip()
        if not name:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error="skill 工具需要 name 参数（技能名）",
                failure_class="tool_error",
            )
        if self.manager is None:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"技能 {name} 未接入技能管理器，无完整指令可加载。",
                data={"loaded": False, "name": name},
            )
        try:
            body = self.manager.load_skill_body_for_tool(name)
        except Exception as exc:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"技能加载失败: {exc}",
                failure_class="tool_error",
            )
        if body is None or not str(body).strip():
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"未找到技能: {name}（可用技能见技能清单摘要）",
                failure_class="tool_error",
            )
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=str(body),
            data={"loaded": True, "name": name},
            summary=f"已加载技能 {name} 完整指令（{len(str(body))} 字符）",
        )
