"""Service 单元测试：构造即注册、pydantic 校验失败、可调用服务。"""

import pytest
from pydantic import BaseModel, Field

from praxic.cordis import ConfigValidationError, Context, Service


class PlainService(Service):
    pass


class CallableService(Service):
    def __call__(self, a, b):
        return a + b


class ConfigService(Service):
    class Config(BaseModel):
        name: str = "default"
        retries: int = Field(default=3, ge=0, le=10)


def test_construction_registers_into_ctx():
    """构造即注册：Service(ctx, name) 后 ctx.get(name) 可解析。"""
    ctx = Context()
    svc = PlainService(ctx, name="plain")
    assert ctx.get("plain") is svc


def test_default_name_is_class_name():
    """未显式传 name 时用类名。"""
    ctx = Context()
    svc = PlainService(ctx)
    assert svc.name == "PlainService"
    assert ctx.get("PlainService") is svc


def test_config_validated_by_pydantic():
    """合法配置被解析为 Config 实例。"""
    ctx = Context()
    svc = ConfigService(ctx, name="cfg", config={"retries": 5})
    assert svc.config.retries == 5
    assert svc.config.name == "default"


def test_config_validation_failure_raises():
    """非法配置抛 ConfigValidationError（pydantic 校验失败）。"""
    ctx = Context()
    with pytest.raises(ConfigValidationError):
        ConfigService(ctx, name="cfg", config={"retries": 99})


def test_config_optional():
    """不传 config 时使用 Config 默认值。"""
    ctx = Context()
    svc = ConfigService(ctx, name="cfg")
    assert svc.config.retries == 3


def test_callable_service():
    """实现 __call__ 的服务可被调用。"""
    ctx = Context()
    svc = CallableService(ctx, name="calc")
    assert svc(1, 2) == 3


def test_non_callable_service_raises():
    """未实现 __call__ 的服务调用时抛 NotImplementedError。"""
    ctx = Context()
    svc = PlainService(ctx, name="plain")
    with pytest.raises(NotImplementedError):
        svc()


def test_config_error_chains_validation():
    """ConfigValidationError 继承自 CordisError，可被统一捕获。"""
    from praxic.cordis import CordisError

    ctx = Context()
    with pytest.raises(CordisError):
        ConfigService(ctx, name="cfg", config={"retries": -1})
