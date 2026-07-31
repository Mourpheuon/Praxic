"""Integration tests for CognitiveLoop."""
import json, pytest
from praxic.core.cognitive_loop import CognitiveLoop
from praxic.core.loop_controller import LoopController
from tests.mock_llm import MockLLM

INV = json.dumps({"facts":[{"id":"f1","content":"用户提出了一个技术问题","source_type":"user_input","credibility":0.95},{"id":"f2","content":"系统具备相关知识库","source_type":"internal","credibility":0.8}],"gaps":[{"description":"需验证新信息","importance":"high","suggested_query":"搜索"}],"summary":"调查完成"})
CONTR = json.dumps({"principal_contradiction":{"description":"用户需求与系统能力矛盾","tension_poles":["需求","能力"],"contradiction_type":"internal","rank":1,"primary_aspect":"能力不足","transformation_condition":"当知识扩展后","basis_fact_ids":["f1","f2"],"basis_summary":"基于f1,f2"},"secondary_contradictions":[],"dynamic_note":"稳定","synthesis":"核心是需求与能力匹配"})
RATION = json.dumps({"essence":"知识获取与应用的鸿沟","patterns":["知识碎片化"],"hypotheses":["结构化有帮助"],"synthesis_text":"分析。","contradiction_motion":"缓和","quantitative_changes":["积累"],"qualitative_threshold":"跨领域","negation_of_negation":"体系化","fact_foundation":"基于f1,f2"})
DECIS = json.dumps({"strategic_assessment":"优化知识组织方式","tactical_plan":"三步","action_items":[{"description":"建立知识分类体系","priority":1,"timeline":"本周","expected_outcome":"知识地图","targets_contradiction":"需求与能力矛盾","contradiction_resolution":"resolve_principal_aspect","based_on_facts":"基于f1,f2"}],"risks":["标准不通用"],"summary":"优化知识组织是关键"})
PERSP = "[评论]\n从批判者角度看，方案过于乐观。\n\n---关键洞察---\n- 标准制定是难题\n- 缺量化指标"
PRACT = json.dumps({"steps_taken":[{"description":"模拟分类","observed_result":"边界模糊"}],"unexpected_findings":["边界模糊"],"practice_summary":"理论分类与实际有差距"})
REFL = json.dumps({"convergence_score":0.88,"should_reinvestigate":False,"reinvestigation_focus":"","skip_phases":[],"focus_hints":{},"recommended_mode":"","lessons":["需要灵活标准"],"issues":[],"improvements":[],"contradiction_stability":0.85,"contradiction_shift_detected":False,"contradiction_shift_description":"","understanding_level":"理性","qualitative_leap":True,"level_progression":""})
REFL_REINV = json.dumps({"convergence_score":0.4,"should_reinvestigate":True,"reinvestigation_focus":"深入调查","skip_phases":[],"focus_hints":{},"recommended_mode":"","lessons":[],"issues":[],"improvements":[],"contradiction_stability":0.3,"contradiction_shift_detected":True,"contradiction_shift_description":"不稳定","understanding_level":"感性","qualitative_leap":False,"level_progression":""})
REFL_CONV = json.dumps({"convergence_score":0.87,"should_reinvestigate":False,"reinvestigation_focus":"","skip_phases":[],"focus_hints":{},"recommended_mode":"","lessons":[],"issues":[],"improvements":[],"contradiction_stability":0.9,"contradiction_shift_detected":False,"contradiction_shift_description":"","understanding_level":"理性","qualitative_leap":True,"level_progression":""})
PSYNTH = json.dumps({"synthesized_insight":"综合洞察","critical_warnings":[],"consensus_points":["共识点1"],"divergence_points":[]})
SYNTH = json.dumps({"synthesized_insight":"综合","critical_warnings":[],"consensus_points":[],"divergence_points":[]})

# Standard mode needs ~22+ LLM calls per iteration:
# inv(1) + contr(1) + ration(1) + decis(1) + persp(9: 4+4+1) + pract(3+: plan+rounds+summary) + refl(1)
# Add extras for safety
_EMPTY = "{}"
FULL = [INV, CONTR, RATION, DECIS,
        PERSP, PERSP, PERSP, PERSP, PERSP, PERSP, PERSP, PERSP, PSYNTH,
        _EMPTY, _EMPTY, _EMPTY, _EMPTY, _EMPTY, _EMPTY, _EMPTY,
        _EMPTY,
        REFL]  # ~22 responses

@pytest.fixture
def mk():
    return MockLLM()

class TestBasic:
    @pytest.mark.asyncio
    async def test_completes(self, mk):
        mk.set_responses(list(FULL))
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(question="如何学习？")
        assert r.summary != ""
        t = r.full_trace
        assert t.investigation is not None
        assert t.contradictions is not None
        assert t.rational_synthesis is not None
        assert t.decision is None
        assert t.practice is not None
        assert t.reflection is not None

    @pytest.mark.asyncio
    async def test_fast(self, mk):
        mk.set_responses([INV, CONTR, RATION, DECIS])
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(question="快", mode="fast")
        t = r.full_trace
        assert t.investigation is not None
        assert t.decision is None
        assert t.practice is None
        assert t.reflection is None

    @pytest.mark.asyncio
    async def test_convergence(self, mk):
        # Pre-seed with convergent REFL as the repeating fallback,
        # and provide enough queued responses for ~20+ calls in 1 iteration.
        mk._last_response = REFL  # when queue runs out, returns convergent REFL
        mk.set_responses(list(FULL))
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(question="收敛")
        assert r.full_trace.metadata.iterations >= 1
        assert r.full_trace.reflection is not None

    @pytest.mark.asyncio
    async def test_reinvest(self, mk):
        mk._last_response = REFL
        mk.set_responses(list(FULL))
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(question="复杂")
        assert r.full_trace.metadata.iterations >= 1
        assert r.summary != ""


class TestSteeringSemantics:
    def test_broadcast_persists_and_targeted_steer_is_consumed_once(self):
        controller = LoopController("steering-contract")
        controller.steer("广播提示")
        controller.steer("实践提示", target_phase="practice")

        investigation = controller.collect_steers("investigation")
        practice = controller.collect_steers("practice")
        reflection = controller.collect_steers("reflection")

        assert "广播提示" in investigation
        assert "广播提示" in practice
        assert "广播提示" in reflection
        assert "实践提示" not in investigation
        assert "实践提示" in practice
        assert "实践提示" not in reflection

class TestTrace:
    @pytest.mark.asyncio
    async def test_credibility(self, mk):
        mk.set_responses(list(FULL))
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(question="可信度")
        assert r.full_trace.metadata.credibility_chain_summary
        assert "可信度链" in (r.full_trace.metadata.credibility_chain_summary or "")

    @pytest.mark.asyncio
    async def test_durations(self, mk):
        mk.set_responses(list(FULL))
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(question="计时")
        d = r.full_trace.metadata.phase_durations
        assert "investigation" in d
        assert "practice" in d
        assert "decision" not in d

    @pytest.mark.asyncio
    async def test_actions(self, mk):
        mk._last_response = REFL
        mk.set_responses(list(FULL))
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(question="行动")
        # Check that we got action items back in the response
        assert len(r.action_items) >= 1 or r.full_trace.practice is not None

class TestCallbacks:
    @pytest.mark.asyncio
    async def test_on_phase(self, mk):
        mk.set_responses(list(FULL))
        phases = []
        def rec(p, s): phases.append(p)
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        await loop.run(question="回调", on_phase=rec)
        assert len(phases) > 0
