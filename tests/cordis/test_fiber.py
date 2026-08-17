"""Fiber 单元测试：dispose 逆序、幂等、异步 disposable、插件启停。"""

import asyncio

import pytest

from praxic.cordis import Context, Fiber


def run(coro):
    return asyncio.run(coro)


def test_dispose_reverse_order():
    """disposable 逆序执行（AsyncExitStack 语义）。"""
    fiber = Fiber()
    order = []
    fiber.register(lambda: order.append("a"))
    fiber.register(lambda: order.append("b"))
    fiber.register(lambda: order.append("c"))
    run(fiber.dispose())
    assert order == ["c", "b", "a"]


def test_dispose_idempotent():
    """dispose 幂等：第二次调用不再执行。"""
    fiber = Fiber()
    calls = []

    def fn():
        calls.append(1)

    fiber.register(fn)
    run(fiber.dispose())
    run(fiber.dispose())
    assert len(calls) == 1


def test_async_disposable_awaited():
    """异步 disposable 被 await，且保持逆序。"""
    fiber = Fiber()
    order = []

    async def cleanup():
        await asyncio.sleep(0)
        order.append("async")

    fiber.register(lambda: order.append("sync"))
    fiber.register(cleanup)
    run(fiber.dispose())
    assert order == ["async", "sync"]


def test_effect_registers_returned_disposable():
    """effect 的返回值若可调用则自动注册为清理函数。"""
    fiber = Fiber()
    order = []

    def effect():
        return lambda: order.append("cleanup")

    fiber.effect(effect)
    assert order == []  # 副作用本身不执行清理
    run(fiber.dispose())
    assert order == ["cleanup"]


def test_dispose_error_collected_not_interrupting():
    """单个清理抛错不中断其余清理，首个错误最后抛出。"""
    fiber = Fiber()
    order = []

    def bad():
        raise RuntimeError("boom")

    fiber.register(bad)
    fiber.register(lambda: order.append("after"))
    with pytest.raises(RuntimeError):
        run(fiber.dispose())
    assert order == ["after"]


def test_disposable_instance_registered():
    """Disposable 实例注册进 fiber 后随 dispose 解绑。"""
    from praxic.cordis import Disposable

    fiber = Fiber()
    ctx = Context()
    seen = []
    d = ctx.on("evt", lambda p: seen.append(p))
    fiber.register(d)
    ctx.emit("evt", 1)
    run(fiber.dispose())
    ctx.emit("evt", 2)
    assert seen == [1]


def test_plugin_start_stop_via_fiber():
    """插件启停：启动注册服务与清理函数，停止逆序执行。"""
    from tests.cordis.fixtures import DisposableService

    ctx = Context()
    fiber = Fiber(ctx)
    order = []

    def plugin_apply():
        # 插件启动：注册服务
        svc = DisposableService(ctx, name="plugin", fiber=fiber)
        order.append(f"start:{svc.name}")
        # 插件自带的停止钩子
        return lambda: order.append("stop:outer")

    fiber.effect(plugin_apply)
    assert ctx.get("plugin") is not None
    assert order == ["start:plugin"]
    run(fiber.dispose())
    # 逆序：后注册的 stop:outer 先执行，再执行服务异步清理
    assert order == ["start:plugin", "stop:outer"]
    assert ctx.get("plugin").disposed is True


def test_dispose_then_dispose_again_safe():
    """连续 dispose 不报错，且清理结果保持。"""
    fiber = Fiber()
    order = []
    fiber.register(lambda: order.append("x"))
    run(fiber.dispose())
    assert order == ["x"]
    # 二次 dispose 后注册新资源不再被清理（fiber 已终结）
    fiber.register(lambda: order.append("y"))
    run(fiber.dispose())
    assert order == ["x"]
