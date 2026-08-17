"""cordis 内核错误类型。

错误分层：
- ``CordisError`` 为所有内核错误基类；
- 注册/解析类错误（Duplicate / Unknown）由 Context 层抛出；
- 组合级错误（InjectCycle / Composition）由 loader 层抛出；
- 配置校验错误（ConfigValidation）由 Service 构造抛出。
"""


class CordisError(Exception):
    """所有 cordis 错误的基类。"""


class DuplicateServiceError(CordisError):
    """同一 realm 内同名服务重复注册（单例语义，对齐 cordis）。"""


class UnknownServiceError(CordisError):
    """按名解析服务失败：未注册，或在隔离域内隔离但未提供。"""


class ConfigValidationError(CordisError):
    """服务配置未通过 pydantic schema 校验。"""


class InjectCycleError(CordisError):
    """组合中的 inject 依赖构成环，组合无法启动。"""


class CompositionError(CordisError):
    """组合行加载失败：schema 非法、导入失败或依赖不可用。"""
