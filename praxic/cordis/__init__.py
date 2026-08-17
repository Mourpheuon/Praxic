"""Praxic cordis —— dsh cordis 内核思想的 Python 重实现。

对应 cordisjs Meta-Framework 的核心原语：

- ``Context``  原型链式依赖容器：extend / isolate / intercept / get
- ``Service``  命名服务，构造即注册，配置 pydantic 校验
- ``Fiber``    生命周期：逆序清理、幂等、异步 disposable
- ``Registry`` 插件注册表：inject 依赖、可用性驱动激活、环检测
- ``load_composition``  YAML 组合加载（group 嵌套 / isolate / disabled）

纯 stdlib + PyYAML + pydantic，无新增第三方依赖。
"""

from .context import Context
from .errors import (
    CompositionError,
    ConfigValidationError,
    CordisError,
    DuplicateServiceError,
    InjectCycleError,
    UnknownServiceError,
)
from .events import Disposable
from .fiber import Fiber
from .loader import LoadResult, LoadedRow, eval_disabled, load_composition
from .registry import PluginDef, Registry, import_class
from .service import Service

__all__ = [
    "CompositionError",
    "ConfigValidationError",
    "Context",
    "CordisError",
    "Disposable",
    "DuplicateServiceError",
    "Fiber",
    "InjectCycleError",
    "LoadResult",
    "LoadedRow",
    "PluginDef",
    "Registry",
    "Service",
    "UnknownServiceError",
    "eval_disabled",
    "import_class",
    "load_composition",
]

__version__ = "0.1.0"
