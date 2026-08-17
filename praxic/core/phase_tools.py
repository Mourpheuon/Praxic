"""
Praxic Agent —— 阶段工具能力（方案 A：统一通道 + 阶段清单 + 轻量决策）

设计：所有阶段走同一个 ToolRegistry，但各阶段只暴露允许的工具子集。
实践阶段保持完整编排（规划-执行-台账）；其他阶段用轻量探查：
LLM 在输出里声明 tool_calls（限阶段清单）→ 框架执行 → 结果回填再回答。

工具能力分层：
- 预处理/调查：web + 文件只读（信息获取）
- 矛盾/理性：文件只读 + 数据查询（参考前序产物）
- 反思：文件只读（核对产物）
- 实践：全部（最强最全面）
"""

from __future__ import annotations

import json
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ── 阶段工具清单（轻量探查允许的子集）──────────────────────────
# practice 阶段不在此列：它使用全量 registry（最强最全面）。

PHASE_TOOLS: dict[str, list[str]] = {
    "preprocessing": [
        "file_list", "file_read", "file_stat", "file_grep",
        "web_search", "web_fetch", "data_query",
    ],
    "investigation": [
        "web_search", "web_fetch",
        "file_list", "file_read", "file_stat", "file_grep", "file_batch_read",
        "data_query", "sqlite_query", "pdf_extract", "env_tool", "time_tool",
    ],
    "contradiction": [
        "file_read", "file_batch_read", "data_query", "sqlite_query", "pdf_extract",
    ],
    "rational": [
        "file_read", "file_batch_read", "data_query", "sqlite_query", "pdf_extract",
    ],
    "reflection": [
        "file_read", "file_stat", "data_query",
    ],
    # practice 不在表里：全量工具 + 完整编排
}

# 探查调用最多执行的工具数（轻量，避免拖慢认知循环）
_MAX_PROBE_CALLS = 3


def phase_tool_names(phase: str) -> list[str]:
    """某阶段允许的工具名列表（practice 返回 None 表示全量）。"""
    if phase == "practice":
        return []
    return PHASE_TOOLS.get(phase, [])


def phase_tools_text(registry, phase: str) -> str:
    """生成某阶段的工具清单文本（供探查 prompt 注入）。"""
    if phase == "practice":
        try:
            return registry.format_for_prompt()
        except Exception:
            return "（工具不可用）"
    allowed = phase_tool_names(phase)
    if not allowed:
        return "（本阶段无需额外工具）"
    try:
        return registry.format_for_prompt(
            categories=None, grouped=False,
        ).split("## 可用工具")[-1] if False else _filter_tools_text(registry, allowed)
    except Exception:
        return "（工具不可用）"


def _filter_tools_text(registry, allowed: list[str]) -> str:
    """从 registry 的工具清单中过滤出允许的工具。"""
    try:
        full = registry.format_for_prompt()
    except Exception:
        return "（工具不可用）"
    # 简单过滤：按工具名区块截取
    lines = full.split("\n")
    out = ["## 可用工具（本阶段允许）\n"]
    current: list[str] = []
    current_name = ""
    for line in lines:
        if line.startswith("### "):
            if current and current_name in allowed:
                out.extend(current)
            current_name = line[4:].strip()
            current = [line]
        elif current_name in allowed:
            current.append(line)
    if current and current_name in allowed:
        out.extend(current)
    return "\n".join(out) if len(out) > 1 else "（本阶段无允许工具）"


def build_probe_prompt(question: str, phase: str, registry, extra_context: str = "") -> str:
    """构造阶段的工具探查 prompt。"""
    tools_text = phase_tools_text(registry, phase)
    context_block = f"\n\n## 本阶段已有材料\n{extra_context[:2000]}" if extra_context else ""
    return (
        "你正在执行认知循环的「" + phase + "」阶段。是否需要调用工具获取额外信息来更好完成本阶段任务？\n"
        "- 若现有材料足以完成，输出 need_tools=false；\n"
        "- 若需要查看文件、查询数据、搜索网络才能补足（如读前序产物、查工作区文件），输出 need_tools=true 并给出工具调用。\n\n"
        + tools_text
        + context_block
        + "\n\n输出严格 JSON：{\"need_tools\": true|false, \"tool_calls\": [{\"tool\": \"工具名\", \"params\": {...}}], \"reason\": \"一句话\"}"
    )


def parse_probe_response(raw: str) -> dict:
    """解析探查 LLM 响应，返回 {need_tools, tool_calls}。"""
    s = str(raw or "").strip()
    try:
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            data = json.loads(s[start:end + 1])
        else:
            return {"need_tools": False, "tool_calls": []}
    except Exception:
        return {"need_tools": False, "tool_calls": []}
    calls = data.get("tool_calls") or []
    # 过滤：只保留阶段允许的工具
    return {"need_tools": bool(data.get("need_tools")), "tool_calls": calls if isinstance(calls, list) else []}


async def run_phase_probe(llm, registry, question: str, phase: str, extra_context: str = "") -> str:
    """执行一次阶段工具探查：LLM 声明 → 执行 → 返回结果文本（无工具则空串）。"""
    if phase == "practice":
        return ""
    from ..tools.base import ToolResult
    allowed = phase_tool_names(phase)
    try:
        prompt = build_probe_prompt(question, phase, registry, extra_context)
        resp = await llm.call(
            messages=[{"role": "user", "content": prompt}],
            system="你是判断是否需要用工具的回答助手。",
            temperature=0.1,
            max_tokens=800,
            enable_reasoning=False,
        )
        plan = parse_probe_response(resp.content)
        if not plan.get("need_tools"):
            return ""
        results = []
        count = 0
        for tc in (plan.get("tool_calls") or []):
            if count >= _MAX_PROBE_CALLS:
                break
            tname = str(tc.get("tool", ""))
            params = tc.get("params") or {}
            if not tname:
                continue
            if allowed and tname not in allowed:
                results.append(f"[{tname}] 该工具不在本阶段允许清单，跳过")
                continue
            try:
                result = await registry.call(tname, **params)
                snippet = (result.content or "")[:500] if isinstance(result, ToolResult) else str(result)[:500]
                if not snippet and getattr(result, "error", ""):
                    snippet = f"错误: {result.error[:200]}"
                results.append(f"[{tname}] {snippet}")
                count += 1
            except Exception as e:
                results.append(f"[{tname}] 调用失败: {str(e)[:200]}")
                count += 1
        if results:
            return "\n\n## 工具探查结果（真实执行）\n" + "\n".join(results)
        return ""
    except Exception as e:
        log.warning("phase_tools.probe_error", phase=phase, error=str(e))
        return ""
