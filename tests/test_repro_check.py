"""程序化复核测试：实践实验的独立复跑比对。"""

import asyncio

from praxic.core.repro_check import check_python_reproducibility, repro_stats


def test_reproduced_and_differs():
    async def _go():
        from praxic.tools.python_exec import PythonExecTool

        t = PythonExecTool(workspace_dir="")
        r = await t.run(code="print(1+1)", timeout_seconds=20)
        base = r.content
        records = [
            {"call_id": "a", "tool": "python_exec", "parameters": {"code": "print(1+1)"}, "result": {"content": base}},
            {"call_id": "b", "tool": "python_exec", "parameters": {"code": "print(1+1)"}, "result": {"content": "999 错误基线"}},
        ]
        checks = await check_python_reproducibility(records, "")
        by_id = {c["call_id"]: c for c in checks}
        assert len(checks) == 2
        assert by_id["a"]["status"] == "reproduced"
        assert by_id["b"]["status"] == "differs"

    asyncio.run(_go())


def test_rerun_error_for_banned_imports():
    async def _go():
        records = [
            {"call_id": "c", "tool": "python_exec", "parameters": {"code": "import os"}, "result": {"content": "x"}},
        ]
        checks = await check_python_reproducibility(records, "")
        assert checks[0]["status"] == "rerun_error"

    asyncio.run(_go())


def test_skips_non_python_records():
    async def _go():
        records = [
            {"call_id": "d", "tool": "shell_exec", "parameters": {"command": ["pwd"]}, "result": {"content": "/"}},
            {"call_id": "e", "tool": "python_exec", "parameters": {}, "result": {"content": "x"}},
        ]
        checks = await check_python_reproducibility(records, "")
        assert checks == []

    asyncio.run(_go())


def test_repro_stats_counts():
    stats = repro_stats([
        {"status": "reproduced"}, {"status": "reproduced"},
        {"status": "differs"}, {"status": "no_baseline"}, {"status": "rerun_error"},
    ])
    assert stats == {"total": 5, "reproduced": 2, "differs": 1, "no_baseline": 1, "rerun_error": 1}