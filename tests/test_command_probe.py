"""command_probe —— PATH 命令存在性探测（只读）测试。

覆盖：命中（found=true + path）、未命中（found=false）、非法命令名
（空 / 含路径分隔符 / 含空白 → ERROR）、assembler 注册（action_kind=observe）。
"""

from __future__ import annotations

import os
import shutil
import sys

import pytest

from praxic.tools.assembler import register_workspace_tools
from praxic.tools.base import ToolStatus
from praxic.tools.command_probe import CommandProbeTool
from praxic.tools.registry import ToolRegistry


def _known_command() -> str:
    """返回一个 shutil.which 确定能解析的命令名（跨平台稳定）。"""
    candidates = [os.path.basename(sys.executable)]
    if sys.executable.lower().endswith(".exe"):
        candidates.append(os.path.basename(sys.executable)[:-4])
    # Windows 上 where/cmd 必然在 PATH；POSIX 上 sh/ls 必然在 PATH
    candidates.extend(["where", "cmd"] if os.name == "nt" else ["sh", "ls", "cat"])
    for name in candidates:
        if shutil.which(name):
            return name
    raise AssertionError("环境异常：找不到任何已知存在于 PATH 的命令")


@pytest.mark.asyncio
async def test_probe_found():
    tool = CommandProbeTool()
    name = _known_command()
    result = await tool.run(command=name)
    assert result.status == ToolStatus.SUCCESS
    assert result.data["found"] is True
    assert result.data["command"] == name
    assert result.data["path"]
    assert result.content.startswith("found:")
    # 与 shutil.which 的解析结果一致（同一 PATH 同一查询）
    assert result.data["path"] == shutil.which(name)


@pytest.mark.asyncio
async def test_probe_not_found():
    tool = CommandProbeTool()
    name = "definitely_not_a_real_cmd_xyz"
    assert shutil.which(name) is None  # 前置条件：确实不存在
    result = await tool.run(command=name)
    assert result.status == ToolStatus.SUCCESS
    assert result.data["found"] is False
    assert result.data["command"] == name
    assert "not found" in result.content
    assert name in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "",                      # 空
        "   ",                   # 纯空白
        "lean/lake",             # 含 / 路径分隔符
        "C:\\tools\\lean.exe",   # 含 \ 路径分隔符（Windows 全路径）
        "lean lake",             # 含空白
        " lean",                 # 前导空白
    ],
)
async def test_invalid_command(bad):
    tool = CommandProbeTool()
    result = await tool.run(command=bad)
    assert result.status == ToolStatus.ERROR
    assert result.error


@pytest.mark.asyncio
async def test_registered(tmp_path):
    registry = ToolRegistry()
    register_workspace_tools(registry, tmp_path)
    assert "command_probe" in registry.get_names()
    descs = {d["name"]: d for d in registry.tool_descriptions()}
    assert descs["command_probe"]["action_kind"] == "observe"
    assert descs["command_probe"]["category"] == "system"
    assert descs["command_probe"]["requires_network"] is False


@pytest.mark.asyncio
async def test_registry_call_auto_allowed(tmp_path):
    """OBSERVE 类走 registry 调用应自动放行，无需授权。"""
    registry = ToolRegistry()
    register_workspace_tools(registry, tmp_path)
    result = await registry.call("command_probe", command=_known_command())
    assert result.status == ToolStatus.SUCCESS
    assert result.data["found"] is True
    assert result.permission.decision.value == "allow"
