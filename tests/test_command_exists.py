"""command_probe 批量/版本探测测试：实践检验管道的第一米。"""

import asyncio

from praxic.tools.command_probe import CommandProbeTool


def _run(coro):
    return asyncio.run(coro)


def test_python_found_with_version():
    async def _go():
        tool = CommandProbeTool()
        r = await tool.run(commands=["python"], with_version=True)
        assert r.status.value == "success"
        assert r.data["python"]["found"] is True
        assert r.data["python"]["path"]
        assert r.data["python"]["version"]  # python 的 --version 可解析

    _run(_go())


def test_garbage_command_not_found():
    async def _go():
        tool = CommandProbeTool()
        r = await tool.run(commands=["definitely_not_a_cmd_xyz_12345"], with_version=False)
        assert r.status.value == "success"
        assert r.data["definitely_not_a_cmd_xyz_12345"]["found"] is False
        assert r.data["definitely_not_a_cmd_xyz_12345"]["path"] is None

    _run(_go())


def test_batch_mode_isolates_failures():
    async def _go():
        tool = CommandProbeTool()
        r = await tool.run(commands=["python", "definitely_not_a_cmd_xyz_12345"], with_version=False)
        assert r.data["python"]["found"] is True
        assert r.data["definitely_not_a_cmd_xyz_12345"]["found"] is False
        assert "✓ python" in r.content
        assert "✗ definitely_not_a_cmd_xyz_12345" in r.content

    _run(_go())


def test_empty_commands_errors():
    async def _go():
        tool = CommandProbeTool()
        r = await tool.run(commands=[], with_version=False)
        assert r.status.value == "error"

    _run(_go())