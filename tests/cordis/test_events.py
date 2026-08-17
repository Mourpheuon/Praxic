"""事件单元测试：沿链传播（子→根）、监听器随 fiber dispose 移除。"""

import asyncio

import pytest

from praxic.cordis import Context, Fiber


def test_emit_propagates_up_chain():
    """事件自当前节点向根传播，父与子监听器都收到。"""
    root = Context()
    child = root.extend()
    grand = child.extend()
    seen = []
    root.on("evt", lambda p: seen.append(("root", p)))
    child.on("evt", lambda p: seen.append(("child", p)))
    grand.emit("evt", {"x": 1})
    assert seen == [("child", {"x": 1}), ("root", {"x": 1})]


def test_emit_does_not_propagate_down():
    """事件不下行：父 emit 子监听器不收到。"""
    root = Context()
    child = root.extend()
    seen = []
    child.on("evt", lambda p: seen.append(p))
    root.emit("evt", 1)
    assert seen == []


def test_emit_does_not_cross_siblings():
    """兄弟作用域事件互不串扰。"""
    root = Context()
    a = root.extend()
    b = root.extend()
    seen = []
    a.on("evt", lambda p: seen.append(p))
    b.emit("evt", 1)
    assert seen == []


def test_listener_disposable_removes():
    """on 返回的 disposable 调用后监听器解绑。"""
    root = Context()
    seen = []
    d = root.on("evt", lambda p: seen.append(p))
    root.emit("evt", 1)
    d.dispose()
    root.emit("evt", 2)
    assert seen == [1]


def test_listener_disposable_idempotent():
    """disposable 二次调用不再解绑其他监听器。"""
    root = Context()
    seen = []
    d = root.on("evt", lambda p: seen.append(p))
    d.dispose()
    d.dispose()
    root.emit("evt", 1)
    assert seen == []


def test_listener_removed_with_fiber_dispose():
    """监听器注册进 fiber 后，随 fiber dispose 移除。"""
    root = Context()
    fiber = Fiber()
    seen = []
    d = root.on("evt", lambda p: seen.append(p))
    fiber.register(d)
    root.emit("evt", 1)
    asyncio.run(fiber.dispose())
    root.emit("evt", 2)
    assert seen == [1]


def test_multiple_listeners_same_event():
    """同一事件多个监听器按注册顺序触发。"""
    root = Context()
    seen = []
    root.on("evt", lambda p: seen.append("a"))
    root.on("evt", lambda p: seen.append("b"))
    root.emit("evt", None)
    assert seen == ["a", "b"]


def test_emit_isolated_realms_still_propagate():
    """realm 内 emit 沿链传播到祖先监听器。"""
    root = Context()
    realm = root.isolate("llm", "session")
    seen = []
    root.on("evt", lambda p: seen.append(p))
    realm.emit("evt", 42)
    assert seen == [42]
