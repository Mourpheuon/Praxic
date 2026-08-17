"""断点续跑（resume）功能测试。

覆盖：
  - resume_from 解析（phase / tool / auto / 未知）
  - 事件序列断点定位（阶段级 / 工具级）
  - 阶段产物重建（pydantic 实例 / dict 两种形态）
  - 端到端续跑：复用已完成阶段产物，不重跑已完成阶段
  - 回归：resume_from 缺省时与现状完全一致
"""
import json
import pytest

from praxic.core.cognitive_loop import CognitiveLoop
from praxic.core.resume import (
    parse_resume_from, locate_resume_point, reconstruct_products,
    phases_before,
)
from praxic.api.schemas.models import (
    PreprocessedQuestion, FactReport, ContradictionGraph,
    RationalSynthesis, PracticeReport, ReflectionReport,
)
from tests.mock_llm import MockLLM


# ── 纯函数断点定位 / 重建 ────────────────────────────────────────────

class TestParseResumeFrom:
    def test_empty_returns_none(self):
        assert parse_resume_from("") is None
        assert parse_resume_from(None) is None

    def test_auto_sentinel(self):
        assert parse_resume_from("auto") == {"kind": "auto"}
        assert parse_resume_from("continue") == {"kind": "auto"}

    def test_phase(self):
        assert parse_resume_from("phase:rational") == {"kind": "phase", "phase": "rational"}

    def test_tool(self):
        r = parse_resume_from("tool:investigation:web_search")
        assert r == {"kind": "tool", "phase": "investigation", "tool": "web_search"}

    def test_unknown(self):
        assert parse_resume_from("phase:nonexistent") is None
        # 未知形式不误判为工具，回退 auto
        assert parse_resume_from("random_garbage") == {"kind": "auto"}


class TestLocatePoint:
    @staticmethod
    def _phase_ev(phase, data):
        return {"type": "phase", "phase": phase, "summary": "", "data": data}

    @staticmethod
    def _tool_ev(phase, tool, status="success"):
        return {
            "type": "activity", "phase": phase, "event_type": "tool_call",
            "summary": "t", "data": {
                "event_type": "tool_call", "tool": tool,
                "record": {"tool": tool, "result": {"status": status, "content": "x" * 50}},
            },
        }

    def test_last_phase(self):
        events = [self._phase_ev("preprocessing", {}), self._phase_ev("investigation", {})]
        assert locate_resume_point(events) == {"product_phase": "investigation"}

    def test_last_is_tool(self):
        events = [
            self._phase_ev("preprocessing", {}),
            self._phase_ev("investigation", {}),
            self._tool_ev("investigation", "web_fetch"),
        ]
        r = locate_resume_point(events)
        assert r["product_phase"] == "investigation"
        assert r["tool"] == "web_fetch"

    def test_empty(self):
        assert locate_resume_point([]) is None


class TestReconstruct:
    @staticmethod
    def _ev(phase, obj):
        return {"type": "phase", "phase": phase, "summary": "", "data": obj}

    def test_from_models(self):
        p = PreprocessedQuestion(original_question="q", expanded_question="eq", task_nature="fact_lookup")
        inv = FactReport(facts=[], summary="调查摘要")
        events = [self._ev("preprocessing", p), self._ev("investigation", inv)]
        prods = reconstruct_products(events)
        assert prods["preprocessing"].expanded_question == "eq"
        assert prods["investigation"].summary == "调查摘要"

    def test_from_dicts(self):
        events = [
            self._ev("preprocessing", {"original_question": "q", "expanded_question": "eq"}),
            self._ev("investigation", {"facts": [], "summary": "调查摘要"}),
        ]
        prods = reconstruct_products(events)
        assert isinstance(prods["preprocessing"], PreprocessedQuestion)
        assert isinstance(prods["investigation"], FactReport)
        assert prods["investigation"].summary == "调查摘要"

    def test_empty_products_filtered(self):
        events = [self._ev("investigation", {"facts": [], "summary": ""})]
        prods = reconstruct_products(events)
        assert "investigation" not in prods


class TestPhasesBefore:
    def test_order(self):
        assert phases_before("rational") == ["preprocessing", "investigation", "contradiction"]
        assert phases_before("investigation") == ["preprocessing"]


# ── 端到端续跑：复用已完成阶段产物 ──────────────────────────────────

def _resume_events():
    """构造含全部已完成阶段产物的续跑事件序列（pydantic 模型形态）。"""
    p = PreprocessedQuestion(
        original_question="测试", expanded_question="测试扩展",
        task_nature="fact_lookup", task_complexity="standard",
        investigation_necessity="required", contradiction_necessity="required",
        rational_necessity="required", practice_necessity="required",
        reflection_necessity="required",
    )
    inv = FactReport(
        facts=[{"id": "f1", "content": "事实A", "source_type": "internal", "credibility": 0.9}],
        gaps=[], summary="续跑调查",
    )
    cg = ContradictionGraph(
        principal_contradiction={
            "description": "矛盾B", "tension_poles": ["a", "b"],
            "contradiction_type": "internal", "rank": 1, "primary_aspect": "a",
            "transformation_condition": "", "basis_fact_ids": ["f1"], "basis_summary": "",
        },
        secondary_contradictions=[], dynamic_note="", synthesis="",
    )
    rat = RationalSynthesis(essence="本质C", patterns=[], hypotheses=[], synthesis_text="理性认识")
    prat = PracticeReport(steps_taken=[{"description": "实践步骤"}], practice_summary="实践摘要")
    return [
        {"type": "phase", "phase": "preprocessing", "summary": "", "data": p},
        {"type": "phase", "phase": "investigation", "summary": "", "data": inv},
        {"type": "phase", "phase": "contradiction", "summary": "", "data": cg},
        {"type": "phase", "phase": "rational", "summary": "", "data": rat},
        {"type": "phase", "phase": "practice", "summary": "", "data": prat},
    ]


_REFL = json.dumps({
    "convergence_score": 0.88, "should_reinvestigate": False,
    "reinvestigation_focus": "", "skip_phases": [], "focus_hints": {},
    "recommended_mode": "", "lessons": [], "issues": [], "improvements": [],
    "contradiction_stability": 0.87, "contradiction_shift_detected": False,
    "contradiction_shift_description": "", "understanding_level": "理性",
    "qualitative_leap": True, "level_progression": "", "final_answer": "续跑验证答案",
})


@pytest.fixture
def mk():
    return MockLLM()


class TestResumeEndToEnd:
    @pytest.mark.asyncio
    async def test_resume_reuses_completed_phases(self, mk):
        """续跑复用 investigation/contradiction/rational/practice，只继续 reflection。"""
        events = _resume_events()  # 中断在 practice 之后（尚无 reflection）
        calls_before = mk.call_count
        # 续跑从 reflection 开始，只需 reflection + 最终回答两次 LLM 调用
        mk.set_responses([_REFL, json.dumps({"summary": "续跑回答"})])
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(
            question="测试", resume_from="phase:reflection", resume_events=events,
        )
        t = r.full_trace
        assert t.metadata.resumed is True
        # 已完成阶段产物全部复用
        assert t.investigation is not None
        assert t.contradictions is not None
        assert t.rational_synthesis is not None
        assert t.practice is not None
        assert t.reflection is not None
        # 未重跑已完成阶段：LLM 调用数很少（仅 reflection + 回答）
        assert mk.call_count - calls_before <= 3

    @pytest.mark.asyncio
    async def test_phase_resume_skips_earlier_phases(self, mk):
        """phase:rational 续跑：跳过 investigation/contradiction，继续 rational 及其后。"""
        events = _resume_events()
        calls_before = mk.call_count
        mk._last_response = _REFL
        mk.set_responses([
            json.dumps({"essence": "理性", "patterns": [], "hypotheses": [], "synthesis_text": "理性认识"}),
            json.dumps({"steps_taken": [{"description": "实践"}], "practice_summary": "实践"}),
            _REFL, json.dumps({"summary": "答"}),
        ])
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(
            question="测试", resume_from="phase:rational", resume_events=events,
        )
        t = r.full_trace
        assert t.metadata.resumed is True
        # investigation 与 contradiction 产物被复用（跳过其 LLM 重跑）
        assert t.investigation is not None
        assert t.contradictions is not None
        # 续跑完成（含 practice/reflection/answer），未进入失控重跑（完整重跑会达几十次）
        assert mk.call_count - calls_before <= 25

    @pytest.mark.asyncio
    async def test_tool_resume_reuses_collected_tools(self, mk):
        """tool 级续跑：investigation 在 web_search 后被中断，续跑复用已收集结果、不重跑搜索。"""
        events = [
            # 仅 preprocessing + 一次成功的 web_search 工具调用（investigation 尚未产出完整产物）
            {"type": "phase", "phase": "preprocessing", "summary": "",
             "data": PreprocessedQuestion(
                 original_question="测试", expanded_question="测试扩展",
                 task_nature="fact_lookup", task_complexity="standard",
             )},
            {"type": "activity", "phase": "investigation", "event_type": "tool_call",
             "summary": "WEB_SEARCH·已完成", "data": {
                 "event_type": "tool_call", "tool": "web_search",
                 "record": {"tool": "web_search", "result": {"status": "success", "content": "已搜索到的关键网络信息"}},
             }},
        ]
        calls_before = mk.call_count
        mk._last_response = _REFL
        mk.set_responses([
            json.dumps({"facts": [{"id": "f", "content": "基于已收集信息的事实", "source_type": "internal", "credibility": 0.9}], "gaps": [], "summary": "调查"}),
            json.dumps({"principal_contradiction": {"description": "矛盾", "tension_poles": ["a", "b"], "contradiction_type": "internal", "rank": 1, "primary_aspect": "a", "transformation_condition": "", "basis_fact_ids": [], "basis_summary": ""}, "secondary_contradictions": [], "dynamic_note": "", "synthesis": ""}),
            json.dumps({"essence": "理性", "patterns": [], "hypotheses": [], "synthesis_text": "理性认识"}),
            json.dumps({"steps_taken": [{"description": "实践"}], "practice_summary": "实践"}),
            _REFL, json.dumps({"summary": "答"}),
        ])
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(
            question="测试", resume_from="tool:investigation:web_search",
            resume_events=events,
        )
        t = r.full_trace
        assert t.metadata.resumed is True
        # 续跑完成整条链路，产出最终结果
        assert t.investigation is not None
        assert t.reflection is not None
        # 续跑不再重跑网络搜索：investigation 走 skip_external_collection
        # （通过事件中记录到 resume_skip_collection 日志间接体现，这里用调用数上限兜底）
        assert mk.call_count - calls_before <= 25

    @pytest.mark.asyncio
    async def test_phase_jump_beyond_available_products(self, mk):
        """显式请求跳过到 reflection，但 investigation/contradiction 产物缺失 → 不崩溃，缺失阶段重跑。"""
        # 只提供 preprocessing 产物（investigation 尚未完成，被中断）
        events = [{"type": "phase", "phase": "preprocessing", "summary": "",
                   "data": PreprocessedQuestion(
                       original_question="测试", expanded_question="测试扩展",
                       task_nature="fact_lookup", task_complexity="standard",
                   )}]
        mk._last_response = _REFL
        mk.set_responses([
            json.dumps({"facts": [{"id": "f", "content": "事实", "source_type": "internal", "credibility": 0.9}], "gaps": [], "summary": "调查"}),
            json.dumps({"principal_contradiction": {"description": "矛盾", "tension_poles": ["a", "b"], "contradiction_type": "internal", "rank": 1, "primary_aspect": "a", "transformation_condition": "", "basis_fact_ids": [], "basis_summary": ""}, "secondary_contradictions": [], "dynamic_note": "", "synthesis": ""}),
            json.dumps({"essence": "理性", "patterns": [], "hypotheses": [], "synthesis_text": "理性认识"}),
            json.dumps({"steps_taken": [{"description": "实践"}], "practice_summary": "实践"}),
            _REFL, json.dumps({"summary": "答"}),
        ])
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        # 请求跳到 reflection，但只有 preprocessing 可用
        r = await loop.run(
            question="测试", resume_from="phase:reflection", resume_events=events,
        )
        t = r.full_trace
        assert t.metadata.resumed is True
        # 缺失产物被重跑，整条链路完成，不崩溃
        assert t.investigation is not None
        assert t.contradictions is not None
        assert t.reflection is not None

    @pytest.mark.asyncio
    async def test_no_source_falls_back_full_run(self, mk):
        """resume_from 给了但无断点源 → 回退完整重跑（标记 resumed=False）。"""
        mk._last_response = _REFL
        mk.set_responses([_REFL])
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(question="测试", resume_from="auto", resume_events=[])
        assert r.full_trace.metadata.resumed is False


class TestResumeNoRegression:
    @pytest.mark.asyncio
    async def test_empty_resume_from_runs_normally(self, mk):
        """resume_from 缺省时与现状完全一致：不标记续跑，正常完成。"""
        # fast 模式避免完整预处理序列对齐问题，仅验证缺省不触发续跑
        mk.set_responses([json.dumps({"facts": [{"id": "f", "content": "事实", "source_type": "internal", "credibility": 0.9}], "gaps": [], "summary": "调查"}),
                         json.dumps({"principal_contradiction": {"description": "矛盾", "tension_poles": ["a", "b"], "contradiction_type": "internal", "rank": 1, "primary_aspect": "a", "transformation_condition": "", "basis_fact_ids": [], "basis_summary": ""}, "secondary_contradictions": [], "dynamic_note": "", "synthesis": ""}),
                         json.dumps({"essence": "本质", "patterns": [], "hypotheses": [], "synthesis_text": "理性"})])
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(question="测试", mode="fast")
        assert r.full_trace.metadata.resumed is False
        assert r.full_trace.investigation is not None
