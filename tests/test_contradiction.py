"""Tests for ContradictionAnalyzer."""
import json, pytest
from praxic.api.schemas.models import ContradictionType, Fact, FactReport
from praxic.core.contradiction import ContradictionAnalyzer
from tests.mock_llm import MockLLM

VALID_RESP = json.dumps({"principal_contradiction":{"description":"用户期望与系统能力之间的根本矛盾","tension_poles":["用户高期望","系统能力有限"],"contradiction_type":"internal","rank":1,"primary_aspect":"系统能力有限","transformation_condition":"当知识库扩展时转移","basis_fact_ids":["f1","f2"],"basis_summary":"基于f1和f2"},"secondary_contradictions":[{"description":"准确性与速度的矛盾","tension_poles":["准确性","速度"],"contradiction_type":"internal","rank":2,"primary_aspect":"准确性","transformation_condition":"有充分计算资源时缓解","basis_fact_ids":["f3"],"basis_summary":"基于f3"}],"dynamic_note":"主要矛盾处于相对稳定状态","synthesis":"核心矛盾是用户期望与能力差距"}, ensure_ascii=False)
VALID_NO_SEC = json.dumps({"principal_contradiction":{"description":"只有一个主要矛盾","tension_poles":["A","B"],"contradiction_type":"internal","rank":1,"primary_aspect":"A","transformation_condition":"条件","basis_fact_ids":[],"basis_summary":""},"secondary_contradictions":[],"dynamic_note":"无","synthesis":"简单情况"}, ensure_ascii=False)

def _make_report(n=3):
    return FactReport(facts=[Fact(id=f"f{i}",content=f"事实{i}",credibility=0.8,source_type="internal") for i in range(1,n+1)], summary="测试")

@pytest.fixture
def mk():
    return MockLLM()
@pytest.fixture
def az(mk):
    return ContradictionAnalyzer(llm=mk)

class TestAnalyzer:
    @pytest.mark.asyncio
    async def test_basic(self, az, mk):
        mk.set_response(VALID_RESP)
        r = await az.analyze(fact_report=_make_report(), question="测试")
        assert r.principal_contradiction is not None
        assert r.principal_contradiction.rank == 1
        assert len(r.secondary_contradictions) == 1
        assert mk.call_count == 1

    @pytest.mark.asyncio
    async def test_no_secondary(self, az, mk):
        mk.set_response(VALID_NO_SEC)
        r = await az.analyze(fact_report=_make_report(), question="简单")
        assert r.principal_contradiction is not None
        assert r.secondary_contradictions == []

    @pytest.mark.asyncio
    async def test_basis_parsed(self, az, mk):
        mk.set_response(VALID_RESP)
        r = await az.analyze(fact_report=_make_report(), question="测试")
        pc = r.principal_contradiction
        assert pc is not None
        assert pc.basis_fact_ids == ["f1","f2"]
        assert pc.basis_summary != ""

class TestParser:
    @pytest.mark.asyncio
    async def test_fenced(self, az, mk):
        mk.set_response("```json\n" + VALID_RESP + "\n```")
        r = await az.analyze(fact_report=_make_report(), question="测试")
        assert r.principal_contradiction is not None

    @pytest.mark.asyncio
    async def test_prose_wrap(self, az, mk):
        mk.set_response("分析如下：\n" + VALID_NO_SEC + "\n以上。")
        r = await az.analyze(fact_report=_make_report(), question="测试")
        assert r.principal_contradiction is not None

    @pytest.mark.asyncio
    async def test_fallback(self, az, mk):
        mk.set_response("主要矛盾：系统能力不足。次要矛盾：资源不均。")
        r = await az.analyze(fact_report=_make_report(), question="测试")
        assert r.synthesis != ""

    @pytest.mark.asyncio
    async def test_invalid_type(self, az, mk):
        resp = json.dumps({"principal_contradiction":{"description":"t","tension_poles":["A","B"],"contradiction_type":"bad","rank":1,"primary_aspect":"A","transformation_condition":"","basis_fact_ids":[],"basis_summary":""},"secondary_contradictions":[],"dynamic_note":"","synthesis":""})
        mk.set_response(resp)
        r = await az.analyze(fact_report=_make_report(), question="测试")
        assert r.principal_contradiction.contradiction_type == ContradictionType.INTERNAL
