"""工具注册表兼容层 + 工具行服务。

- ``ToolRegistryService`` 包装现有 ``ToolRegistry`` 实例，注册/查询行为不变；
- ``ToolService`` 按行 id 构造工具实例并注册进 tool-registry，工具清单与
  ``CognitiveLoop`` 旧装配段逐一对应（不增不减）。
"""

from __future__ import annotations

from praxic.cordis import Service


class ToolRegistryService(Service):
    """tool-registry 服务：兼容层，包装现有 ToolRegistry。

    event_sink 由 CognitiveLoopService 装配时指向 loop 的事件转发，
    与旧路径 ``ToolRegistry(event_sink=self._on_registry_event)`` 等价。
    """

    def __init__(self, ctx, name=None, config=None):
        super().__init__(ctx, name, config)
        from praxic.tools.registry import ToolRegistry

        policy_svc = ctx.get("permission-policy")
        self.registry = ToolRegistry(policy=policy_svc.policy)


class ToolService(Service):
    """工具行服务：按行 id 构造工具并注册进 tool-registry。

    支持的行（与旧装配段一一对应）：python-exec、workspace-tools、shell、
    web-search、web-fetch、user-context、plugin-scan。
    """

    def __init__(self, ctx, name=None, config=None):
        super().__init__(ctx, name, config)
        registry_svc = ctx.get("tool-registry")
        self._registry = registry_svc.registry
        tool = self._build()
        if tool is not None:
            self._register_tool(tool)

    def _register_tool(self, tool) -> None:
        """注册工具；撞名（同名工具已注册）按 P2 策略抛错。"""
        existing = self._registry.get(tool.name)
        if existing is not None:
            from praxic.cordis import DuplicateServiceError

            raise DuplicateServiceError(
                f"工具 {tool.name!r} 重复注册（已有 {type(existing).__name__}，"
                f"当前行 {self.name!r}）"
            )
        self._registry.register(tool)

    def _build(self):
        rid = self.name
        from praxic.config import settings

        workspace_svc = self.ctx.get("workspace")
        ws = workspace_svc.workspace if workspace_svc else None
        ws_dir = str(ws.workspace) if ws else ""

        if rid == "python-exec":
            from praxic.tools.python_exec import PythonExecTool

            return PythonExecTool(workspace_dir=ws_dir)

        if rid == "workspace-tools":
            from praxic.tools.assembler import register_workspace_tools

            register_workspace_tools(self._registry, ws.workspace)
            return None

        if rid == "shell":
            from praxic.tools.shell import ShellTool

            return ShellTool(allowed_roots=(ws.workspace,))

        if rid == "web-search":
            from praxic.tools.web_search import WebSearchTool

            return WebSearchTool(
                api_key=settings.tavily_api_key,
                max_results=settings.web_search_max_results,
            )

        if rid == "web-fetch":
            if not (settings.web_search_enabled and settings.web_fetch_enabled):
                return None
            from praxic.tools.web_fetch import WebFetchTool

            return WebFetchTool()

        if rid == "user-context":
            from praxic.tools.user_context import ReadUserContextTool

            return ReadUserContextTool()

        if rid == "plugin-scan":
            from praxic.tools.assembler import register_plugins

            register_plugins(self._registry)
            return None

        raise ValueError(f"未知工具行 id: {rid!r}")