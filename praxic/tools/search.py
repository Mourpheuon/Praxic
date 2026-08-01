"""
Praxic Agent —— 搜索工具
支持 Tavily API（需配置 key）或 DuckDuckGo HTML 解析作为回退
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
import structlog

from .base import ActionKind, BaseTool, ToolResult, ToolStatus

log = structlog.get_logger(__name__)


class TavilySearchTool(BaseTool):
    """Tavily 搜索工具（推荐：返回 LLM 友好的结构化结果）"""

    name = "tavily_search"
    description = "通过 Tavily API 搜索网络，返回摘要和来源"
    requires_network = True
    action_kind = ActionKind.OBSERVE

    def __init__(self, api_key: Optional[str] = None, max_results: int = 5):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY", "")
        self.max_results = max_results
        self._base_url = "https://api.tavily.com/search"

    async def run(self, query: str, **kwargs) -> ToolResult:
        if not self.api_key:
            log.warning("tavily_search.no_api_key")
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error="未配置 TAVILY_API_KEY，搜索功能不可用",
            )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    self._base_url,
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "max_results": self.max_results,
                        "search_depth": "basic",
                        "include_answer": True,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            answer = data.get("answer", "")
            results = data.get("results", [])
            lines = []
            if answer:
                lines.append(f"[摘要] {answer}\n")
            for r in results[:self.max_results]:
                lines.append(
                    f"【{r.get('title', '无标题')}】\n"
                    f"来源：{r.get('url', '')}\n"
                    f"{r.get('content', '')}\n"
                )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                content="\n".join(lines),
                data=data,
                source=self._base_url,
            )

        except Exception as exc:
            log.error("tavily_search.error", exc=str(exc))
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=str(exc),
            )


class MockSearchTool(BaseTool):
    """
    模拟搜索工具（无需外部 API，用于开发和测试）
    直接返回一个提示，告知 LLM 进行内部推理
    """

    name = "mock_search"
    description = "模拟搜索（开发模式），基于内部知识回答"
    requires_network = False
    action_kind = ActionKind.OBSERVE

    async def run(self, query: str, **kwargs) -> ToolResult:
        content = (
            f"[模拟搜索] 查询：{query}\n"
            "注意：当前运行在无外部搜索的模式下。"
            "以下分析将完全基于模型的内部知识进行，请在调查结果中标注来源为 'internal'，"
            "并将可信度设为 'medium'。"
        )
        return ToolResult(
            status=ToolStatus.PARTIAL,
            content=content,
            source="internal",
        )


def get_search_tool() -> BaseTool:
    """根据环境配置返回合适的搜索工具"""
    tavily_key = os.getenv("TAVILY_API_KEY", "")
    if tavily_key:
        return TavilySearchTool(api_key=tavily_key)
    log.info("search_tool.using_mock", reason="no TAVILY_API_KEY")
    return MockSearchTool()
