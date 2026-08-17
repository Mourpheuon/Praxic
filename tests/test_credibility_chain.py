"""Tests for CredibilityChain."""
import pytest
from praxic.api.schemas.models import (Contradiction, ContradictionGraph, ContradictionType, Fact, FactReport, RationalSynthesis)
from praxic.core.credibility_chain import CredibilityChain

def _make_fact_report(facts):
    return FactReport(facts=[Fact(id=fid, content=content, credibility=cred, source_type="internal") for fid, content, cred in facts], summary="test")

def _make_contradiction(basis_ids, desc="test contradiction"):
    return ContradictionGraph(principal_contradiction=Contradiction(description=desc, tension_poles=["A","B"], contradiction_type=ContradictionType.INTERNAL, rank=1, basis_fact_ids=basis_ids, basis_summary="test"), synthesis=desc)

class TestCredibilityChainBasic:
    def test_all_high_facts_chain(self):
        facts = _make_fact_report([("f1","high cred fact 1",0.95),("f2","high cred fact 2",0.90),("f3","high cred fact 3",0.92)])
        cg = _make_contradiction(basis_ids=["f1","f2","f3"])
        rational = RationalSynthesis(essence="test", synthesis_text="test")
        chain = CredibilityChain.from_trace(fact_report=facts, contradiction_graph=cg, rational_synthesis=rational)
        assert chain.investigation_max > 0.9
        assert chain.overall_confidence > 0.5

    def test_mixed_credibility_decay(self):
        facts = _make_fact_report([("f1","high cred",0.9),("f2","low cred",0.3)])
        chain = CredibilityChain.from_trace(fact_report=facts)
        assert 0.7 <= chain.investigation_max <= 0.85
        assert chain.overall_confidence < 0.5

    def test_empty_facts(self):
        facts = FactReport(facts=[], summary="empty")
        chain = CredibilityChain.from_trace(fact_report=facts)
        assert chain.investigation_max <= 0.3
        assert chain.overall_confidence <= 0.3

class TestCredibilityChainWithContradiction:
    def test_basis_fact_ids_match(self):
        facts = _make_fact_report([("f1","key fact",0.95),("f2","supporting",0.60),("f3","irrelevant",0.40)])
        cg = _make_contradiction(basis_ids=["f2","f3"])
        chain = CredibilityChain.from_trace(fact_report=facts, contradiction_graph=cg)
        assert chain.contradiction_max <= chain.investigation_max

    def test_basis_fact_ids_missing(self):
        facts = _make_fact_report([("f1","only fact",0.95)])
        cg = _make_contradiction(basis_ids=["f99"])
        chain = CredibilityChain.from_trace(fact_report=facts, contradiction_graph=cg)
        assert chain.contradiction_max == pytest.approx(chain.investigation_max * 0.8, rel=0.1)

class TestCredibilityChainFullPipeline:
    def test_full_pipeline_decay(self):
        facts = _make_fact_report([("f1","fact",0.9)])
        cg = _make_contradiction(basis_ids=["f1"])
        rational = RationalSynthesis(essence="test", synthesis_text="test")
        chain = CredibilityChain.from_trace(fact_report=facts, contradiction_graph=cg, rational_synthesis=rational)
        assert chain.investigation_max > 0.8
        assert chain.contradiction_max <= chain.investigation_max
        assert chain.rational_max <= chain.contradiction_max
        assert chain.practice_max <= chain.rational_max
        assert chain.overall_confidence == min(chain.investigation_max, chain.contradiction_max, chain.rational_max, chain.practice_max)

    def test_weakest_link_identified(self):
        facts = _make_fact_report([("f1","strong fact",0.95)])
        cg = _make_contradiction(basis_ids=["f1"])
        chain = CredibilityChain.from_trace(fact_report=facts, contradiction_graph=cg)
        assert chain.weakest_link in ["调查阶段","矛盾分析","理性认识","实践检验"]

    def test_summary_format(self):
        facts = _make_fact_report([("f1","fact",0.9)])
        chain = CredibilityChain.from_trace(fact_report=facts)
        s = chain.summary()
        assert "可信度链" in s
        assert "薄弱环节" in s

    def test_decay_path_populated(self):
        facts = _make_fact_report([("f1","fact",0.9)])
        chain = CredibilityChain.from_trace(fact_report=facts)
        assert len(chain.decay_path) == 4
        assert all("→" in p for p in chain.decay_path)
