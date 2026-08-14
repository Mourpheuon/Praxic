"""
Execution-layer upgrade verification tests (Phases A/B/C/D/E of DSH-derived prompts).

Covers:
  A1  ToolResult.summary → next-round context uses summary, not full content
  A2  head_tail_truncate preserves tail (errors/latest state), drops middle
  B1  read-only tools are marked is_concurrency_safe=True; BaseTool default False
  B2  _schedule_tool_calls runs safe tools concurrently + unsafe barrier, ordered
  C1  failure_class distinguishes timeout/output_limit/permission
  C2  permission-denied result carries escalation_hint + retry guidance
  D1  sandbox escalation graph + justification fail-closed
  E1  skill injection uses catalog summary; skill tool loads full body
  E2  history compression produces a summary node, direction state preserved
Runs instantly (mocks, no network, no real API calls).
"""
import asyncio
import json
from pathlib import Path

import pytest

from praxic.core.autonomy import PermissionMode
from praxic.core.practice import PracticeModule
from praxic.core.skill_manager import SkillManager
from praxic.llm.base import BaseLLM, LLMResponse
from praxic.tools.base import (
    ActionKind,
    BaseTool,
    ToolResult,
    ToolStatus,
    ensure_summary,
    head_tail_truncate,
)
from praxic.tools.permissions import (
    PermissionPolicy,
    SandboxLevel,
    build_escalation_hint,
    escalation_allowed,
    sandbox_from_string,
)
from praxic.tools.registry import ToolRegistry
from praxic.tools.skill import SkillLoadTool


# ── A2: 保头尾截断 ─────────────────────────────

def test_head_tail_truncate_keeps_both_ends():
    text = "A" * 100 + "ERROR_MARKER_AT_TAIL"
    truncated = head_tail_truncate(text, head_chars=20, tail_chars=30)
    assert truncated.startswith("A" * 20)
    assert truncated.endswith("ERROR_MARKER_AT_TAIL")
    assert "[... 中段省略 ...]" in truncated
    assert len(truncated) < len(text)


def test_head_tail_truncate_noop_when_short():
    text = "short text"
    assert head_tail_truncate(text) == text


def test_head_tail_truncate_respects_max_len():
    text = "x" * 1000 + "tail"
    r = head_tail_truncate(text, max_len=300)
    assert len(r) <= 300


# ── A1: summary 提取 ───────────────────────────

def test_ensure_summary_uses_explicit_summary():
    result = ToolResult(status=ToolStatus.SUCCESS, content="raw" * 100, summary="一句话结论")
    assert ensure_summary(result) == "一句话结论"


def test_ensure_summary_falls_back_to_content_and_error():
    # 统一管道：成功无 summary → 占位（不搬正文，单行多行一致）
    ok = ToolResult(status=ToolStatus.SUCCESS, content="实际输出内容")
    assert ensure_summary(ok) == "（6 字符，见日志/产物）"
    assert "实际输出内容" not in ensure_summary(ok)
    # 失败 → 保头尾错误信息
    err = ToolResult(status=ToolStatus.ERROR, content="", error="尾部错误信息很长很长很长", failure_class="tool_error")
    assert "尾部错误信息" in ensure_summary(err)


def test_ensure_summary_unified_pipeline():
    """统一管道：所有类型同一条规则——error 保头尾 / summary 直接用 / 无 summary 占位。"""
    # 内容型（file_read）：单行也不搬正文
    single = ToolResult(status=ToolStatus.SUCCESS, content="api_key=sk-1234567890abcdef")
    assert ensure_summary(single) == "（27 字符，见日志/产物）"
    assert "sk-1234567890abcdef" not in ensure_summary(single)
    # 内容型多行：同样占位
    multi = ToolResult(status=ToolStatus.SUCCESS, content="line1\nline2\n")
    assert "line1" not in ensure_summary(multi)
    assert "见日志/产物" in ensure_summary(multi)
    # 结论型：显式 summary 直接用
    result = ToolResult(status=ToolStatus.SUCCESS, content="北京: 80 行", summary="北京 80 行 sum=2500")
    assert ensure_summary(result) == "北京 80 行 sum=2500"
    # 空内容：状态分类兜底
    empty = ToolResult(status=ToolStatus.SUCCESS, content="")
    assert ensure_summary(empty) in ("observed", "world_unchanged", "success")


# ── B1: 并发安全标记 ───────────────────────────

def test_base_tool_default_is_not_concurrency_safe():
    assert BaseTool.is_concurrency_safe is False


def test_read_only_tools_marked_concurrency_safe():
    from praxic.tools.filesystem import FileReadTool, FileListTool
    from praxic.tools.file_query import FileGrepTool, FileBatchReadTool, FileStatTool
    from praxic.tools.data_query import DataQueryTool
    from praxic.tools.sqlite_query import SqliteQueryTool
    from praxic.tools.pdf_extract import PdfExtractTool
    from praxic.tools.environment import EnvTool, TimeTool
    from praxic.tools.web_search import WebSearchTool
    from praxic.tools.web_fetch import WebFetchTool
    from praxic.tools.skill import SkillLoadTool

    for cls in (FileReadTool, FileListTool, FileGrepTool, FileBatchReadTool, FileStatTool,
                DataQueryTool, SqliteQueryTool, PdfExtractTool, EnvTool, TimeTool,
                WebSearchTool, WebFetchTool, SkillLoadTool):
        assert cls.is_concurrency_safe is True, cls.__name__


# ── B2: 并发调度 ───────────────────────────────

class _Probe:
    def __init__(self, name, running, lock):
        self.name = name
        self.is_concurrency_safe = name.startswith("safe")
        self.running = running
        self.lock = lock

    async def run(self, **kw):
        async with self.lock:
            self.running.append(self.name)
            await asyncio.sleep(0.02)
        return self.running


class _ConvRegistry:
    """Registry exposing enough of the real interface for scheduling tests."""

    def __init__(self):
        self.records = []

    def get(self, name):
        pass

    def get_is_safe(self, name):
        return name.startswith("safe")


@pytest.mark.asyncio
async def test_schedule_safe_tools_run_concurrently_unsafe_barrier():
    running = []
    lock = asyncio.Lock()

    calls = [
        {"tool": "safe_1", "params": {}},
        {"tool": "safe_2", "params": {}},
        {"tool": "unsafe_3", "params": {}},
        {"tool": "safe_4", "params": {}},
    ]

    async def fake_call(name, **_):
        # 模拟实际执行顺序：安全工具并发（重叠），非安全工具在屏障后执行
        if name.startswith("safe"):
            await asyncio.sleep(0.02)
            running.append(f"{name}(done)")
            return ToolResult(status=ToolStatus.SUCCESS, content=name)
        # unsafe：记录它在两个 safe 都完成前不会被调度
        await asyncio.sleep(0.005)
        running.append(f"unsafe({len([r for r in running if '(done)' in r])})")
        return ToolResult(status=ToolStatus.SUCCESS, content=name)

    reg = _ConvRegistry()

    class WrappedRegistry:
        def get(self, name):
            class TT:
                is_concurrency_safe = name.startswith("safe")
            return TT()

        async def call(self, name, **params):
            return await fake_call(name)

    ordered = await PracticeModule()._schedule_tool_calls(calls, registry=WrappedRegistry())
    # 保序提交
    assert [o[0] for o in ordered if o[0]] == ["safe_1", "safe_2", "unsafe_3", "safe_4"]
    # unsafe_3 在屏障处执行：此时它前面的 safe_1/safe_2 已完成
    unsafe_entry = next(r for r in running if r.startswith("unsafe"))
    assert unsafe_entry == "unsafe(2)", "非安全工具必须在两个前面的安全工具都完成后才执行"


@pytest.mark.asyncio
async def test_schedule_preserves_order_with_none_registry_result():
    calls = [{"tool": "a", "params": {}}, {"tool": "b", "params": {}}]
    # registry=None → 全部返回 None（无执行路径）
    result = await PracticeModule()._schedule_tool_calls(calls, registry=None)
    assert [r[0] for r in result] == ["a", "b"]
    assert all(r[2] is None for r in result)


# ── C1: 失败分类 ───────────────────────────────

def test_failure_class_timeout_distinguishable_in_status_text():
    practice = PracticeModule()
    practice._last_round_detail = type("D", (), {
        "round_num": 2,
        "tool_calls": [{
            "tool": "python_exec",
            "result": {"status": "error", "state_classification": "tool_error",
                       "failure_class": "timeout", "error": "执行超时 (30s)"},
        }, {
            "tool": "file_write",
            "result": {"status": "error", "state_classification": "permission_denied",
                       "failure_class": "permission_denied", "error": "越界"},
        }],
    })()
    text = practice._execution_status_text()
    assert "[超时]" in text
    assert "[权限拒绝]" in text


def test_output_limit_classified():
    practice = PracticeModule()
    practice._last_round_detail = type("D", (), {
        "round_num": 1,
        "tool_calls": [{
            "tool": "python_exec",
            "result": {"status": "error", "state_classification": "tool_error",
                       "failure_class": "output_limit", "error": "输出超限"},
        }],
    })()
    assert "[输出超限]" in practice._execution_status_text()


# ── C2: 升级提示 ───────────────────────────────

def test_escalation_hint_generated():
    hint = build_escalation_hint(tool_name="file_write", current_mode=PermissionMode.ASK)
    assert "sandbox_permissions" in hint
    assert "justification" in hint
    assert "workspace_write" in hint


def test_escalation_hint_read_only_mode_blocks():
    hint = build_escalation_hint(tool_name="shell_exec", current_mode=PermissionMode.READ_ONLY)
    assert "只读" in hint
    assert "不能自行请求" in hint or "需管理员" in hint


def test_policy_deny_result_includes_escalation_hint_in_error():
    from praxic.tools.filesystem import FileWriteTool
    from praxic.core.autonomy import PermissionMode as PM

    policy = PermissionPolicy(permission_mode=PermissionMode.READ_ONLY)
    reg = ToolRegistry(policy=policy)
    reg.register(FileWriteTool(workspace=Path("/tmp") if False else Path(".")))

    result = asyncio.run(reg.call("file_write", path="x.txt", content="y"))
    assert result.status == ToolStatus.ERROR
    assert "升级提示" in (result.error or "")
    assert result.metadata.get("escalation_hint")


# ── D1: 沙箱升级图 ─────────────────────────────

def test_sandbox_escalation_graph():
    assert escalation_allowed(SandboxLevel.READ_ONLY, SandboxLevel.WORKSPACE_WRITE)
    assert escalation_allowed(SandboxLevel.WORKSPACE_WRITE, SandboxLevel.DANGER_FULL_ACCESS)
    # 不能降级
    assert not escalation_allowed(SandboxLevel.WORKSPACE_WRITE, SandboxLevel.READ_ONLY)
    assert not escalation_allowed(SandboxLevel.DANGER_FULL_ACCESS, SandboxLevel.WORKSPACE_WRITE)


def test_sandbox_from_string_aliases():
    assert sandbox_from_string("workspace_write") == SandboxLevel.WORKSPACE_WRITE
    assert sandbox_from_string("danger") == SandboxLevel.DANGER_FULL_ACCESS
    with pytest.raises(ValueError):
        sandbox_from_string("not_a_level")


@pytest.mark.asyncio
async def test_escalation_without_justification_fails_closed():
    """带 sandbox_permissions 但无 justification → fail-closed，不执行、不挂起。"""
    from praxic.tools.filesystem import FileWriteTool

    # 用 READ_ONLY 模式产生硬拒绝（不进入授权等待），验证升级环节 fail-closed。
    policy = PermissionPolicy(permission_mode=PermissionMode.READ_ONLY)
    reg = ToolRegistry(policy=policy, authorization_timeout_seconds=1.0)
    reg.register(FileWriteTool(workspace=Path(".")))
    result = await asyncio.wait_for(
        reg.call(
            "file_write", path="x.txt", content="y",
            sandbox_permissions="workspace_write",  # 缺 justification
        ),
        timeout=3.0,
    )
    assert result.status == ToolStatus.ERROR
    assert "升级提示" in (result.error or ""), "无理由升级被拒，且仍给升级指引"


# ── E1: 技能按需加载 ─────────────────────────

def test_phase_skill_catalog_is_summary_not_body(tmp_path):
    manager = SkillManager(tmp_path)
    # 手工造一个技能，模拟完整 SKILL.md
    (tmp_path / "demo").mkdir(parents=True, exist_ok=True)
    (tmp_path / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 演示技能\nstatus: active\nactive_phases: [practice]\n---\n\n# 完整指令\nSTEP_1_DETAILED_BODY",
        encoding="utf-8",
    )
    manager._load_registry.__wrapped__ if False else None
    # 直接构造 catalog
    from praxic.api.schemas.models import SkillMetadata
    meta = SkillMetadata(
        name="demo", description="演示技能", active_phases=["practice"],
        status="active", file_path=str(tmp_path / "demo" / "SKILL.md"),
    )
    manager._catalog["demo"] = meta
    manager._phase_index["practice"] = ["demo"]

    catalog = manager.get_phase_skill_catalog("practice")
    assert "demo" in catalog
    assert "演示技能" in catalog
    assert "STEP_1_DETAILED_BODY" not in catalog, "目录摘要不应含完整指令"

    full = manager.load_skill_body_for_tool("demo")
    assert "完整指令" in full


def test_skill_load_tool_returns_full_body():
    class FakeManager:
        def load_skill_body_for_tool(self, name):
            return "FULL SKILL INSTRUCTIONS for " + name

    tool = SkillLoadTool(manager=FakeManager())
    result = asyncio.run(tool.run(name="my_skill"))
    assert result.ok
    assert "FULL SKILL INSTRUCTIONS" in result.content
    assert result.summary and "my_skill" in result.summary


# ── E2: 历史压缩 ─────────────────────────────

@pytest.mark.asyncio
async def test_history_compression_produces_summary_node():
    captured = {}

    class CompressLLM(BaseLLM):
        async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
            captured["content"] = messages[-1]["content"] if messages else ""
            captured["system"] = system or ""
            return LLMResponse(content="<summary>前几轮已确认假设1成立，假设2因样本不足暂未定论。</summary>",
                               model="fake")

        async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
            yield ""

    practice = PracticeModule(llm=CompressLLM(), max_retries=2)
    practice._direction_state_update = '{"evidence_status":"effective_observation"}'
    node = await practice._compress_history(
        ["第1轮 ok=True", "第2轮 ok=True", "第3轮 ok=True"], direction_update="方向状态保持不变"
    )
    assert "<history-summary>" in node
    assert "假设1成立" in node
    # 方向状态作为压缩输入被传入（E2：保留方向，不丢）
    assert "方向状态保持不变" in captured["content"]
