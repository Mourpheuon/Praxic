"""
Praxic Agent —— 插件工具加载器（档 3：非核心/第三方工具）

用户/第三方添加的工具以插件目录形式存在，每个插件一个目录，内含
manifest.yaml 声明元数据 + 执行函数（可 import 的 Python 模块）。

manifest.yaml 契约：
```yaml
name: my_tool            # 工具名（唯一）
category: data           # file/data/network/system/code/knowledge/user/misc
description: 工具描述
action_kind: observe     # observe | compute | change | external
group: ""                # 可选：同质组（渐进式披露）
sandbox_safe: false      # 可选：是否声明为沙箱安全（外部代码默认不信任）
requires_authorization: false  # 可选
requires_network: false  # 可选
run: my_plugin:run       # 执行函数：module:function（async def run(**kwargs) -> str|dict）
```

执行函数签名：`async def run(**kwargs)`，返回 str 或 dict（序列化为 ToolResult）。
外部代码默认 sandbox_safe=False（不自动信任沙箱），除非 manifest 显式声明。
"""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import Any, Optional

import structlog
import yaml

from .base import ActionKind, BaseTool, ToolResult, ToolStatus

log = structlog.get_logger(__name__)

VALID_ACTION_KINDS = {"observe", "compute", "change", "external"}
VALID_CATEGORIES = {"file", "data", "network", "system", "code", "knowledge", "user", "misc"}


class DeclaredTool(BaseTool):
    """由 manifest 声明 + 执行函数包装成的工具。"""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        category: str,
        action_kind: ActionKind,
        run_fn,
        group: str = "",
        sandbox_safe: bool = False,
        requires_authorization: bool = False,
        requires_network: bool = False,
        source_dir: str = "",
    ):
        self.name = name
        self.description = description
        self.category = category
        self.group = group
        self.action_kind = action_kind
        self.sandbox_safe = sandbox_safe
        self.requires_authorization = requires_authorization
        self.requires_network = requires_network
        self._run_fn = run_fn
        self.source_dir = source_dir
        # 参数 schema 从函数签名推断
        sig = inspect.signature(run_fn)
        self.parameter_schema = {}
        for pname, param in sig.parameters.items():
            if pname in ("self", "kwargs"):
                continue
            ptype = "string"
            if param.annotation is not inspect.Parameter.empty:
                ann = str(param.annotation)
                if "int" in ann:
                    ptype = "integer"
                elif "float" in ann:
                    ptype = "number"
                elif "bool" in ann:
                    ptype = "boolean"
                elif "list" in ann or "dict" in ann:
                    ptype = "object"
            self.parameter_schema[pname] = {"type": ptype}

    async def run(self, **kwargs) -> ToolResult:
        try:
            result = await self._run_fn(**kwargs)
            if isinstance(result, ToolResult):
                return result
            if isinstance(result, dict):
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=str(result.get("content", "")),
                    data=result,
                )
            return ToolResult(status=ToolStatus.SUCCESS, content=str(result))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"插件执行失败：{e}")


class PluginScanner:
    """扫描插件目录，按 manifest.yaml 加载插件工具。"""

    def __init__(self, plugins_dir: str | Path):
        self.plugins_dir = Path(plugins_dir)

    def scan(self) -> list[DeclaredTool]:
        """扫描目录下的插件，返回可注册的工具列表。"""
        if not self.plugins_dir.exists():
            return []
        tools: list[DeclaredTool] = []
        for manifest_path in self.plugins_dir.rglob("manifest.yaml"):
            try:
                tool = self._load_manifest(manifest_path)
                if tool is not None:
                    tools.append(tool)
            except Exception as exc:
                log.warning("plugin.load_failed", manifest=str(manifest_path), error=str(exc))
        return tools

    def _load_manifest(self, manifest_path: Path) -> Optional[DeclaredTool]:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("manifest 缺少 name")
        description = str(data.get("description", "")).strip()
        category = str(data.get("category", "misc"))
        if category not in VALID_CATEGORIES:
            raise ValueError(f"非法 category：{category}")
        action_kind_raw = str(data.get("action_kind", "observe"))
        if action_kind_raw not in VALID_ACTION_KINDS:
            raise ValueError(f"非法 action_kind：{action_kind_raw}")
        run_ref = str(data.get("run", "")).strip()
        if not run_ref or ":" not in run_ref:
            raise ValueError("manifest 缺少 run 引用（module:function）")
        module_name, func_name = run_ref.split(":", 1)
        # 插件执行模块从插件目录加载：manifest 所在目录与插件根目录都加进 sys.path，
        # 兼容“模块与 manifest 同目录”和“模块在 plugins 根”两种布局。
        plugin_root = str(manifest_path.parent)
        plugins_base = str(manifest_path.parent.parent)
        for candidate in (plugin_root, plugins_base):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
        module = importlib.import_module(module_name)
        run_fn = getattr(module, func_name, None)
        if run_fn is None or not callable(run_fn):
            raise ValueError(f"run 函数不存在：{run_ref}")

        tool = DeclaredTool(
            name=name,
            description=description,
            category=category,
            action_kind=ActionKind(action_kind_raw),
            run_fn=run_fn,
            group=str(data.get("group", "")),
            sandbox_safe=bool(data.get("sandbox_safe", False)),
            requires_authorization=bool(data.get("requires_authorization", False)),
            requires_network=bool(data.get("requires_network", False)),
            source_dir=str(manifest_path.parent),
        )
        log.info("plugin.loaded", name=name, category=category, source=str(manifest_path.parent))
        return tool


def load_plugins(registry, plugins_dir: str | Path) -> int:
    """扫描并注册插件到 registry，返回注册数量。"""
    scanner = PluginScanner(plugins_dir)
    tools = scanner.scan()
    for tool in tools:
        registry.register(tool)
    if tools:
        log.info("plugin.registered", count=len(tools), dir=str(plugins_dir))
    return len(tools)
