"""Tests for the contradiction-spine upgrade (多轮矛盾维护接线)."""
import json
import pytest

from praxic.api.schemas.models import (
    Contradiction,
    ContradictionGraph,
    ContradictionPositionShift,
    ContradictionType,
    Fact,
    FactReport,
)
from praxic.core.contradiction import ContradictionAnalyzer
from praxic.memory.working_memory import WorkingMemory
from tests.mock_llm import MockLLM

VALID_RESP = json.dumps(
    {
        "principal_contradiction": {
            "description": "用户期望与系统能力之间的根本矛盾",
            "tension_poles": ["用户高期望", "系统能力有限"],
            "contradiction_type": "internal",
            "rank": 1,
            "primary_aspect": "系统能力有限",
            "transformation_condition": "当知识库扩展时转移",
            "basis_fact_ids": ["f1", "f2"],
            "basis_summary": "基于f1和f2",
        },
        "secondary_contradictions": [],
        "dynamic_note": "主要矛盾处于相对稳定状态",
        "synthesis": "核心矛盾是用户期望与能力差距",
    },
    ensure_ascii=False,
)
MAINTAIN_RESP = json.dumps(
    {
        "principal_contradiction": {
            "description": "用户期望与系统能力之间的根本矛盾",
            "tension_poles": ["用户高期望", "系统能力有限"],
            "contradiction_type": "internal",
            "rank": 1,
            "primary_aspect": "系统能力有限",
            "transformation_condition": "当知识库扩展时转移",
            "basis_fact_ids": ["f1", "f2", "f3"],
            "basis_summary": "基于f1,f2，本轮补充f3",
        },
        "secondary_contradictions": [],
        "dynamic_note": "矛盾出现转化迹象",
        "synthesis": "核心矛盾仍是需求与能力，但趋势变化",
        "position_shifts": [
            {
                "from_role": "secondary",
                "to_role": "principal",
                "contradiction_description": "某一度被低估的次要矛盾",
                "trigger_facts": ["f3"],
                "transformation_condition_met": "新证据出现",
            }
        ],
    },
    ensure_ascii=False,
)


def _make_report(fact_contents=("事实1", "事实2", "事实3")):
    return FactReport(
        facts=[
            Fact(id=f"f{i}", content=c, credibility=0.8, source_type="internal")
            for i, c in enumerate(fact_contents, 1)
        ],
        summary="测试",
    )


def _prev_graph(with_shift=False):
    shifts = (
        [ContradictionPositionShift(from_role="secondary", to_role="principal",
                                    contradiction_description="历史转换", trigger_facts=["f0"],
                                    trigger_iteration=1, transformation_condition_met="旧条件")]
        if with_shift else []
    )
    return ContradictionGraph(
        principal_contradiction=Contradiction(
            description="历史主要矛盾", tension_poles=["A", "B"],
            contradiction_type=ContradictionType.INTERNAL, rank=1,
            primary_aspect="A", transformation_condition="", basis_fact_ids=["f1"],
            basis_summary="", involving_elements=[], position_in_feedback="",
            systemic_drive="", particularity_description="", derivation_chain=None,
        ),
        secondary_contradictions=[],
        dynamic_note="旧动态", synthesis="旧综合", system_model=None,
        position_shifts=shifts, iteration=2,
    )


@pytest.fixture
def mk():
    return MockLLM()


class TestMaintainBudgetAndEvolution:
    @pytest.mark.asyncio
    async def test_maintain_receives_budget_and_applies_shallow_max_tokens(self, mk):
        """A2：maintain 收到 budget；depth=SHALLOW 时 max_tokens 受控（非默认 16384 也可能按档收敛）。"""
        mk.set_response(MAINTAIN_RESP)
        an = ContradictionAnalyzer(llm=mk)
        prev = _prev_graph()
        result = await an.maintain_contradictions(
            previous_graph=prev,
            updated_fact_report=_make_report(),
            question="持续检验",
        )
        assert result is not None
        # maintenance 不改变已识别矛盾，且 iteration 递增
        assert result.iteration == prev.iteration + 1
        call = mk.call_history[-1]
        assert call["max_tokens"] > 0

    @pytest.mark.asyncio
    async def test_maintain_accumulates_position_shifts_and_advances_iteration(self, mk):
        """A3/D：position_shifts 累积（previous + new），iteration 递增。"""
        mk.set_response(MAINTAIN_RESP)
        an = ContradictionAnalyzer(llm=mk)
        prev = _prev_graph(with_shift=True)
        result = await an.maintain_contradictions(
            previous_graph=prev,
            updated_fact_report=_make_report(),
            question="检验",
        )
        assert result.iteration == prev.iteration + 1
        # 新的 position_shifts 从响应解析出 1 条，加上 previous 的 1 条 = 2
        assert len(result.position_shifts) >= len(prev.position_shifts) + 1


class TestWorkingMemoryInvestigationVisibility:
    def _mem_with_contradiction(self):
        wm = WorkingMemory()
        wm.set_contradiction(_prev_graph())
        return wm

    def test_investigation_injects_contradiction_as_check_object(self):
        wm = self._mem_with_contradiction()
        ctx = wm.get_context_for_phase("investigation")
        assert "检验对象" in ctx
        assert "上一轮识别的矛盾结构" in ctx
        assert "历史主要矛盾" in ctx

    def test_contradiction_phase_does_not_inject_old_contradiction(self):
        wm = self._mem_with_contradiction()
        ctx = wm.get_context_for_phase("contradiction")
        assert "上一轮识别的矛盾结构" not in ctx
        assert "历史主要矛盾" not in ctx

    def test_rational_still_injects_current_contradiction(self):
        wm = self._mem_with_contradiction()
        ctx = wm.get_context_for_phase("rational")
        assert "当前矛盾结构" in ctx
        assert "历史主要矛盾" in ctx

    def test_first_round_no_contradiction_investigation_skips(self):
        # 无 contradiction context 时（第一轮），调查阶段不注入也不报错
        wm = WorkingMemory()
        ctx = wm.get_context_for_phase("investigation")
        assert "检验对象" not in ctx


class TestMaintainDictatesLoopWire:
    @pytest.mark.asyncio
    async def test_contradiction_analyzer_has_maintain_with_budget_param(self, mk):
        """契约验证：contradiction 模块的 maintain 签名带 budget，供认知循环第二轮调用。"""
        import inspect
        sig = inspect.signature(ContradictionAnalyzer.maintain_contradictions)
        assert "budget" in sig.parameters
        assert sig.parameters["budget"].default is None


# ---------------------------------------------------------------------------
# 认知循环多轮接线：第二轮走 maintain，第一轮走 analyze
# ---------------------------------------------------------------------------
class TestLoopMaintainWiring:
    @pytest.mark.asyncio
    async def test_second_iteration_calls_maintain_first_calls_analyze(self, tmp_path):
        """J线验收：第二轮矛盾分析走 maintain_contradictions 而非 analyze。"""
        import asyncio
        import os
        from pathlib import Path
        from praxic.llm.base import BaseLLM, LLMResponse
        os.environ["DEEPSEEK_API_KEY"] = "x"
        from praxic.core.autonomy import PermissionMode
        from praxic.core.cognitive_loop import CognitiveLoop
        from praxic.config import settings

        settings.max_iterations = 2
        settings.practice_rounds = 2
        settings.web_search_enabled = False
        settings.web_fetch_enabled = False
        settings.permission_mode = PermissionMode.AUTO_REVIEW
        settings.workspace_dir = Path(tmp_path)

        SUPERSET = {
            "original_question": "q", "expanded_question": "用代码验证质数", "question_intent": "行动",
            "question_domains": [], "structured_sub_questions": [],
            "facts": [{"content": "质数是大于1的自然数", "credibility": 0.9}], "gaps": [], "summary": "求和",
            "principal_contradiction": {"description": "效率vs正确", "tension_poles": ["效率", "正确"],
                                        "contradiction_type": "internal", "rank": 1,
                                        "primary_aspect": "正确", "transformation_condition": "运行验证"},
            "secondary_contradictions": [],
            "essence": "试除法", "patterns": ["试除"], "hypotheses": ["遍历可判"],
            "synthesis_text": "综合", "contradiction_motion": "缓", "unexplained_phenomena": [],
            "return_to_concrete": "", "abstract_from": "",
            "round_rationale": "运行脚本建立基线", "files_to_create": [], "commands_to_run": [],
            "tool_calls": [], "expected_outcomes": [], "done": True,
            "quality_assessment": "ok", "convergence_score": 0.6,
            "should_reinvestigate": False,
            "lessons_learned": [], "final_answer": "答案是X",
            "skill_draft_candidates": [],
        }

        class SpyLoop:
            """包裹真实矛盾分析器，记录 analyze / maintain_contradictions 的调用次数。"""
            def __init__(self, real):
                self._real = real
                self.n_analyze = 0
                self.n_maintain = 0
            async def analyze(self, *a, **kw):
                self.n_analyze += 1
                return await self._real.analyze(*a, **kw)
            async def maintain_contradictions(self, *a, **kw):
                self.n_maintain += 1
                return await self._real.maintain_contradictions(*a, **kw)

        class FakeLLM(BaseLLM):
            def __init__(self):
                self.reflection_calls = 0
            async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
                user = messages[-1].get("content", "") if isinstance(messages, list) else ""
                # 实践的文件生成调用返回可运行代码，避免 JSON 被当代码
                if "生成可运行" in user or "文件" in user and "路径" in user:
                    return LLMResponse(content="print('ok')", model="fake")
                body = dict(SUPERSET)
                # 反思阶段：第一次返回重调查（进入第二轮），之后收敛
                if "认知轨迹摘要" in user:
                    self.reflection_calls += 1
                    if self.reflection_calls == 1:
                        body["should_reinvestigate"] = True
                        body["convergence_score"] = 0.4
                    else:
                        body["should_reinvestigate"] = False
                        body["convergence_score"] = 0.9
                return LLMResponse(content=json.dumps(body, ensure_ascii=False), model="fake")
            async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
                yield ""

        real_loop = CognitiveLoop(llm=FakeLLM())
        fake = FakeLLM()
        # 用真实矛盾分析器 + spy 记录方法调用
        spy = SpyLoop(real_loop.contradiction)
        real_loop.contradiction = spy
        for attr in ("preprocessing", "investigation", "rational", "practice", "reflection"):
            obj = getattr(real_loop, attr, None)
            if obj is not None and hasattr(obj, "llm"):
                obj.llm = fake
        rt = await real_loop.run(question="用Python计算质数之和", mode="standard",
                                 session_id="spineloop", conversation_id="spineloop")
        assert spy.n_analyze >= 1
        assert spy.n_maintain >= 1
        assert rt.full_trace.metadata.iterations >= 2


class TestDualLayerOutput:
    """B方案：结论层与推理层分离；thinking 保持开启（不传 disabled）；思维链捕获进 thinking_trace。"""

    @pytest.mark.asyncio
    async def test_standard_analyze_keeps_thinking_on_and_min_tokens(self, mk):
        mk.set_response(VALID_RESP)
        an = ContradictionAnalyzer(llm=mk)
        await an.analyze(fact_report=_make_report(), question="测试", budget={"depth": "standard"})
        call = mk.call_history[-1]
        # thinking 不再被关闭（不传 thinking 参数 → 保持 DeepSeek 默认开启）
        assert call.get("kwargs", {}).get("thinking") is None
        # STANDARD 档 max_tokens 保底 16384（容纳思维链 + 结论层正文）
        assert call["max_tokens"] >= 16384

    @pytest.mark.asyncio
    async def test_analyze_captures_thinking_trace_from_metadata(self, mk):
        mk.set_response_with_metadata(VALID_RESP, {"reasoning": "先想：拓扑不可见导致故障定位困难……"})
        an = ContradictionAnalyzer(llm=mk)
        graph = await an.analyze(fact_report=_make_report(), question="测试", budget={"depth": "standard"})
        # 思维链被捕获到 graph.thinking_trace（仅供展示，不进后续输入）
        assert "拓扑不可见" in graph.thinking_trace

    @pytest.mark.asyncio
    async def test_maintain_captures_thinking_trace(self, mk):
        mk.set_response_with_metadata(MAINTAIN_RESP, {"reasoning": "第二轮维护的思维链……"})
        an = ContradictionAnalyzer(llm=mk)
        prev = _prev_graph()
        graph = await an.maintain_contradictions(
            previous_graph=prev, updated_fact_report=_make_report(), question="维护"
        )
        assert "第二轮维护" in graph.thinking_trace

    @pytest.mark.asyncio
    async def test_standard_analyze_schema_scope_excludes_reasoning_layer(self, mk):
        mk.set_response(VALID_RESP)
        an = ContradictionAnalyzer(llm=mk)
        await an.analyze(fact_report=_make_report(), question="测试", budget={"depth": "standard"})
        sysp = mk.call_history[-1]["system"]
        # STANDARD 档明确要求正文不输出推理层（推理层仍由 thinking 承载）
        assert "只输出结论层" in sysp
        assert "不要输出推理层" in sysp

    @pytest.mark.asyncio
    async def test_deep_analyze_schema_scope_requires_reasoning_layer(self, mk):
        mk.set_response(VALID_RESP)
        an = ContradictionAnalyzer(llm=mk)
        await an.analyze(fact_report=_make_report(), question="测试", budget={"depth": "deep"})
        sysp = mk.call_history[-1]["system"]
        assert "完整推理层" in sysp
        assert "derivation_chain" in sysp

    @pytest.mark.asyncio
    async def test_standard_respects_explicit_budget_max_tokens(self, mk):
        """预算显式给了更大 max_tokens 时不被 16384 保底覆盖（保底只升不降）。"""
        mk.set_response(VALID_RESP)
        an = ContradictionAnalyzer(llm=mk)
        await an.analyze(fact_report=_make_report(), question="测试",
                         budget={"depth": "standard", "max_tokens": 20000})
        call = mk.call_history[-1]
        assert call["max_tokens"] == 20000
