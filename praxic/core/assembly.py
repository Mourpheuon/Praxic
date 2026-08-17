"""装配层：CognitiveLoop 的“装配什么”单点维护处。

两条装配路径：
1. ``assemble_loop_runtime`` —— 旧构造路径（v0.1.8 行为不变）：
   ``CognitiveLoop()`` 内部调用，policy + ToolRegistry + 工具注册。
2. ``build_loop_from_composition`` —— 组合路径：加载 ``praxic/agent.yml``，
   由组合声明驱动装配，供 P2 会话 realm 接入。

六阶段认知方法论（阶段编排逻辑与六个阶段模块）不在此层，留在
``CognitiveLoop``；这里只决定“装哪些服务、怎么配”。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog
from pydantic import BaseModel

from ..cordis import CompositionError, Context, Service, load_composition
from ..config import settings
from .cognitive_loop import CognitiveLoop

log = structlog.get_logger(__name__)

_PRESET_DIR = Path(__file__).resolve().parent.parent  # praxic/
_PRESETS = {
    "default": _PRESET_DIR / "agent.yml",
}


def preset_path(preset_name: str = "default") -> Path:
    """返回组合文件路径。"""
    try:
        return _PRESETS[preset_name]
    except KeyError as exc:
        raise ValueError(f"未知组合预设: {preset_name!r}（可选: {list(_PRESETS)}）") from exc


# ----------------------------------------------------------------------
# 路径 1：旧构造路径（行为不变）
# ----------------------------------------------------------------------
def assemble_loop_runtime(loop: CognitiveLoop) -> None:
    """旧路径装配：policy + ToolRegistry + 工具注册。

    与 v0.1.8 的 ``CognitiveLoop.__init__`` 装配段逐行等价，只读
    ``loop`` 上由 ``_init_core`` 建立的状态（workspace / _web_enabled /
    _llm_factory / _on_registry_event）。
    """
    from ..core.autonomy import PermissionMode
    from ..tools.permissions import PermissionPolicy
    from ..tools.registry import ToolRegistry

    policy = PermissionPolicy(
        permission_mode=settings.permission_mode,
        allowed_roots=(loop.workspace.workspace,) if loop.workspace else (),
        allow_network=loop._web_enabled,
    )
    if settings.permission_mode == PermissionMode.AUTO_REVIEW:
        # 自动审核模式：为越界/外部操作挂上 LLM 语义审核器。
        from ..core.reviewer import build_reviewer

        policy.reviewer = build_reviewer(loop._llm_factory("practice", tag="reviewer"))
    loop._registry = ToolRegistry(
        policy=policy,
        event_sink=loop._on_registry_event,
    )
    try:
        from ..tools.python_exec import PythonExecTool

        loop._registry.register(
            PythonExecTool(
                workspace_dir=str(loop.workspace.workspace) if loop.workspace else ""
            )
        )
    except Exception:  # noqa: BLE001 - 与旧行为一致：python-exec 缺失不致命
        pass
    if loop.workspace:
        from ..tools.assembler import register_workspace_tools
        from ..tools.shell import ShellTool

        register_workspace_tools(loop._registry, loop.workspace.workspace)
        loop._registry.register(ShellTool(allowed_roots=(loop.workspace.workspace,)))
    from ..tools.web_search import WebSearchTool

    loop._registry.register(
        WebSearchTool(
            api_key=settings.tavily_api_key,
            max_results=settings.web_search_max_results,
        )
    )
    if loop._web_enabled and settings.web_fetch_enabled:
        from ..tools.web_fetch import WebFetchTool

        loop._registry.register(WebFetchTool())
    from ..tools.user_context import ReadUserContextTool

    loop._registry.register(ReadUserContextTool())
    # 插件（档 3）：用户/第三方工具，从 data_dir/plugins 自动加载。
    from ..tools.assembler import register_plugins

    register_plugins(loop._registry)


# ----------------------------------------------------------------------
# 路径 2：组合路径（agent.yml 驱动）
# ----------------------------------------------------------------------
class CognitiveLoopService(Service):
    """cognitive-loop 行：从组合 ctx 装配 CognitiveLoop。

    复用 ``_init_core``（核心状态），工具注册表改用组合装配的
    ``tool-registry`` 服务；构造签名与阶段逻辑零改动。
    """

    class Config(BaseModel):
        conversation_id: str = ""
        project_id: str = ""

    def __init__(self, ctx, name=None, config=None):
        super().__init__(ctx, name, config)
        llm_svc = ctx.get("llm")
        loop = CognitiveLoop.__new__(CognitiveLoop)
        loop._init_core(
            llm=llm_svc.get(),
            web_search_enabled=None,
            conversation_id=self.config.conversation_id,
            review_strategy="",
            project_id=self.config.project_id,
        )
        registry_svc = ctx.get("tool-registry")
        loop._registry = registry_svc.registry
        loop._registry.event_sink = loop._on_registry_event
        self.loop = loop


def build_loop_from_composition(
    root_ctx: Context,
    preset_name: str = "default",
) -> CognitiveLoop:
    """从组合文件构建 CognitiveLoop。

    ``root_ctx`` 为组合挂载的根 context（P2 阶段传入 session realm）。
    组合装配失败的行会被跳过（记录于 ``LoadResult.failed``）；核心服务
    ``cognitive-loop`` 缺失视为组合级错误。
    """
    result = load_composition(preset_path(preset_name), root_ctx)
    if not root_ctx.has("cognitive-loop"):
        failures = "; ".join(f"{rid}: {err}" for rid, err in result.failed[:5])
        raise CompositionError(
            "组合装配失败：缺少 cognitive-loop 核心服务"
            + (f"（已跳过行: {failures}）" if failures else "")
        )
    return root_ctx.get("cognitive-loop").loop
