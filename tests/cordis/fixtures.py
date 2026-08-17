"""tests/cordis 的 loader fixture：供 ``module:Class`` 组合声明引用的服务类。

这些类只在测试包内存在，组合测试通过 ``tests.cordis.fixtures:ClassName``
的形式由 importlib 导入。
"""

from pydantic import BaseModel, Field

from praxic.cordis import Service


class CounterService(Service):
    """可调用计数服务：每次调用自增并返回计数。"""

    def __init__(self, ctx, name=None, config=None):
        super().__init__(ctx, name, config)
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.calls


class GreetingService(Service):
    """带默认配置的可调用服务。"""

    class Config(BaseModel):
        greeting: str = "hello"

    def __call__(self):
        return self.config.greeting


class StrictService(Service):
    """配置带约束：threshold 必须在 [0, 100]。"""

    class Config(BaseModel):
        threshold: int = Field(ge=0, le=100)


class DisposableService(Service):
    """注册进 fiber 后 dispose 会触发异步清理。"""

    def __init__(self, ctx, name=None, config=None, fiber=None):
        super().__init__(ctx, name, config)
        self.disposed = False
        if fiber is not None:
            fiber.register(self._cleanup)

    async def _cleanup(self):
        self.disposed = True


class DepService(Service):
    """构造时从 ctx 解析依赖服务。"""

    def __init__(self, ctx, name=None, config=None, dep=None):
        super().__init__(ctx, name, config)
        self.dep_name = dep or "llm"
        self.dep = ctx.get(self.dep_name)
