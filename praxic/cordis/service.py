"""cordis 服务原语。

``Service`` 构造即注册：``Service(ctx, name)`` 会把自己挂到 ctx 链上
最近的隔离域（若 ctx 本身不隔离该名字，则挂到 ctx 自身）。配置经
pydantic schema 校验，失败抛 ``ConfigValidationError``。
"""

from __future__ import annotations

from typing import Any, Type

from pydantic import BaseModel, ValidationError

from .errors import ConfigValidationError


class _EmptyConfig(BaseModel):
    """Service.Config 的默认 schema：不做任何约束。"""


class Service:
    """命名服务基类。

    子类可覆盖 ``Config`` 声明配置 schema；构造时传入的 ``config``
    会被该校验。默认 ``__call__`` 抛错，可调用服务需自行实现。
    """

    Config: Type[BaseModel] = _EmptyConfig

    def __init__(
        self,
        ctx: Any,
        name: str | None = None,
        config: dict | None = None,
    ) -> None:
        self.ctx = ctx
        self.name = name or self.__class__.__name__
        self.config = self._validate(config)
        ctx.provide(self)

    def _validate(self, config: dict | None) -> BaseModel:
        schema = self.Config
        if config is None:
            return schema()
        try:
            return schema(**config)
        except ValidationError as exc:
            raise ConfigValidationError(
                f"服务 {self.name} 配置校验失败: {exc.errors()}"
            ) from exc

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            f"{self.__class__.__name__} 不是可调用服务；如需可调用，请实现 __call__"
        )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<{self.__class__.__name__} name={self.name!r}>"
