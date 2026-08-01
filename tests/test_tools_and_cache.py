from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from praxic.api.routes import agent as agent_routes
from praxic.api.routes.agent import _serialize_event
from praxic.api.schemas.models import CognitiveTrace
from praxic.tools.permissions import PermissionMode
from praxic.core.cognitive_loop import CognitiveLoop
from praxic.core.practice import PracticeModule
from praxic.llm.claude import ClaudeLLM
from praxic.llm.kv_cache import InMemoryPrefixKVCache, detect_kv_cache_backend
from praxic.memory.context_cache import ContextBlock, ContextCache, ContextCompiler, estimate_tokens
from praxic.memory.episodic_memory import EpisodicMemory
from praxic.memory.working_memory import WorkingMemory
from praxic.tools.base import ActionKind, BaseTool, ToolResult, ToolStatus
from praxic.tools.filesystem import FileWriteTool
from praxic.tools.permissions import PermissionPolicy
from praxic.tools.python_exec import PythonExecTool
from praxic.tools.registry import ToolRegistry
from praxic.tools.shell import ShellTool
from praxic.tools.web_search import MultiSearchTool
from praxic.tools.user_context import ReadUserContextTool


class ExternalProbeTool(BaseTool):
    name = "external_probe"
    description = "test-only external action"
    action_kind = ActionKind.EXTERNAL
    requires_authorization = True
    sandbox_safe = False
    parameter_schema = {"target": {"type": "string"}}

    def __init__(self):
        self.calls = 0

    async def run(self, target: str) -> ToolResult:
        self.calls += 1
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"contacted {target}",
            data={"target": target},
            action_kind=ActionKind.EXTERNAL,
        )


@pytest.mark.asyncio
async def test_multi_search_converts_cancelled_child_to_structured_error():
    class CancelledSearch:
        async def run(self, query: str):
            raise asyncio.CancelledError()

    results = await MultiSearchTool(CancelledSearch()).search_all(["cancelled query"])
    assert len(results) == 1
    assert results[0].status == ToolStatus.ERROR
    assert "cancelled query" in results[0].error


async def _wait_for_event(events: list[dict], event_type: str) -> dict:
    for _ in range(100):
        match = next((event for event in events if event.get("event_type") == event_type), None)
        if match:
            return match
        await asyncio.sleep(0.001)
    raise AssertionError(f"event not emitted: {event_type}")


@pytest.mark.asyncio
async def test_authorization_wait_approve_and_deny():
    events: list[dict] = []
    registry = ToolRegistry(
        policy=PermissionPolicy(permission_mode=PermissionMode.AUTO_REVIEW),
        event_sink=events.append,
        authorization_timeout_seconds=1.0,
    )
    tool = ExternalProbeTool()
    registry.register(tool)

    approved_task = asyncio.create_task(registry.call("external_probe", target="device-a"))
    requested = await _wait_for_event(events, "authorization_requested")
    request_id = requested["authorization"]["request_id"]
    assert registry.authorization_status(request_id)["status"] == "pending"
    approved = registry.approve_authorization(request_id, ttl_seconds=30)
    assert approved["status"] == "approved"
    assert registry.approve_authorization(request_id, ttl_seconds=30) is None
    assert registry.deny_authorization(request_id) is None
    result = await approved_task
    assert result.status == ToolStatus.SUCCESS
    assert tool.calls == 1
    assert result.permission is not None
    assert result.permission.authorization_id

    events.clear()
    denied_task = asyncio.create_task(registry.call("external_probe", target="device-b"))
    requested = await _wait_for_event(events, "authorization_requested")
    denied_id = requested["authorization"]["request_id"]
    denied_status = registry.deny_authorization(denied_id)
    assert denied_status["status"] == "denied"
    assert registry.deny_authorization(denied_id) is None
    denied = await denied_task
    assert denied.status == ToolStatus.ERROR
    assert denied.state_classification == "permission_denied"
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_authorization_timeout_does_not_execute():
    events: list[dict] = []
    registry = ToolRegistry(
        policy=PermissionPolicy(permission_mode=PermissionMode.AUTO_REVIEW),
        event_sink=events.append,
        authorization_timeout_seconds=0.01,
    )
    tool = ExternalProbeTool()
    registry.register(tool)
    result = await registry.call("external_probe", target="device-timeout")
    assert result.status == ToolStatus.ERROR
    assert result.failure_class == "authorization_expired"
    assert result.state_classification == "authorization_expired"
    assert tool.calls == 0
    resolved = [event for event in events if event.get("event_type") == "authorization_resolved"]
    assert len(resolved) == 1
    assert resolved[0]["authorization"]["status"] == "expired"


@pytest.mark.asyncio
async def test_authorization_cancellation_resolves_pending_request():
    events: list[dict] = []
    registry = ToolRegistry(
        policy=PermissionPolicy(permission_mode=PermissionMode.AUTO_REVIEW),
        event_sink=events.append,
        authorization_timeout_seconds=30.0,
    )
    tool = ExternalProbeTool()
    registry.register(tool)

    task = asyncio.create_task(registry.call("external_probe", target="device-cancelled"))
    requested = await _wait_for_event(events, "authorization_requested")
    request_id = requested["authorization"]["request_id"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert registry.authorization_status(request_id)["status"] == "expired"
    assert registry.pending_authorizations == []
    assert tool.calls == 0
    resolved = [event for event in events if event.get("event_type") == "authorization_resolved"]
    assert resolved[-1]["authorization"]["status"] == "expired"


@pytest.mark.asyncio
async def test_authorization_redacts_nested_parameters():
    events: list[dict] = []
    registry = ToolRegistry(
        policy=PermissionPolicy(permission_mode=PermissionMode.AUTO_REVIEW),
        event_sink=events.append,
        authorization_timeout_seconds=1.0,
    )
    registry.register(ExternalProbeTool())
    task = asyncio.create_task(
        registry.call(
            "external_probe",
            target="device-secret",
            headers={"Authorization": "Bearer secret", "X-Api-Key": "key-secret"},
            payload={"nested": {"access_token": "token-secret"}},
            args=["--token", "cli-secret", "visible"],
        )
    )
    requested = await _wait_for_event(events, "authorization_requested")
    params = requested["authorization"]["parameters"]
    assert params["headers"] == {"Authorization": "[REDACTED]", "X-Api-Key": "[REDACTED]"}
    assert params["payload"]["nested"]["access_token"] == "[REDACTED]"
    assert params["args"] == ["--token", "[REDACTED]", "visible"]
    registry.deny_authorization(requested["request_id"])
    await task


@pytest.mark.asyncio
async def test_user_context_observation_waits_for_authorization_and_hides_text():
    events: list[dict] = []
    registry = ToolRegistry(
        policy=PermissionPolicy(permission_mode=PermissionMode.AUTO_REVIEW),
        event_sink=events.append,
        authorization_timeout_seconds=1.0,
    )
    registry.register(ReadUserContextTool())

    task = asyncio.create_task(
        registry.call(
            "read_user_context",
            reason="需要判断背景是否改变实践检验条件",
            _user_context="这段背景只应在授权后出现",
        )
    )
    requested = await _wait_for_event(events, "authorization_requested")
    await asyncio.sleep(0)

    assert not task.done()
    assert requested["authorization"]["status"] == "pending"
    assert "这段背景只应在授权后出现" not in json.dumps(requested, ensure_ascii=False)

    registry.approve_authorization(requested["request_id"], ttl_seconds=30)
    result = await task
    assert result.status == ToolStatus.SUCCESS
    assert "这段背景只应在授权后出现" in result.content
    assert result.permission is not None
    assert result.permission.authorization_id
    assert "_user_context" not in registry.records[-1].parameters


@pytest.mark.asyncio
async def test_practice_executor_supplies_context_only_after_approval():
    events: list[dict] = []
    registry = ToolRegistry(
        policy=PermissionPolicy(permission_mode=PermissionMode.AUTO_REVIEW),
        event_sink=events.append,
        authorization_timeout_seconds=1.0,
    )
    registry.register(ReadUserContextTool())
    wm = WorkingMemory(session_id="practice-context")
    wm.set("context", "实践检验必须获批后才能看到的条件")
    practice = PracticeModule(llm=SimpleNamespace(), workspace=None, practice_rounds=1)

    task = asyncio.create_task(
        practice._execute_round(
            {
                "round_rationale": "确认是否需要用户补充背景",
                "tool_calls": [
                    {
                        "tool": "read_user_context",
                        "params": {"reason": "背景可能改变检验边界"},
                    }
                ],
            },
            1,
            registry=registry,
            wm=wm,
        )
    )
    requested = await _wait_for_event(events, "authorization_requested")
    assert not task.done()
    assert "实践检验必须获批后才能看到的条件" not in json.dumps(requested, ensure_ascii=False)

    registry.approve_authorization(requested["request_id"], ttl_seconds=30)
    steps, *_ = await task
    assert any("实践检验必须获批后才能看到的条件" in step.observed_result for step in steps)


def test_working_memory_hides_user_context_from_practice_prompt():
    wm = WorkingMemory(session_id="context-gate")
    wm.set("context", "只允许调查阶段自动读取的背景")
    wm.set("conversation_history", "前文中有一段必须用于比较的代码")

    assert "只允许调查阶段自动读取的背景" not in wm.get_context_for_phase("practice")
    assert "只允许调查阶段自动读取的背景" in wm.get_context_for_phase("investigation")
    assert "前文中有一段必须用于比较的代码" in wm.get_context_for_phase("practice")


def test_conversation_history_preserves_concrete_prior_code(tmp_path):
    memory = EpisodicMemory(db_path=tmp_path / "episodic.db")
    prior_code = "fn main() { println!(\"76127\"); }\nPRIOR_CODE_TAIL"
    memory.save_episode(
        session_id="previous-session",
        conversation_id="follow-up",
        question="写一段 Rust 代码计算质数和",
        summary=prior_code,
    )

    history = memory.build_conversation_context(
        conversation_id="follow-up",
        current_question="这和下面的代码哪个更好？",
    )
    loop = object.__new__(CognitiveLoop)
    final_prompt = loop._summarize_for_answer(
        "这和下面的代码哪个更好？",
        CognitiveTrace(),
        conversation_history=history,
    )

    assert "PRIOR_CODE_TAIL" in history
    assert "PRIOR_CODE_TAIL" in final_prompt


@pytest.mark.asyncio
async def test_api_returns_conflict_for_resolved_authorization(monkeypatch):
    registry = ToolRegistry(policy=PermissionPolicy(permission_mode=PermissionMode.AUTO_REVIEW))
    request = registry.policy.create_authorization_request(
        tool_name="external_probe",
        action_kind=ActionKind.EXTERNAL,
        params={"target": "device-a"},
        scope="device-a",
        reason="external side effect",
    )
    assert registry.deny_authorization(request.request_id)["status"] == "denied"
    monkeypatch.setattr(agent_routes, "_find_registry", lambda request_id, project_id="": registry)

    with pytest.raises(HTTPException) as exc_info:
        await agent_routes.resolve_authorization(
            request.request_id,
            agent_routes.AuthorizationResolutionRequest(action="approve"),
        )
    assert exc_info.value.status_code == 409


def test_authorization_ttl_must_be_positive():
    with pytest.raises(ValueError):
        agent_routes.AuthorizationResolutionRequest(action="approve", ttl_seconds=0)
    with pytest.raises(ValueError):
        PermissionPolicy().issue_grant(ttl_seconds=0)


@pytest.mark.asyncio
async def test_file_change_records_and_readback(tmp_path):
    registry = ToolRegistry(
        policy=PermissionPolicy(
            permission_mode=PermissionMode.AUTO_REVIEW,
            allowed_roots=(tmp_path,),
        )
    )
    registry.register(FileWriteTool(tmp_path))

    first = await registry.call("file_write", path="state.txt", content="v1")
    assert first.status == ToolStatus.SUCCESS
    assert first.world_changed is True
    assert first.verification is not None and first.verification.ok
    assert first.change is not None and first.change.before_digest != first.change.after_digest

    same = await registry.call("file_write", path="state.txt", content="v1")
    assert same.status == ToolStatus.SUCCESS
    assert same.world_changed is False
    assert same.state_classification == "world_unchanged"
    assert same.verification is not None and same.verification.ok


@pytest.mark.asyncio
async def test_shell_rejects_shell_composition(tmp_path):
    registry = ToolRegistry(
        policy=PermissionPolicy(allowed_roots=(tmp_path,)),
    )
    registry.register(ShellTool(allowed_roots=(tmp_path,)))
    result = await registry.call("shell_exec", command="echo safe && whoami", cwd=str(tmp_path))
    assert result.status == ToolStatus.ERROR
    assert "shell" in result.error.lower() or "控制" in result.error


@pytest.mark.asyncio
async def test_shell_interpreters_require_external_action_and_do_not_claim_change(tmp_path):
    script = tmp_path / "probe.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    tool = ShellTool(allowed_roots=(tmp_path,))
    params = {"command": ["python", "probe.py"], "cwd": str(tmp_path)}
    assert tool.classify_action(params) == ActionKind.EXTERNAL

    result = await tool.run(**params)
    result.verification = await tool.verify(params, result)
    assert result.status == ToolStatus.SUCCESS
    assert result.world_changed is None
    assert result.state_classification == "change_unverified"
    assert result.verification.status.value == "skipped"

    blocked = await tool.run(command=["python", "-c", "print('unsafe')"], cwd=str(tmp_path))
    assert blocked.status == ToolStatus.ERROR
    assert "python_exec" in blocked.error


def test_shell_treats_only_explicit_git_read_commands_as_observation(tmp_path):
    tool = ShellTool(allowed_roots=(tmp_path,))
    assert tool.classify_action({"command": ["git", "status"]}) == ActionKind.OBSERVE
    assert (
        tool.classify_action({"command": ["git", "-C", str(tmp_path), "log", "-1"]})
        == ActionKind.OBSERVE
    )
    assert (
        tool.classify_action({"command": ["git", "branch", "-D", "topic"]}) == ActionKind.EXTERNAL
    )
    assert tool.classify_action({"command": ["git", "switch", "main"]}) == ActionKind.EXTERNAL
    assert (
        tool.classify_action({"command": ["git", "log", "--output=history.txt"]})
        == ActionKind.EXTERNAL
    )


@pytest.mark.asyncio
async def test_python_exec_blocks_world_side_effects(tmp_path):
    tool = PythonExecTool(workspace_dir=tmp_path)
    assert tool.classify_action({"requirements": ["example-package"]}) == ActionKind.EXTERNAL
    result = await tool.run("open('escaped.txt', 'w').write('secret')")
    assert result.status == ToolStatus.ERROR
    assert "禁止调用" in result.error
    assert not (tmp_path / "escaped.txt").exists()

    aliased = await tool.run("writer = open\nwriter('escaped.txt', 'w')")
    assert aliased.status == ToolStatus.ERROR
    assert "禁止引用 open" in aliased.error

    dynamic_import = await tool.run("import importlib\nprint(importlib.import_module('os'))")
    assert dynamic_import.status == ToolStatus.ERROR
    assert "禁止 import importlib" in dynamic_import.error

    safe_compute = await tool.run(
        "import math\nif __name__ == '__main__':\n    print(math.sqrt(9))"
    )
    assert safe_compute.status == ToolStatus.SUCCESS
    assert safe_compute.content.strip() == "3.0"

    dependency = await tool.run("print('unused')", requirements=["requests"])
    assert dependency.status == ToolStatus.ERROR
    assert dependency.action_kind == ActionKind.EXTERNAL
    assert "relaxed_sandbox" in dependency.error


@pytest.mark.asyncio
async def test_legacy_python_command_routes_to_python_exec():
    practice = object.__new__(PracticeModule)

    async def generate_file_content(path, purpose, plan):
        return "print(1060)\n"

    practice._generate_file_content = generate_file_content
    calls = await practice._normalise_tool_calls(
        {
            "files_to_create": [{"path": "primes.py", "purpose": "sum primes"}],
            "commands_to_run": [{"cmd": "python primes.py", "timeout_seconds": 15}],
        }
    )
    assert [call["tool"] for call in calls] == ["file_write", "python_exec"]
    assert calls[1]["params"] == {"code": "print(1060)\n", "timeout_seconds": 15}


@pytest.mark.asyncio
async def test_unverified_side_effect_invalidates_context_cache():
    class RegistryProbe:
        records = []

        async def call(self, name, **params):
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content="command completed",
                action_kind=ActionKind.EXTERNAL,
            )

    class MemoryProbe:
        def __init__(self):
            self.reasons = []

        def invalidate_context(self, reason):
            self.reasons.append(reason)

    practice = object.__new__(PracticeModule)
    memory = MemoryProbe()
    result = await practice._execute_round(
        {"tool_calls": [{"tool": "external_probe", "params": {}}]},
        round_num=1,
        registry=RegistryProbe(),
        wm=memory,
    )
    assert memory.reasons == ["world_state_may_have_changed:external_probe"]
    assert result[6] is False
    assert result[7].failure_class == "change_unverified"


def test_context_and_kv_cache_are_isolated_and_invalidated():
    kv = InMemoryPrefixKVCache(max_entries=8)
    compiler = ContextCompiler(ContextCache(), kv_backend=kv)
    blocks = [
        ContextBlock("stable", "同一稳定前缀"),
        ContextBlock("live", "当前状态", stable=False),
    ]
    first = compiler.compile(blocks, session_id="s1", project_id="p1", model="m1")
    assert first.cache_hit is False
    assert first.kv_cache_hit is False

    # A new application cache can recover the compiled prefix from the local KV backend.
    recovered = ContextCompiler(ContextCache(), kv_backend=kv).compile(
        blocks, session_id="s1", project_id="p1", model="m1"
    )
    assert recovered.cache_hit is True
    assert recovered.kv_cache_hit is True
    assert recovered.stable_prefix_tokens == first.stable_prefix_tokens

    isolated = ContextCompiler(ContextCache(), kv_backend=kv).compile(
        blocks, session_id="s2", project_id="p1", model="m1"
    )
    assert isolated.kv_cache_hit is False

    removed = compiler.invalidate_scope(session_id="s1", project_id="p1")
    assert removed == 1
    assert detect_kv_cache_backend("none").capabilities.available is False
    assert kv.stats()["entries"] == 1


def test_context_cache_isolates_budgets_and_tracks_only_contiguous_stable_prefix():
    compiler = ContextCompiler(ContextCache(), kv_backend=InMemoryPrefixKVCache(max_entries=8))
    long_blocks = [ContextBlock("long", "alpha " * 100)]
    small = compiler.compile(long_blocks, session_id="s", model="m", token_budget=12)
    large = compiler.compile(long_blocks, session_id="s", model="m", token_budget=200)

    assert small.key != large.key
    assert small.token_count <= 12
    assert len(small.content) < len(large.content)
    assert large.cache_hit is False

    mixed = compiler.compile(
        [
            ContextBlock("stable", "immutable"),
            ContextBlock("live", "changing", stable=False),
            ContextBlock("late", "stable but not a prefix"),
        ],
        session_id="prefix",
        model="m",
    )
    assert mixed.stable_prefix_tokens == estimate_tokens("## stable\nimmutable")

    cached = compiler.compile(
        [ContextBlock("stable", "immutable")],
        session_id="metric",
        model="m",
    )
    compiler.compile([ContextBlock("stable", "immutable")], session_id="metric", model="m")
    metrics = compiler.cache_report()["context"]
    assert cached.stable_prefix_tokens > 0
    assert metrics["assembly_tokens_reused"] == cached.stable_prefix_tokens
    assert metrics["tokens_saved"] == 0
    assert metrics["token_savings_verified"] is False


@pytest.mark.asyncio
async def test_claude_marks_system_prompt_for_provider_cache_by_default():
    class Messages:
        def __init__(self):
            self.params = None

        async def create(self, **params):
            self.params = params
            return SimpleNamespace(
                content=[SimpleNamespace(text="ok")],
                model="claude-test",
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=1,
                    cache_read_input_tokens=8,
                    cache_creation_input_tokens=0,
                ),
                stop_reason="end_turn",
            )

    messages_api = Messages()
    llm = object.__new__(ClaudeLLM)
    llm._client = SimpleNamespace(messages=messages_api)
    llm.default_model = "claude-test"
    response = await llm.call([{"role": "user", "content": "hello"}], system="stable system")

    assert messages_api.params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert response.cache_hit is True
    assert llm.cache_stats()["cache_read_tokens"] == 8


def test_tool_contracts_are_structured_and_describable():
    tool = ExternalProbeTool()
    registry = ToolRegistry()
    registry.register(tool)
    descriptions = registry.tool_descriptions()
    assert descriptions[0]["action_kind"] == ActionKind.EXTERNAL.value
    assert descriptions[0]["parameters"]["target"]["type"] == "string"


def test_authorization_activity_serializes_for_sse():
    authorization = {
        "request_id": "auth-123",
        "tool_name": "external_probe",
        "action_kind": "external",
        "parameters": {"target": "device-a"},
        "reason": "external side effect",
        "scope": "device-a",
        "status": "pending",
    }
    line = _serialize_event(
        {
            "type": "activity",
            "event_type": "authorization_requested",
            "phase": "practice",
            "summary": "external_probe waiting for authorization",
            "data": {"authorization": authorization},
        }
    )

    assert line is not None and line.startswith("data: ") and line.endswith("\n\n")
    payload = json.loads(line.removeprefix("data: "))
    assert payload["type"] == "activity"
    assert payload["event_type"] == "authorization_requested"
    assert payload["phase"] == "practice"
    assert payload["data"]["authorization"] == authorization
