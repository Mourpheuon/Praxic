"""cordis 事件原语。

``Disposable`` 是一次性资源句柄：调用一次即与宿主解绑，可注册进 Fiber
统一随生命周期清理。事件本身的 on/emit 沿 context 链传播的逻辑定义在
``Context`` 上（见 ``praxic.cordis.context``），这里只提供句柄与辅助。
"""

from __future__ import annotations

from typing import Any, Callable


class Disposable:
    """一次性资源：首次调用执行清理，之后调用为空操作。"""

    __slots__ = ("_fn", "_disposed")

    def __init__(self, fn: Callable[[], Any] | None = None):
        self._fn = fn
        self._disposed = False

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.dispose()

    def dispose(self) -> Any:
        """幂等地执行清理函数。返回清理结果（仅首次）。"""
        if self._disposed:
            return None
        self._disposed = True
        if self._fn is not None:
            return self._fn()
        return None

    @property
    def disposed(self) -> bool:
        return self._disposed

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        state = "disposed" if self._disposed else "active"
        return f"<Disposable {state}>"
