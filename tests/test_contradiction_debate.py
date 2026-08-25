"""矛盾 debate 关卡测试：反方攻击必须被事实约束，仲裁结果进入理性输入。"""

import asyncio
import json

from praxic.api.schemas.models import Fact, FactReport
from praxic.core.contradiction import ContradictionAnalyzer


def _graph_json():
    return json.dumps({
        "principal_contradiction": {"description": "主矛盾", "tension_poles": ["A", "B"], "contradiction_type": "internal"},
        "secondary_contradictions": [],
        "dynamic_note": "原动态",
        "synthesis": "综合",
        "system_model": {
            "system_boundary": "", "external_environment": "",
            "elements": [{"name": "A", "based_on_fact_ids": ["f1"]}],
            "relationships": [], "feedback_loops": [], "emergent_properties": [],
        },
    }, ensure_ascii=False)


class CriticLLM:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def call(self, messages=None, system="", **kwargs):
        self.calls += 1
        return type("_R", (), {"content": json.dumps(self.response, ensure_ascii=False), "metadata": {}})()


def _facts():
    return FactReport(facts=[
        Fact(id="f1", content="事实一", source_type="web", credibility=0.9),
        Fact(id="f2", content="事实二", source_type="web", credibility=0.9),
    ])


def test_high_valid_challenge_marks_graph_and_uncertainty():
    async def _run():
        llm = CriticLLM({
            "verdict": "needs_revision",
            "challenges": [{
                "target": "principal", "claim": "主矛盾忽略 f2 的反证",
                "issue": "ignored_counterevidence", "fact_ids": ["f2"],
                "severity": "high", "revision_hint": "纳入 f2 后重估主要方面",
            }],
        })
        analyzer = ContradictionAnalyzer(llm=llm)
        graph = analyzer._parse_response(_graph_json())
        result = await analyzer.debate(graph, _facts(), "测试问题", strategy="once")
        assert llm.calls == 1
        assert result.debate_audit["status"] == "challenged"
        assert len(result.debate_audit["challenges"]) == 1
        assert "反方审查" in result.dynamic_note
        assert any("纳入 f2" in x for x in result.system_model.uncertainty_areas)

    asyncio.run(_run())


def test_invalid_fact_attack_is_discarded_by_code_arbiter():
    async def _run():
        llm = CriticLLM({
            "verdict": "needs_revision",
            "challenges": [{
                "target": "principal", "claim": "凭空攻击",
                "issue": "unsupported_fact", "fact_ids": ["f404"],
                "severity": "high", "revision_hint": "无",
            }],
        })
        analyzer = ContradictionAnalyzer(llm=llm)
        graph = analyzer._parse_response(_graph_json())
        result = await analyzer.debate(graph, _facts(), "测试问题", strategy="once")
        assert result.debate_audit["status"] == "accepted"
        assert result.debate_audit["challenges"] == []
        assert result.debate_audit["discarded_challenges"][0]["fact_ids"] == ["f404"]

    asyncio.run(_run())


def test_off_strategy_does_not_call_llm():
    async def _run():
        llm = CriticLLM({"verdict": "sound", "challenges": []})
        analyzer = ContradictionAnalyzer(llm=llm)
        graph = analyzer._parse_response(_graph_json())
        result = await analyzer.debate(graph, _facts(), "测试问题", strategy="off")
        assert result is graph
        assert llm.calls == 0

    asyncio.run(_run())