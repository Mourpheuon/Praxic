"""cordis 插件注册表。

``Registry`` 负责按声明启动插件：校验 inject 依赖可用性（缺失则标记
失败、不拖垮整体）、导入 ``module:Class`` 或执行内联 ``apply``、把
产生的 disposable 挂进 Fiber。``detect_inject_cycle`` 在启动前对
整张依赖图做环检测，发现环即抛 ``InjectCycleError``。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import structlog

from .context import Context
from .errors import DuplicateServiceError, InjectCycleError
from .fiber import Fiber

log = structlog.get_logger(__name__)


def import_class(spec: str) -> type:
    """解析 ``module:Class`` 并导入类。

    与现有插件 manifest 的 ``module:function`` 约定同构。
    """
    if not spec or ":" not in spec:
        raise ValueError(f"无效的 module:Class 名: {spec!r}")
    module_name, _, class_name = spec.partition(":")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, class_name)
    except AttributeError as exc:
        raise ImportError(f"模块 {module_name} 中没有 {class_name!r}") from exc


@dataclass
class PluginDef:
    """一行组合声明对应的插件定义。

    ``name`` 为 ``module:Class``；``apply`` 为内联启动函数
    ``fn(ctx, plugin) -> Any``，二者至少其一。
    """

    id: str
    name: str | None = None
    config: dict[str, Any] | None = None
    inject: list[str] = field(default_factory=list)
    isolate: dict[str, bool] = field(default_factory=dict)
    apply: Callable[[Context, "PluginDef"], Any] | None = None

    @property
    def service_name(self) -> str:
        """服务标识 = 行 id。"""
        return self.id


class Registry:
    """组合加载用的插件注册表。"""

    def __init__(self, ctx: Context, fiber: Fiber | None = None) -> None:
        self.ctx = ctx
        self.fiber = fiber or Fiber(ctx)
        self._activated: list[str] = []
        self._failed: list[tuple[str, str]] = []

    @property
    def activated(self) -> list[str]:
        return list(self._activated)

    @property
    def failed(self) -> list[tuple[str, str]]:
        return list(self._failed)

    # ------------------------------------------------------------------
    # 激活
    # ------------------------------------------------------------------
    def activate(
        self,
        plugin: PluginDef,
        ctx: Context | None = None,
    ) -> bool:
        """启动一个插件到 ``ctx``（缺省为 registry 的 ctx）。

        依赖缺失或启动抛错时记录到 ``failed`` 并返回 False；
        成功返回 True，且产生的可调用返回值的清理函数挂进 fiber。
        """
        target = ctx or self.ctx
        for dep in plugin.inject:
            if not target.has(dep):
                self._failed.append((plugin.id, f"依赖服务 {dep!r} 不可用"))
                log.warning("cordis.plugin.dependency_missing", id=plugin.id, dep=dep)
                return False
        try:
            if plugin.apply is not None:
                result = plugin.apply(target, plugin)
            elif plugin.name:
                cls = import_class(plugin.name)
                result = cls(target, name=plugin.id, config=plugin.config)
            else:
                raise ValueError(f"插件 {plugin.id!r} 缺少 name 或 apply")
            if callable(result):
                self.fiber.register(result)
            self._activated.append(plugin.id)
            return True
        except DuplicateServiceError:
            # 撞名是组合级配置错误（P2 收紧）：不降级为坏行，直接抛出
            raise
        except Exception as exc:  # noqa: BLE001 - 坏行不拖垮整体
            self._failed.append((plugin.id, str(exc)))
            log.warning("cordis.plugin.activation_failed", id=plugin.id, error=str(exc))
            return False

    # ------------------------------------------------------------------
    # 依赖环检测
    # ------------------------------------------------------------------
    @staticmethod
    def detect_inject_cycle(rows: Sequence[Any]) -> None:
        """检测 inject 依赖环，发现即抛 ``InjectCycleError``。

        ``rows`` 为带 ``id`` 与 ``inject`` 属性的对象序列。
        """
        graph: dict[str, list[str]] = {
            row.id: list(getattr(row, "inject", None) or []) for row in rows
        }
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {node: WHITE for node in graph}
        stack: list[str] = []

        def visit(node: str) -> None:
            color[node] = GRAY
            stack.append(node)
            for dep in graph.get(node, ()):
                if dep not in graph:
                    continue  # 外部依赖，不在组合图内，不构成环
                if color[dep] == GRAY:
                    idx = stack.index(dep)
                    cycle = stack[idx:] + [dep]
                    raise InjectCycleError(
                        f"inject 依赖环: {' -> '.join(cycle)}"
                    )
                if color[dep] == WHITE:
                    visit(dep)
            stack.pop()
            color[node] = BLACK

        for node in graph:
            if color[node] == WHITE:
                visit(node)
