"""
可信度链 —— 追踪可信度在认知阶段间的传递与衰减。
基于"实事求是"原则：结论的可信度 ≤ 其所依赖事实的可信度。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from ..api.schemas.models import (
    ContradictionGraph, RationalSynthesis, DecisionReport, FactReport
)


@dataclass
class CredibilityChain:
    """追踪认知阶段产出的可信度上界。"""

    investigation_max: float = 0.0       # 调查阶段：取所有事实可信度的加权平均
    contradiction_max: float = 0.0       # 矛盾分析：≤ 其所引用事实的可信度
    rational_max: float = 0.0            # 理性认识：≤ 矛盾分析可信度
    decision_max: float = 0.0            # 决策：≤ 理性认识可信度
    overall_confidence: float = 0.0      # 整体可信度：全链路最低值
    weakest_link: str = ""               # 可信度链最薄弱环节的描述
    decay_path: list[str] = field(default_factory=list)

    @classmethod
    def from_trace(
        cls,
        fact_report: FactReport,
        contradiction_graph: Optional[ContradictionGraph] = None,
        rational_synthesis: Optional[RationalSynthesis] = None,
        decision_report: Optional[DecisionReport] = None,
    ) -> "CredibilityChain":
        chain = cls()

        # Level 0: 事实可信度（加权平均，高可信度事实权重更大）
        if fact_report.facts:
            weights = [f.credibility for f in fact_report.facts]
            total_w = sum(weights)
            chain.investigation_max = (
                sum(f.credibility * f.credibility for f in fact_report.facts)
                / total_w
            ) if total_w else 0.5
        else:
            chain.investigation_max = 0.3
        chain.decay_path.append(f"调查事实 → {chain.investigation_max:.2f}")

        # Level 1: 矛盾分析可信度 ≤ 所引用事实可信度
        if contradiction_graph and contradiction_graph.principal_contradiction:
            pc = contradiction_graph.principal_contradiction
            if hasattr(pc, 'basis_fact_ids') and pc.basis_fact_ids:
                cited_facts = [
                    f for f in fact_report.facts
                    if f.id in pc.basis_fact_ids
                ]
                if cited_facts:
                    chain.contradiction_max = min(
                        min(f.credibility for f in cited_facts),
                        chain.investigation_max,
                    )
                else:
                    chain.contradiction_max = chain.investigation_max * 0.8
            else:
                chain.contradiction_max = chain.investigation_max * 0.8
        else:
            chain.contradiction_max = chain.investigation_max * 0.6
        chain.decay_path.append(f"矛盾分析 → {chain.contradiction_max:.2f}")

        # Level 2: 理性认识可信度 ≤ 矛盾分析可信度 × 推理衰减
        if rational_synthesis:
            chain.rational_max = min(
                chain.contradiction_max * 0.9,
                chain.investigation_max,
            )
        else:
            chain.rational_max = chain.contradiction_max * 0.7
        chain.decay_path.append(f"理性认识 → {chain.rational_max:.2f}")

        # Level 3: 决策可信度 ≤ 理性认识可信度 × 决策衰减
        if decision_report:
            chain.decision_max = min(
                chain.rational_max * 0.85,
                chain.investigation_max,
            )
        else:
            chain.decision_max = chain.rational_max * 0.7
        chain.decay_path.append(f"决策输出 → {chain.decision_max:.2f}")

        # 整体可信度 = 全链路最低值
        chain.overall_confidence = min(
            chain.investigation_max,
            chain.contradiction_max,
            chain.rational_max,
            chain.decision_max,
        )

        # 定位最薄弱环节
        levels = {
            "调查阶段": chain.investigation_max,
            "矛盾分析": chain.contradiction_max,
            "理性认识": chain.rational_max,
            "决策输出": chain.decision_max,
        }
        chain.weakest_link = min(levels, key=levels.get)

        return chain

    def summary(self) -> str:
        return (
            f"可信度链: {self.overall_confidence:.2f} "
            f"(调查{self.investigation_max:.2f} → "
            f"矛盾{self.contradiction_max:.2f} → "
            f"理性{self.rational_max:.2f} → "
            f"决策{self.decision_max:.2f}) | "
            f"薄弱环节: {self.weakest_link}"
        )
