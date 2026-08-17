"""阶段工具能力（方案 A）：阶段清单 + 轻量探查执行。"""
import json
from pathlib import Path

import pytest

from praxic.config import settings
from praxic.core.autonomy import PermissionMode
from praxic.core.phase_tools import (
    PHASE_TOOLS,
    build_probe_prompt,
    parse_probe_response,
    phase_tool_names,
    run_phase_probe,
)
from praxic.llm.base import BaseLLM, LLMResponse
from praxic.tools.assembler import register_workspace_tools
from praxic.tools.base import BaseTool
from praxic.tools.permissions import PermissionPolicy
from praxic.tools.python_exec import PythonExecTool
from praxic.tools.registry import ToolRegistry
from praxic.tools.shell import ShellTool


@pytest.fixture
def registry(tmp_path):
    settings.permission_mode = PermissionMode.AUTO_REVIEW
    reg = ToolRegistry(
        policy=PermissionPolicy(permission_mode=PermissionMode.AUTO_REVIEW, allowed_roots=(tmp_path,))
    )
    register_workspace_tools(reg, tmp_path)
    reg.register(PythonExecTool(workspace_dir=tmp_path))
    reg.register(ShellTool(allowed_roots=(tmp_path,)))
    return reg


def test_phase_tool_lists():
    # 调查：web + 文件只读
    assert "web_search" in phase_tool_names("investigation")
    assert "file_read" in phase_tool_names("investigation")
    # 矛盾/理性：文件只读，无写工具
    assert "file_read" in phase_tool_names("contradiction")
    assert "shell_exec" not in phase_tool_names("contradiction")
    assert "file_write" not in phase_tool_names("rational")
    # 实践：全量（返回空表，由调用方走完整编排）
    assert phase_tool_names("practice") == []


def test_parse_probe_response():
    p = parse_probe_response(
        '{"need_tools": true, "tool_calls": [{"tool": "file_read", "params": {"path": "x"}}]}'
    )
    assert p["need_tools"] is True
    assert p["tool_calls"][0]["tool"] == "file_read"
    # 非法输入 fail-closed
    assert parse_probe_response("不是JSON")["need_tools"] is False
    assert parse_probe_response("")["need_tools"] is False


def test_build_probe_prompt_injects_phase_tools(registry):
    prompt = build_probe_prompt("分析", "contradiction", registry)
    assert "contradiction" in prompt
    assert "file_read" in prompt  # 阶段允许的工具在清单里
    assert "shell_exec" not in prompt  # 越权工具不暴露


class _ProbeLLM(BaseLLM):
    def __init__(self, plan):
        self.plan = plan

    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        return LLMResponse(content=json.dumps(self.plan), model="f")

    async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        yield ""


@pytest.mark.asyncio
async def test_probe_runs_allowed_tool(tmp_path, registry):
    (tmp_path / "notes.txt").write_text("关键产物内容", encoding="utf-8")
    llm = _ProbeLLM({
        "need_tools": True,
        "tool_calls": [{"tool": "file_read", "params": {"path": "notes.txt"}}],
    })
    result = await run_phase_probe(llm, registry, "分析", "contradiction")
    assert "工具探查结果" in result
    assert "关键产物内容" in result


@pytest.mark.asyncio
async def test_probe_filters_out_of_scope_tools(tmp_path, registry):
    llm = _ProbeLLM({
        "need_tools": True,
        "tool_calls": [{"tool": "shell_exec", "params": {"command": ["ls"]}}],
    })
    result = await run_phase_probe(llm, registry, "分析", "contradiction")
    # shell 不在 contradiction 允许清单 → 跳过，且不执行
    assert "不在本阶段允许清单" in result


@pytest.mark.asyncio
async def test_probe_no_tools_returns_empty(registry):
    llm = _ProbeLLM({"need_tools": False, "tool_calls": [], "reason": "材料足够"})
    result = await run_phase_probe(llm, registry, "分析", "contradiction")
    assert result == ""


@pytest.mark.asyncio
async def test_probe_practice_phase_skipped(registry):
    # practice 不走轻量探查（完整编排负责）
    llm = _ProbeLLM({"need_tools": True, "tool_calls": [{"tool": "file_read", "params": {"path": "x"}}]})
    result = await run_phase_probe(llm, registry, "分析", "practice")
    assert result == ""
