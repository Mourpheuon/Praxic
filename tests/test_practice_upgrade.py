"""
Practice phase upgrade verification tests.

Covers the L1/L2 + direction-anchor refactor of the practice phase:
  1. Planner retry after invalid JSON, with error feedback injected into retry call
  2. response_format (JSON mode) graceful degradation to plain text
  3. Direction anchor + dynamic tool-list injection (shell_exec visible)
  4. code_ref → generated code → execution (plan/code decoupling)
  5. Persistent planning failure → epistemic analysis (V2) degrade, no empty rounds
Runs instantly (no real API calls, no network).
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from praxic.llm.base import BaseLLM, LLMResponse
from praxic.core.practice import PracticeModule
from praxic.tools.filesystem import WorkspaceToolkit
from praxic.api.schemas.models import (
    CognitiveTrace,
    FactReport,
    Fact,
    InformationGap,
    RationalSynthesis,
    ContradictionGraph,
    Contradiction,
    PracticeRound,
)


class FakeLLM(BaseLLM):
    """Programmable fake: returns canned responses by mode."""

    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = []
        self.system_prompts = []

    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        user = messages[-1]["content"] if messages else ""
        self.calls.append({"user": user[:60], "kwargs_keys": list(kwargs.keys())})
        self.system_prompts.append(system or "")
        response_format = kwargs.get("response_format")

        # Retry path: first call returns prose, second returns a valid plan.
        if self.mode == "retry_once":
            if len(self.calls) == 1:
                return LLMResponse(content="这不是 JSON，我在解释我要做什么……", model="fake")
            return self._valid_plan()

        # JSON-mode degrade path: provider rejects response_format, then succeeds.
        if self.mode == "json_mode_unsupported":
            if response_format:
                raise Exception("Unsupported parameter: response_format is not supported")
            return self._valid_plan()

        # Persistent failure path: analysis calls succeed, planner calls never do.
        if self.mode == "always_bad":
            if any(k in user for k in ("知性评估", "综合分析", "知性分析")):
                return LLMResponse(
                    content=json.dumps({
                        "verdict": "inconclusive",
                        "analysis": "规划持续失败，转入知性分析：现有证据不足以判定。",
                        "claim_assessments": [],
                        "surprises": [],
                    }, ensure_ascii=False),
                    model="fake",
                )
            return LLMResponse(content="完全无法解析的内容 ###", model="fake")

        # Code generation request.
        if "为文件" in user or "生成代码" in user:
            return LLMResponse(
                content="import json\nprint(json.dumps({'status': 'ok', 'data': {'v': 42}}))",
                model="fake",
            )
        return self._valid_plan()

    def _valid_plan(self):
        return LLMResponse(
            content=json.dumps({
                "round_rationale": "先用最小模拟验证假设1",
                "epistemic_role": "verification",
                "directional_claim": "检验假设1：故障定位误差应随轮次下降",
                "deviation_rationale": "",
                "testable_claims": [
                    {"claim": "假设1", "if_true": "误差下降", "if_false": "误差不降"}
                ],
                "tool_calls": [
                    {
                        "tool": "python_exec",
                        "params": {
                            "code_ref": "模拟零样本故障定位并计算均方误差",
                            "timeout_seconds": 30,
                        },
                    }
                ],
                "expected_outcomes": ["得到误差数值"],
            }, ensure_ascii=False),
            model="fake",
        )

    async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        yield ""


def build_trace() -> CognitiveTrace:
    trace = CognitiveTrace()
    trace.investigation = FactReport(
        facts=[Fact(
            content="零样本场景下模型缺乏训练样本，泛化依赖先验结构",
            credibility=0.9,
        )],
        gaps=[InformationGap(description="误差下降斜率数据缺失", importance="high")],
    )
    trace.contradictions = ContradictionGraph(
        principal_contradiction=Contradiction(
            description="先验结构约束与样本不足之间的矛盾",
            tension_poles=["先验约束", "样本稀缺"],
        ),
    )
    trace.rational_synthesis = RationalSynthesis(
        essence="误差下降斜率可检验先验结构的有效性",
        hypotheses=[
            "假设1：先验结构能降低误差",
            "假设2：移除数值否决权会增大后验方差",
        ],
        synthesis_text="综合判断：假设1 可先行验证",
    )
    return trace


@pytest.fixture
def practice(tmp_path) -> PracticeModule:
    ws = WorkspaceToolkit(workspace_dir=str(tmp_path))
    return PracticeModule(llm=FakeLLM("ok"), workspace=ws, practice_rounds=1)


@pytest.fixture
def registry(practice):
    return practice._get_fallback_registry()


class TestPlannerRetry:
    async def test_retry_after_invalid_json(self, tmp_path):
        """First call returns non-JSON → second call succeeds with error feedback."""
        fake = FakeLLM("retry_once")
        practice = PracticeModule(
            llm=fake, workspace=WorkspaceToolkit(workspace_dir=str(tmp_path)),
            practice_rounds=1,
        )
        plan = await practice._plan_round1(
            "测试问题", build_trace(), wm=None,
            registry=practice._get_fallback_registry(),
        )
        assert not plan.get("plan_failed"), "重试后应成功"
        assert plan.get("directional_claim"), "方向字段应存在"
        assert len(fake.calls) >= 2, "应发生重试"
        assert "上一次规划被拒绝" in fake.calls[1]["user"], "第二次调用应包含错误反馈"

    async def test_retry_exhaustion_marks_plan_failed(self):
        """Persistent invalid output → plan_failed marker, no crash."""
        fake = FakeLLM("always_bad")
        practice = PracticeModule(
            llm=fake, practice_rounds=1, max_retries=2,
        )
        plan = await practice._plan_round1(
            "测试问题", build_trace(), wm=None,
            registry=practice._get_fallback_registry(),
        )
        assert plan.get("plan_failed") is True
        assert "规划在 2 次尝试后仍失败" in plan.get("round_rationale", "")


class TestJsonModeDegrade:
    async def test_response_format_unsupported_falls_back_to_text(self, tmp_path):
        fake = FakeLLM("json_mode_unsupported")
        practice = PracticeModule(
            llm=fake, workspace=WorkspaceToolkit(workspace_dir=str(tmp_path)),
            practice_rounds=1,
        )
        plan = await practice._plan_round1(
            "测试问题", build_trace(), wm=None,
            registry=practice._get_fallback_registry(),
        )
        assert not plan.get("plan_failed"), "降级后应成功"
        assert "response_format" in fake.calls[0]["kwargs_keys"], "首次调用应带 response_format"
        assert "response_format" not in fake.calls[1]["kwargs_keys"], "降级后不应带 response_format"


class TestAnchorAndTools:
    async def test_direction_anchor_and_tools_injected(self, tmp_path):
        fake = FakeLLM("ok")
        practice = PracticeModule(
            llm=fake, workspace=WorkspaceToolkit(workspace_dir=str(tmp_path)),
            practice_rounds=1,
        )
        registry = practice._get_fallback_registry()
        await practice._plan_round1("测试问题", build_trace(), wm=None, registry=registry)
        sys_prompt = fake.system_prompts[0]
        assert "主要矛盾" in sys_prompt, "锚点应包含主要矛盾"
        assert "核心假设" in sys_prompt, "锚点应包含核心假设"
        assert "{tools_text}" not in sys_prompt, "工具占位符应被替换"
        assert "shell_exec" in sys_prompt, "动态工具清单应暴露 shell_exec"
        assert "epistemic_role" in sys_prompt, "认识论定位说明应在提示词中"
        assert "抓主要矛盾" in sys_prompt, "方法论约束应在提示词中"
        assert "证伪" in sys_prompt, "技术失败≠证伪 约束应在提示词中"

    async def test_dynamic_tools_used_by_registry(self, practice, registry):
        """The tools text must be generated by the registry, not hardcoded."""
        tools_text = practice._build_tools_text(registry)
        assert "shell_exec" in tools_text
        assert "python_exec" in tools_text
        assert "read_user_context" in tools_text


class TestDirectionState:
    def test_c5_persists_structured_evidence_for_next_round(self):
        practice = object.__new__(PracticeModule)
        practice._current_wm = None
        detail = PracticeRound(tool_calls=[{
            "tool": "python_exec",
            "result": {
                "ok": True,
                "state_classification": "observed",
                "content": "误差从 0.42 降到 0.18",
            },
        }])

        state = practice._update_direction_state(
            {
                "epistemic_role": "verification",
                "directional_claim": "先验结构能降低误差",
            },
            ["observed python_exec"],
            [],
            round_num=1,
            detail=detail,
        )

        assert state.evidence_status == "effective_observation"
        assert state.effective_observations[0].startswith("python_exec [observed]")
        assert practice._direction_state == state
        context = practice._build_next_round_context(2, "测试问题", build_trace(), [], [])
        assert '"evidence_status": "effective_observation"' in context["direction_anchor"]

    def test_legacy_direction_fields_are_soft_validated(self):
        practice = object.__new__(PracticeModule)
        plan = {
            "files_to_create": [{"path": "result.txt", "purpose": "记录结果"}],
            "commands_to_run": [],
        }

        with patch("praxic.core.practice.log.warning") as warning:
            assert practice._validate_plan_schema(plan) == []
            warning.assert_called_once()
            assert warning.call_args.args[0] == "practice.legacy_plan_missing_direction_fields"

        practice._default_direction_fields(plan)
        assert plan["epistemic_role"] == "exploration"
        assert plan["directional_claim"] == ""
        assert plan["deviation_rationale"] == ""


class TestPlanDeviation:
    def _record(self, tool, status="success", classification="observed", error=""):
        return {"tool": tool, "result": {"status": status, "state_classification": classification, "error": error}}

    def test_planned_but_not_executed_flagged(self):
        practice = PracticeModule()
        practice._last_round_plan = {
            "tool_calls": [
                {"tool": "file_read", "params": {"path": "a.txt"}},
                {"tool": "web_search", "params": {"query": "y"}},
            ]
        }
        practice._last_round_detail = type("D", (), {
            "round_num": 1,
            "tool_calls": [self._record("file_read")],
        })()
        text = practice._execution_status_text()
        assert "[成功] file_read" in text
        assert "计划偏差" in text
        assert "web_search" in text and "未执行" in text

    def test_no_deviation_when_all_executed(self):
        practice = PracticeModule()
        practice._last_round_plan = {
            "tool_calls": [{"tool": "file_read", "params": {"path": "a.txt"}}]
        }
        practice._last_round_detail = type("D", (), {
            "round_num": 1,
            "tool_calls": [self._record("file_read")],
        })()
        text = practice._execution_status_text()
        assert "计划偏差" not in text

    def test_technical_failure_tagged(self):
        practice = PracticeModule()
        practice._last_round_detail = type("D", (), {
            "round_num": 1,
            "tool_calls": [self._record("python_exec", status="error", classification="tool_error", error="语法错误")],
        })()
        text = practice._execution_status_text()
        assert "[技术中断] python_exec" in text


class TestCodeRefDecoupling:
    async def test_code_ref_generated_before_execution(self, tmp_path):
        fake = FakeLLM("ok")
        practice = PracticeModule(
            llm=fake, workspace=WorkspaceToolkit(workspace_dir=str(tmp_path)),
            practice_rounds=1,
        )
        registry = practice._get_fallback_registry()
        plan = await practice._plan_round1("测试问题", build_trace(), wm=None, registry=registry)
        calls = await practice._normalise_tool_calls(plan)
        assert calls and calls[0]["tool"] == "python_exec"
        assert "code" in calls[0]["params"], "应生成实际代码"
        assert "code_ref" not in calls[0]["params"], "code_ref 应被替换"
        assert "import json" in calls[0]["params"]["code"], "代码应经生成器产出"


class TestEpistemicDegrade:
    async def test_persistent_plan_failure_degrades_to_v2(self, tmp_path):
        fake = FakeLLM("always_bad")
        practice = PracticeModule(
            llm=fake, workspace=WorkspaceToolkit(workspace_dir=str(tmp_path)),
            practice_rounds=3, max_retries=2,
        )
        registry = practice._get_fallback_registry()
        report = await practice.practice("测试问题", build_trace(), registry=registry)
        assert report.mode in ("partial", "epistemic_only"), "应降级为知性分析"
        assert report.confidence_ceiling == "V2", "可信度上限应为 V2"
        assert len(report.rounds) == 0, "不应空跑三轮"
        assert report.world_changed is False
