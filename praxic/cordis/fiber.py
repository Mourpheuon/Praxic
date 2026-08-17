"""cordis 生命周期：Fiber。

Fiber 持有 disposable 列表，``dispose()`` 时逆序执行（AsyncExitStack
语义），幂等，且支持异步清理函数。插件启动产生的资源、事件监听器、
后台任务都可以注册进 Fiber 统一清理。

后台任务（asyncio.Task）用 ``track_task`` 单独登记：dispose 时先
cancel 并 await 全部任务，再逆序执行其余 disposable（防协程泄漏与
僵尸广播竞态）。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

import structlog

from .events import Disposable

log = structlog.get_logger(__name__)


class Fiber:
    """生命周期容器。"""

    __slots__ = ("ctx", "_disposables", "_tasks", "_disposed")

    def __init__(self, ctx: Any = None) -> None:
        self.ctx = ctx
        self._disposables: list[Callable[[], Any]] = []
        self._tasks: list[asyncio.Task] = []
        self._disposed = False

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------
    def register(self, fn: Callable[[], Any] | Disposable) -> None:
        """注册清理函数（可同步或异步，可为 Disposable 实例）。"""
        self._disposables.append(fn)

    def effect(self, fn: Callable[[], Any]) -> Any:
        """运行副作用；若返回值可调用则自动注册为清理函数。"""
        result = fn()
        if callable(result):
            self.register(result)
        return result

    def track_task(self, task: asyncio.Task) -> None:
        """登记一个后台任务：dispose 时先 cancel 并 await，再逆序清理其余。"""
        self._tasks.append(task)

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------
    @property
    def disposed(self) -> bool:
        return self._disposed

    async def dispose(self) -> None:
        """先 cancel 后台任务并 await，再逆序执行其余 disposable，幂等。

        单个清理函数抛错不中断其余清理；首个错误在全部清理完成后
        重新抛出（其余错误记录日志）。
        """
        if self._disposed:
            return
        self._disposed = True
        errors: list[Exception] = []
        # 1) 后台任务：全部 cancel 后统一 await
        tasks = self._tasks
        self._tasks = []
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass  # 预期：任务被本 fiber 取消
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
                log.warning("cordis.fiber.task_error", error=str(exc))
        # 2) 其余 disposable：逆序执行
        for item in reversed(self._disposables):
            try:
                result = item()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # noqa: BLE001 - 收集而非中断
                errors.append(exc)
                log.warning("cordis.fiber.dispose_error", error=str(exc))
        self._disposables.clear()
        if errors:
            raise errors[0]
