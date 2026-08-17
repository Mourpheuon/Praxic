"""cordis 上下文：原型链式依赖容器。

Context 是服务注册、解析与事件传播的载体，对应 cordis 的 Context：

- ``extend()`` 建子作用域，子可见父，父不可见子；
- ``isolate(name, label)`` 为某服务名开隔离域（realm），realm 内的
  同名服务互不遮蔽、撞名单例抛错；
- ``get()`` 沿 parent 链解析，隔离墙内只认本 realm 注册；
- ``intercept(name, config)`` 沿链浅合并服务配置（根在前、子覆盖父）；
- ``on/emit`` 事件沿链自当前节点向根传播。
"""

from __future__ import annotations

from typing import Any, Callable

from .errors import DuplicateServiceError, UnknownServiceError
from .events import Disposable


class Context:
    """依赖容器节点。"""

    __slots__ = (
        "parent",
        "label",
        "_owned",
        "_isolated",
        "_intercepts",
        "_listeners",
    )

    def __init__(self, parent: Context | None = None, label: str = "") -> None:
        self.parent = parent
        self.label = label
        self._owned: dict[str, Any] = {}
        self._isolated: set[str] = set()
        self._intercepts: dict[str, dict[str, Any]] = {}
        self._listeners: dict[str, list[Callable[[Any], None]]] = {}

    # ------------------------------------------------------------------
    # 作用域
    # ------------------------------------------------------------------
    def extend(self, label: str = "") -> Context:
        """建子作用域。子可见父的注册，父不可见子。"""
        return Context(parent=self, label=label)

    def isolate(self, name: str, label: str = "") -> Context:
        """为 ``name`` 开隔离域，返回新的 realm context。

        realm 内 ``provide``/``get`` 该名字时只认 realm 自己的注册；
        同 realm 内同名第二次注册抛 ``DuplicateServiceError``。
        """
        realm = self.extend(label=label or name)
        realm._isolated.add(name)
        return realm

    # ------------------------------------------------------------------
    # 注册与解析
    # ------------------------------------------------------------------
    def provide(self, service: Any) -> None:
        """注册一个服务实例（Service 构造时自动调用）。

        查找挂载点：沿链找到第一个隔离了该名字的节点，挂到那里；
        无隔离墙则挂到当前节点。任何节点上已存在同名注册即抛错。
        """
        name = service.name
        node: Context | None = self
        while node is not None:
            if name in node._owned:
                owner = node.label or "root"
                raise DuplicateServiceError(
                    f"服务 {name!r} 在 '{owner}' 中已注册（单例语义）"
                )
            if name in node._isolated:
                node._owned[name] = service
                return
            node = node.parent
        self._owned[name] = service

    def get(self, name: str) -> Any:
        """按名解析服务，沿 parent 链向上。

        遇到隔离墙时只认本 realm 的注册，未注册即抛错（不穿透父）。
        """
        node: Context | None = self
        while node is not None:
            if name in node._isolated:
                if name in node._owned:
                    return node._owned[name]
                raise UnknownServiceError(
                    f"服务 {name!r} 在 realm '{node.label}' 中隔离但未注册"
                )
            if name in node._owned:
                return node._owned[name]
            node = node.parent
        raise UnknownServiceError(f"服务 {name!r} 未注册")

    def has(self, name: str) -> bool:
        """服务是否可解析（不抛错版本）。"""
        try:
            self.get(name)
            return True
        except UnknownServiceError:
            return False

    # ------------------------------------------------------------------
    # 配置拦截
    # ------------------------------------------------------------------
    def intercept(self, name: str, config: dict) -> None:
        """为服务 ``name`` 注入配置覆盖，沿链浅合并（子覆盖父）。"""
        self._intercepts.setdefault(name, {}).update(config)

    def get_config(self, name: str) -> dict[str, Any]:
        """收集从根到当前节点的配置覆盖，浅合并。"""
        merged: dict[str, Any] = {}
        chain: list[Context] = []
        node: Context | None = self
        while node is not None:
            chain.append(node)
            node = node.parent
        for node in reversed(chain):  # 根在前，子覆盖父
            merged.update(node._intercepts.get(name, {}))
        return merged

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def on(self, event: str, listener: Callable[[Any], None]) -> Disposable:
        """注册监听器，返回 disposable（调用即解绑，可随 fiber dispose）。"""
        self._listeners.setdefault(event, []).append(listener)

        def _off() -> None:
            listeners = self._listeners.get(event)
            if listeners and listener in listeners:
                listeners.remove(listener)

        return Disposable(_off)

    def emit(self, event: str, payload: Any = None) -> None:
        """沿 context 链自当前节点向根传播事件。"""
        node: Context | None = self
        while node is not None:
            for listener in list(node._listeners.get(event, ())):
                listener(payload)
            node = node.parent
