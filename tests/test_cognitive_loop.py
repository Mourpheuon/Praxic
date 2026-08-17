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
# 根因②修复测试数据：goal_achieved=true 但收敛度低且 reinvestigate=true（旧判据会继续空转）
REFL_GOAL = json.dumps({"convergence_score":0.78,"should_reinvestigate":True,"reinvestigation_focus":"更深入调查","skip_phases":[],"focus_hints":{},"recommended_mode":"","lessons":[],"issues":[],"improvements":[],"contradiction_stability":0.5,"contradiction_shift_detected":False,"contradiction_shift_description":"","understanding_level":"知性","qualitative_leap":False,"level_progression":"","goal_achieved":True,"goal_evidence":"能力询问，结论已明确","incomplete_tasks":["未验证 lean 安装"]})
# 收敛停滞测试数据：连续两轮 0.6 且 reinvestigate=true（旧判据会继续跑到 max_iterations）
REFL_LOW = json.dumps({"convergence_score":0.6,"should_reinvestigate":True,"reinvestigation_focus":"深入调查","skip_phases":[],"focus_hints":{},"recommended_mode":"","lessons":[],"issues":[],"improvements":[],"contradiction_stability":0.3,"contradiction_shift_detected":True,"contradiction_shift_description":"不稳定","understanding_level":"感性","qualitative_leap":False,"level_progression":"","goal_achieved":False,"goal_evidence":"","incomplete_tasks":["事实不足"]})
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
        assert not hasattr(t, "decision")
        assert t.practice is not None
        assert t.reflection is not None

    @pytest.mark.asyncio
    async def test_fast(self, mk):
        mk.set_responses([INV, CONTR, RATION, DECIS])
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(question="快", mode="fast")
        t = r.full_trace
        assert t.investigation is not None
        assert not hasattr(t, "decision")
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
    async def test_goal_achieved_stops_early(self, mk):
        """根因②修复：任务目标已达成（能力询问第一轮即有答案），
        即使收敛度 0.78 < 0.85 且 should_reinvestigate=true，也应一轮收敛。"""
        # 第一轮调用序列：预处理5+调查1+探查1+矛盾1+理性1+实践规划3+知性分析1 = 13 个；
        # 第 14 个（reflection）放 REFL_GOAL，保证 reflection 拿到 goal_achieved=true 判定。
        mk._last_response = REFL_GOAL
        mk.set_responses(list(FULL[:13]) + [REFL_GOAL])
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        loop.max_iterations = 3  # 测试环境默认为 1，调大以排除“因上限才停”的混淆
        r = await loop.run(question="你可以跑 lean 代码吗")
        assert r.full_trace.metadata.iterations == 1, (
            f"goal_achieved 应一轮收敛，实际 {r.full_trace.metadata.iterations} 轮"
        )
        assert r.full_trace.reflection.goal_achieved is True

    @pytest.mark.asyncio
    async def test_convergence_stagnation_forces_stop(self, mk):
        """根因②修复：连续两轮收敛度不升（0.6 → 0.6）且 reinvestigate=true，
        旧判据会继续空转，新判据第二轮强制收敛止损。"""
        mk._last_response = REFL_LOW
        mk.set_responses(list(FULL[:13]) + [REFL_LOW])
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        loop.max_iterations = 3  # 测试环境默认为 1，调大才能验证“第二轮强制停”而非“上限停”
        r = await loop.run(question="收敛如何")
        assert r.full_trace.metadata.iterations == 2, (
            f"收敛停滞应第二轮强制停，实际 {r.full_trace.metadata.iterations} 轮"
        )
        assert r.full_trace.reflection.convergence_score == 0.6

    @pytest.mark.asyncio
    async def test_goal_fields_parsed(self, mk):
        """根因②修复：ReflectionReport 新字段（goal_achieved/incomplete_tasks）可被解析。"""
        from praxic.core.reflection import ReflectionEngine
        report = ReflectionEngine(llm=mk)._parse_response(REFL_GOAL)
        assert report.goal_achieved is True
        assert report.goal_evidence != ""
        assert "lean" in report.incomplete_tasks[0]

    @pytest.mark.asyncio
    async def test_practice_forced_on_first_round_even_if_skipped(self, mk):
        """根因④修复：预处理将 practice 判为 skip（如 fact_lookup）时，
        首轮也必须强制执行——"复用上一轮"只对同一认知循环的后续轮有意义，
        跨问题没有上一轮，跳过会导致反思面对空白实践受旧题结论污染。"""
        step1_fact_lookup = json.dumps({
            "task_nature": "fact_lookup", "complexity": "standard",
            "needs_investigation": True,
        })
        events = []
        # 响应序列：0=step1(fact_lookup→practice=skip)，1-4=预处理后续失败回退，
        # 5=investigation，6=probe，7=contradiction，8=rational，9-11=实践规划失败，
        # 12=知性分析，13=reflection(收敛)。
        responses = [
            step1_fact_lookup, "{}", "{}", "{}", "{}",
            INV, "{}", CONTR, RATION, PERSP, PERSP, PERSP, "{}", REFL_CONV,
        ]
        mk._last_response = REFL_CONV
        mk.set_responses(responses)
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)

        def _on_phase(phase, summary, data=None):
            events.append(summary)

        r = await loop.run(question="查一下事实", on_phase=_on_phase)
        # 首轮 practice 被执行（即使预处理标了 skip），trace.practice 非空
        assert r.full_trace.practice is not None, "首轮 practice 应被强制执行"
        # 事件流中不应出现“复用上一轮”的跳过日志
        assert not any("已跳过：实践结论复用上一轮" in e for e in events), (
            "首轮不应出现跨题复用的跳过日志"
        )

    @pytest.mark.asyncio
    async def test_investigation_skip_does_not_crash_downstream(self, mk):
        """回归修复：simple creative_design 任务 investigation 被判 skip 时，
        fact_report 需兜底为空调查产物，否则 contradiction.analyze 访问 .facts 崩溃
        （AttributeError: 'NoneType' object has no attribute 'facts'）。"""
        step1 = json.dumps({
            "task_nature": "creative_design", "complexity": "simple",
            "needs_investigation": True,
        })
        mk._last_response = REFL_CONV
        # 0=step1(creative_design+simple→investigation light→skip)，1-4=预处理回退，
        # 5=探查，6=contradiction，7=rational，8-10=实践规划失败，11=知性分析，12=reflection
        mk.set_responses([
            step1, "{}", "{}", "{}", "{}", "{}",
            CONTR, RATION, PERSP, PERSP, PERSP, "{}", REFL_CONV,
        ])
        loop = CognitiveLoop(llm=mk, web_search_enabled=False)
        r = await loop.run(question="设计一个 logo")
        t = r.full_trace
        # 不崩溃且调查产物有兜底，下游阶段照常执行
        assert t.investigation is not None
        assert t.contradictions is not None
        assert r.summary != ""


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
