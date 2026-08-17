"""Context 单元测试：parent 链解析、extend 隔离、isolate 独立实例、撞名抛错。"""

import pytest

from praxic.cordis import (
    Context,
    DuplicateServiceError,
    Service,
    UnknownServiceError,
)


class DummyService(Service):
    pass


def make(ctx: Context, name: str) -> DummyService:
    return DummyService(ctx, name=name)


def test_parent_chain_resolution():
    """get 沿 parent 链向上解析。"""
    root = Context()
    svc = make(root, "llm")
    child = root.extend()
    grand = child.extend()
    assert grand.get("llm") is svc


def test_extend_child_invisible_to_parent():
    """子作用域注册不影响父。"""
    root = Context()
    child = root.extend()
    make(child, "mem")
    assert not root.has("mem")
    with pytest.raises(UnknownServiceError):
        root.get("mem")


def test_extend_does_not_leak_into_parent_lookup():
    """父的注册对子可见，但子注册不改变父的解析。"""
    root = Context()
    svc = make(root, "ws")
    child = root.extend()
    assert child.get("ws") is svc
    assert root.get("ws") is svc


def test_isolate_creates_independent_instance():
    """realm 内提供同名服务，父作用域实例不受影响。"""
    root = Context()
    svc = make(root, "llm")
    realm = root.isolate("llm", "session")
    svc2 = make(realm, "llm")
    assert realm.get("llm") is svc2
    assert root.get("llm") is svc


def test_isolate_missing_service_raises():
    """realm 内隔离但未注册的服务不可穿透父，直接报错。"""
    root = Context()
    make(root, "llm")
    realm = root.isolate("llm", "session")
    with pytest.raises(UnknownServiceError):
        realm.get("llm")


def test_duplicate_provide_same_realm_raises():
    """同一 realm 同名第二次注册抛 DuplicateServiceError。"""
    root = Context()
    make(root, "llm")
    with pytest.raises(DuplicateServiceError):
        make(root, "llm")


def test_duplicate_provide_different_realms_ok():
    """不同 realm 各自提供同名服务互不冲突。"""
    root = Context()
    r1 = root.isolate("llm", "a")
    r2 = root.isolate("llm", "b")
    s1 = make(r1, "llm")
    s2 = make(r2, "llm")
    assert r1.get("llm") is s1
    assert r2.get("llm") is s2


def test_child_cannot_shadow_parent_service():
    """子作用域不能遮蔽父已注册的非隔离服务。"""
    root = Context()
    make(root, "llm")
    child = root.extend()
    with pytest.raises(DuplicateServiceError):
        make(child, "llm")


def test_nested_isolate_chain():
    """嵌套隔离：内层 realm 解析自己的实例，不穿透到外层 realm。"""
    root = Context()
    make(root, "llm")
    outer = root.isolate("llm", "outer")
    inner = outer.isolate("llm", "inner")
    svc_inner = make(inner, "llm")
    assert inner.get("llm") is svc_inner
    assert outer.has("llm") is False  # outer 只隔离未提供
    with pytest.raises(UnknownServiceError):
        outer.get("llm")


def test_has_returns_false_for_missing():
    ctx = Context()
    assert ctx.has("nope") is False


def test_intercept_shallow_merge_chain():
    """intercept 沿链浅合并，子覆盖父。"""
    root = Context()
    root.intercept("llm", {"model": "deepseek", "temp": 0.7})
    child = root.extend()
    child.intercept("llm", {"temp": 0.2})
    config = child.get_config("llm")
    assert config == {"model": "deepseek", "temp": 0.2}
    # 父不受子影响
    assert root.get_config("llm") == {"model": "deepseek", "temp": 0.7}
