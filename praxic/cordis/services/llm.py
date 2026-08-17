"""LLM 服务壳：包装现有 ``get_llm()`` 全局入口。

组合里的 ``llm`` 行激活后，其他服务（阶段模块、语义审核器）通过
``ctx.get("llm").get()`` 拿到真实 LLM 实例。
"""

from __future__ import annotations

from praxic.cordis import Service
from praxic.llm import get_llm


class LLMService(Service):
    """llm 服务壳。构造即解析全局 LLM 并持有。"""

    def __init__(self, ctx, name=None, config=None):
        super().__init__(ctx, name, config)
        self._llm = get_llm()

    def get(self):
        """返回底层 LLM 实例。"""
        return self._llm
