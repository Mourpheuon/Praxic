"""引用完整性关卡测试：矛盾分析的 based_on_fact_ids 必须指向真实事实。"""

import asyncio
import json

from praxic.api.schemas.models import Fact, FactReport
from praxic.core.contradiction import ContradictionAnalyzer, validate_fact_citations


def _graph_json(element_ids):
    return json.dumps({
        "principal_contradiction": {"description": "主矛盾", "tension_poles": ["A", "B"], "contradiction_type": "internal"},
        "secondary_contradictions": [],
        "dynamic_note": "",
        "synthesis": "",
        "system_model": {
            "system_boundary": "",
            "external_environment": "",
            "elements": [{"name": "e1", "description": "", "based_on_fact_ids": element_ids}],
            "relationships": [],
            "feedback_loops": [],
            "emergent_properties": [],
        },
    }, ensure_ascii=False)


def test_validate_fact_citations_counts_valid_and_invalid():
    graph = ContradictionAnalyzer(None)._parse_response(_graph_json(["f1", "fX"]))
    cited, total, invalid = validate_fact_citations(graph, {"f1", "f2"})
    assert cited == 1
    assert total == 2
    assert invalid == ["fX"]


def test_validate_fact_citations_all_valid():
    graph = ContradictionAnalyzer(None)._parse_response(_graph_json(["f1", "f2"]))
    cited, total, invalid = validate_fact_citations(graph, {"f1", "f2"})
    assert cited == 2
    assert total == 2
    assert invalid == []


class SeqLLM:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = 0

    async def call(self, messages=None, system="", **kwargs):
        self.calls += 1
        content = self.contents.pop(0) if self.contents else self.contents[-1]
        return type("_R", (), {"content": content, "metadata": {}})()


def test_analyze_retries_once_on_invalid_citation():
    from praxic.config import settings

    async def _run():
        llm = SeqLLM([_graph_json(["f1", "fX"]), _graph_json(["f1", "f2"])])
        analyzer = ContradictionAnalyzer(llm=llm)
        fr = FactReport(facts=[
            Fact(id="f1", content="事实一", source_type="web", credibility=0.9),
            Fact(id="f2", content="事实二", source_type="internal", credibility=0.95),
        ])
        graph = await analyzer.analyze(fr, "测试问题")
        assert llm.calls == 2
        cited, total, invalid = validate_fact_citations(graph, {"f1", "f2"})
        assert invalid == []

    asyncio.run(_run())