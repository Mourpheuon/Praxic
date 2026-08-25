"""实践相位程序化复核：python_exec 实验的可复现性校验。

"实践是检验真理的唯一标准"的结构化兑现——LLM 不能自评"实验证实了结论"，
实验必须能被程序独立复跑并得到一致输出。输出不一致（含非确定代码）标记
differs 并附双方输出，不硬性判错；由下游与指标消费。
"""

from __future__ import annotations

import asyncio
import re

import structlog

log = structlog.get_logger(__name__)


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:500]


async def _rerun(code: str, workspace_dir: str):
    from ..tools.python_exec import PythonExecTool

    tool = PythonExecTool(workspace_dir=workspace_dir or "")
    try:
        return await asyncio.wait_for(
            tool.run(code=code, timeout_seconds=20), timeout=30
        )
    except Exception as exc:  # noqa: BLE001
        return exc


async def check_python_reproducibility(tool_records, workspace_dir: str = "") -> list[dict]:
    """对 python_exec 工具记录做独立复跑比对。

    返回每项 {call_id, status, recorded_head, actual_head, error}，
    status ∈ reproduced | differs | no_baseline | rerun_error。
    """
    checks = []
    for r in tool_records or []:
        if not isinstance(r, dict):
            continue
        if (r.get("tool") or r.get("tool_name") or "") != "python_exec":
            continue
        params = r.get("parameters") or {}
        code = params.get("code") or ""
        if not code:
            continue
        result = r.get("result") or {}
        recorded = (
            result.get("content")
            or result.get("stdout")
            or (result.get("data") or {}).get("content")
            or ""
        )
        entry = {
            "call_id": r.get("call_id", ""),
            "status": "no_baseline",
            "recorded_head": _norm(recorded),
            "actual_head": "",
            "error": "",
        }
        outcome = await _rerun(code, workspace_dir)
        if isinstance(outcome, Exception):
            entry["status"] = "rerun_error"
            entry["error"] = str(outcome)[:200]
        else:
            st = getattr(getattr(outcome, "status", None), "value", "")
            actual = getattr(outcome, "content", "") or ""
            entry["actual_head"] = _norm(actual)
            if st == "error":
                entry["status"] = "rerun_error"
                entry["error"] = str(getattr(outcome, "error", "") or "")[:200]
            elif not entry["recorded_head"]:
                entry["status"] = "no_baseline"
            elif entry["recorded_head"] == entry["actual_head"]:
                entry["status"] = "reproduced"
            else:
                entry["status"] = "differs"
        checks.append(entry)
    return checks


def repro_stats(checks: list[dict]) -> dict:
    """复核统计：{total, reproduced, differs, no_baseline, rerun_error}。"""
    stats = {"total": len(checks), "reproduced": 0, "differs": 0, "no_baseline": 0, "rerun_error": 0}
    for c in checks:
        key = c.get("status", "no_baseline")
        if key in stats:
            stats[key] += 1
    return stats