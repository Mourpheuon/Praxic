"""
Praxic Agent —— 网络搜索工具
基于 Tavily Search API，为调查阶段提供实时信息获取能力。
"""

from __future__ import annotations

import httpx
from typing import Optional
from dataclasses import dataclass, field

import structlog

from .base import ActionKind, BaseTool, ToolResult, ToolStatus

log = structlog.get_logger(__name__)

TAVILY_API_URL = "https://api.tavily.com/search"


@dataclass
class SearchResult:
    """单条搜索结果"""

    title: str = ""
    url: str = ""
    content: str = ""
    score: float = 0.0


class WebSearchTool(BaseTool):
    """基于 Tavily 的联网搜索工具"""

    name = "web_search"
    category = "knowledge"
    group = "web_search"
    description = "联网搜索获取最新信息，用于补全调查阶段的信息缺口"
    requires_network = True
    action_kind = ActionKind.OBSERVE
    is_concurrency_safe = True

    def __init__(
        self,
        api_key: str = "",
        max_results: int = 5,
        include_answer: bool = True,
        search_depth: str = "basic",  # "basic" | "advanced"
    ):
        self.api_key = api_key
        self.max_results = max_results
        self.include_answer = include_answer
        self.search_depth = search_depth

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def run(
        self,
        query: str,
        max_results: Optional[int] = None,
        search_depth: Optional[str] = None,
    ) -> ToolResult:
        """执行搜索。query: 搜索关键词"""
        if not self.api_key:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error="Tavily API key 未配置，无法执行网络搜索。请在 config.toml [llm] 下设置 tavily_api_key。",
            )

        depth = search_depth or self.search_depth
        n = max_results or self.max_results

        log.info("web_search.start", query=query[:80], depth=depth, max_results=n)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    TAVILY_API_URL,
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "search_depth": depth,
                        "max_results": n,
                        "include_answer": self.include_answer,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            log.error("web_search.http_error", error=str(e))
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"搜索请求失败：{e}",
            )
        except Exception as e:
            log.error("web_search.error", error=str(e))
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"搜索异常：{e}",
            )

        results: list[SearchResult] = []
        for r in data.get("results", []):
            results.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    content=r.get("content", ""),
                    score=float(r.get("score", 0)),
                )
            )

        answer = data.get("answer", "")
        response_time = data.get("response_time", 0)

        # 构建 LLM 友好的文本格式
        lines = []
        if answer:
            lines.append(f"📌 AI 摘要：{answer}\n")
        lines.append(f"共 {len(results)} 条结果（耗时 {response_time:.1f}s）：\n")
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.title}")
            lines.append(f"    URL: {r.url}")
            lines.append(f"    内容: {r.content}")
            lines.append("")

        content = "\n".join(lines)

        log.info("web_search.done", query=query[:40], n_results=len(results))

        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=content,
            data={
                "answer": answer,
                "results": [
                    {"title": r.title, "url": r.url, "content": r.content, "score": r.score}
                    for r in results
                ],
                "response_time": response_time,
            },
            source="Tavily Search API",
            metadata={
                "query": query,
                "n_results": len(results),
                "response_time": response_time,
            },
        )

    @staticmethod
    def format_for_llm(result: ToolResult) -> str:
        """将搜索结果格式化为 LLM prompt 可用的上下文"""
        if not result.ok:
            return f"（搜索失败：{result.error}）"

        lines = ["## 网络搜索结果\n"]
        lines.append(result.content)
        lines.append("---")
        return "\n".join(lines)


class MultiSearchTool:
    """
    批量搜索工具：对多个查询并行搜索，合并结果。
    用于调查阶段针对多个信息缺口同时搜索。
    """

    def __init__(self, search_tool: WebSearchTool):
        self.search = search_tool

    async def search_all(self, queries: list[str]) -> list[ToolResult]:
        """并行执行多个搜索，按 query 顺序返回结果"""
        import asyncio

        if not queries:
            return []

        log.info("multi_search.start", n_queries=len(queries))

        tasks = [self.search.run(q) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: list[ToolResult] = []
        for q, r in zip(queries, results):
            if isinstance(r, BaseException):
                output.append(
                    ToolResult(
                        status=ToolStatus.ERROR,
                        content="",
                        error=f"搜索 '{q[:50]}' 异常：{r}",
                    )
                )
            else:
                output.append(r)

        ok = sum(1 for r in output if r.ok)
        log.info("multi_search.done", total=len(queries), ok=ok)
        return output
