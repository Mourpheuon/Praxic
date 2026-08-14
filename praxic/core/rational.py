"""
Praxic Agent —— 理性认识阶段
核心原则：去粗取精、去伪存真、由此及彼、由表及里
改进三：从抽象上升到具体 —— 完成辩证运动的第二环节
"""

from __future__ import annotations

import json
from typing import Optional

import structlog

from ..api.schemas.models import (
    ContradictionGraph,
    FactReport,
    RationalSynthesis,
    SystemModel,
)
from ..config import load_phase_prompt, settings
from ..llm.base import BaseLLM
from ..llm import get_llm as _get_default_llm

log = structlog.get_logger(__name__)

_RATIONAL_PROMPT = """
你正在研究用户提出的问题，当前正处于【理性认识】阶段。
核心信条：去粗取精、去伪存真、由此及彼、由表及里。

## 核心方法（实践论）
- 去粗取精：过滤掉次要细节，保留核心要素
- 去伪存真：区分表象与本质，识别误导性信息
- 由此及彼：建立事物之间的关联，发现类比
- 由表及里：从现象深入到本质，揭示规律

## 辩证运动：从抽象上升到具体

矛盾分析阶段已经完成了从具体事实到抽象矛盾的飞跃。你收到了：
- 主要矛盾和次要矛盾的抽象表述
- 系统模型的结构化抽象
- 每个矛盾的 derivation_chain（从事实到矛盾判断的推理路径）

你的任务不是重复这个抽象过程——而是完成理性认识的第二环节：**从抽象再上升到思维中的具体**。

**"从抽象上升到具体"的含义**：
- 抽象给你的是骨架（主要的矛盾关系、本质的趋势）
- 你需要在思维中把这个骨架"填满"——用本质来解释具体的现象
- 一个好的理性认识不是"本质=..."这样的空洞命题
- 而是"因为本质关系是 X，所以表象中观察到的 Y 和 Z 可以得到解释，而且 A 现象可能被误判了"

## 你的任务

1. **接收抽象**（abstract_from）：概括矛盾分析已经抽象出了什么（矛盾的本质关系、系统的主要结构）
2. **识别问题的本质**（essence）：用一两句话说清楚这个问题最根本的是什么
3. **提炼规律**（patterns）：从事实和矛盾中发现的普遍性规律。每条规律必须说明"在什么具体条件下成立"
4. **生成假设**（hypotheses）：基于理性认识，对问题走向的预判。每条假设应说明"如果本质判断正确，那么实践应该观察到什么"
5. **回归具体**（return_to_concrete）：把本质规律放回到具体的现象世界中，解释它如何表现：
   - 如果本质是 X，那么事实 F1、F3、F7 为什么呈现为它们现在的样子？
   - 如果本质是 X，那么信息缺口 G2 和 G5 所指向的"我们还没查到的东西"应该是什么？
6. **识别解释不了的现象**（unexplained_phenomena）：当前框架解释不了的具体现象——诚实记录下来，它们是认识进一步深化的线索
7. **综合性论述**（synthesis_text）：完整的理性认识过程，完整展示"从具体事实→抽象矛盾→回到具体现象"的辩证运动过程，不少于3段
8. **矛盾运动分析**：当前矛盾是在激化、缓和还是转化？哪些量变在积累？质变门槛在哪？
9. **系统及矛盾运动**：利用系统模型和矛盾分析，说明矛盾运动的方向，涌现属性如何受矛盾运动影响

## 输出格式（严格 JSON）
{
  "abstract_from": "从矛盾分析的抽象中接收了什么核心认识（1-2句）",
  "essence": "问题的本质，1-2句话",
  "patterns": ["规律1及成立条件", "规律2及成立条件", "规律3"],
  "hypotheses": ["假设1及可观测预言", "假设2"],
  "return_to_concrete": "把本质放回具体现象中解释——如何用本质解释观察到的具体事实？200-300字",
  "unexplained_phenomena": ["当前框架解释不了的现象1", "现象2"],
  "synthesis_text": "完整的理性认识论述，展示从具体事实→抽象矛盾→回到具体现象的辩证运动过程，深度分析，不少于3段",
  "contradiction_motion": "激化/缓和/转化 —— 说明理由",
  "quantitative_changes": ["量变1", "量变2"],
  "qualitative_threshold": "质变条件描述",
  "negation_of_negation": "螺旋路径预判",
  "fact_foundation": "理性认识所依赖的核心事实简述"
}

只输出 JSON。
"""


class RationalCognitionModule:
    """理性认识模块 —— 从感性认识到理性认识的升华"""

    def __init__(
        self,
        llm: Optional[BaseLLM] = None,
        phase_config: Optional[dict] = None,
    ):
        self.llm = llm or _get_default_llm()
        self.config = phase_config or {}

    async def synthesize(
        self,
        question: str,
        fact_report: FactReport,
        contradiction_graph: ContradictionGraph,
        system_model: Optional[SystemModel] = None,
        budget: dict = None,
    ) -> RationalSynthesis:
        log.info("rational.start")

        principal = contradiction_graph.principal_contradiction
        facts_high = [f for f in fact_report.facts if f.credibility >= 0.7]
        facts_text = "\n".join(f"- {f.content}" for f in facts_high[:8])
        if not facts_text:
            facts_text = "\n".join(f"- {f.content}" for f in fact_report.facts[:6])

        user_content = f"""## 用户问题
{question}

## 关键事实（高可信度）
{facts_text}

## 主要矛盾
{principal.description if principal else '未识别'}
"""
        # 改进五：注入矛盾特殊性
        if principal and principal.particularity_description:
            user_content += f"\n矛盾特殊性：{principal.particularity_description[:200]}"

        # 改进四：注入推导链摘要
        if principal and principal.derivation_chain:
            dc = principal.derivation_chain
            user_content += f"\n推导链摘要：{dc.summary[:200]}"

        user_content += f"""

## 矛盾动态说明
{contradiction_graph.dynamic_note}

## 矛盾综合
{contradiction_graph.synthesis}
"""
        # Inject system model context
        if system_model:
            elements_text = "\n".join(
                f"- {e.name}：{e.function_in_system[:100]}"
                for e in system_model.elements
            )
            relationships_text = "\n".join(
                f"- {r.source_element} -> {r.target_element} [{r.relationship_type}]：{r.description[:80]}"
                for r in system_model.relationships
            )
            feedback_text = "\n".join(
                f"- [{f.loop_type}] {f.description[:120]}"
                for f in system_model.feedback_loops
            )
            emergent_text = "\n".join(
                f"- {ep.property_name}：{ep.description[:100]}"
                for ep in system_model.emergent_properties
            )
            
            user_content += (
                "\n\n## 系统模型（矛盾分析的解剖学基础）\n"
                f"\n### 系统边界\n{system_model.system_boundary}"
                f"\n\n### 关键要素\n{elements_text}"
                f"\n\n### 要素关系\n{relationships_text}"
                f"\n\n### 反馈回路\n{feedback_text}"
                f"\n\n### 涌现属性\n{emergent_text}"
            )

        system = load_phase_prompt("rational", _RATIONAL_PROMPT)
        try:
            from .autonomy import get_autonomy_instruction
            system = system + "\n" + get_autonomy_instruction(settings.autonomy_level, "rational")
        except ImportError:
            pass
        budget = budget or {}
        from .phase_budget import budget_max_tokens, budget_depth
        from .depth import Depth
        depth = budget_depth(budget) or Depth.STANDARD
        max_tokens = budget_max_tokens(budget, getattr(self.config, "max_tokens", 8192))
        # 按深度注入输出 schema 分层说明：
        #   SHALLOW → 仅 essence；STANDARD → essence+patterns+hypotheses；
        #   DEEP → 完整 essence+hypotheses+contradiction_motion+negation_of_negation 等全字段
        _schema_scope = {
            Depth.SHALLOW: (
                "\n\n## 输出范围（本档）\n"
                "仅需输出 essence 字段，其余字段可输出空值。"
            ),
            Depth.STANDARD: (
                "\n\n## 输出范围（本档）\n"
                "输出 essence、patterns、hypotheses、synthesis_text、contradiction_motion。"
            ),
            Depth.DEEP: (
                "\n\n## 输出范围（本档）\n"
                "输出全部字段：essence、patterns、hypotheses、return_to_concrete、"
                "unexplained_phenomena、synthesis_text、contradiction_motion、"
                "quantitative_changes、qualitative_threshold、negation_of_negation、fact_foundation。"
            ),
        }.get(depth, "")
        system = system + _schema_scope
        response = await self.llm.call(
            messages=[{"role": "user", "content": user_content}],
            system=system,
            temperature=getattr(self.config, "temperature", 0.5),
            max_tokens=max_tokens,
        )

        result = self._parse(response.content)
        log.info("rational.done", n_patterns=len(result.patterns),
                 has_return_to_concrete=bool(result.return_to_concrete))
        return result

    def _parse(self, raw: str) -> RationalSynthesis:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip().rstrip("`")
        try:
            data = json.loads(raw)
            return RationalSynthesis(
                essence=data.get("essence", ""),
                patterns=data.get("patterns", []),
                hypotheses=data.get("hypotheses", []),
                synthesis_text=data.get("synthesis_text", ""),
                contradiction_motion=data.get("contradiction_motion", ""),
                quantitative_changes=data.get("quantitative_changes", []),
                qualitative_threshold=data.get("qualitative_threshold", ""),
                negation_of_negation=data.get("negation_of_negation", ""),
                fact_foundation=data.get("fact_foundation", ""),
                abstract_from=data.get("abstract_from", ""),
                return_to_concrete=data.get("return_to_concrete", ""),
                unexplained_phenomena=data.get("unexplained_phenomena", []),
            )
        except json.JSONDecodeError:
            # 保留完整原文，前端负责把可解析字段整理展示，原始内容放入可折叠区域。
            return RationalSynthesis(essence=raw, synthesis_text=raw)

    # ═══════════════════════════════════════════════════════════════════
    # I 线：理性认识深化
    # ═══════════════════════════════════════════════════════════════════

    async def deepen(
        self,
        question: str,
        previous_synthesis: RationalSynthesis,
        updated_contradiction_graph: ContradictionGraph,
        updated_fact_report: FactReport,
    ) -> RationalSynthesis:
        """
        I线：在已有理性认识基础上深化，而不是从头重新综合。
        关注：
        - 哪些本质判断被新证据支持或削弱？
        - 哪些规律需要修正边界条件？
        - 哪些假设现在可以确认或证伪？
        - 之前无法解释的现象现在能解释了吗？
        """
        log.info("rational.deepen", prev_essence=previous_synthesis.essence[:60])

        # 构造深化提示
        principal = updated_contradiction_graph.principal_contradiction
        new_facts = [
            f for f in updated_fact_report.facts
            if not any(f.content[:60] in p for p in previous_synthesis.patterns)
        ]
        new_facts_text = "\n".join(f"- {f.content[:120]}" for f in new_facts[:6])

        deepen_prompt = f"""
你正在【深化】已有的理性认识，而不是从头重新综合。

## 用户问题
{question}

## 上一轮的理性认识
- 本质判断：{previous_synthesis.essence}
- 已识别规律（{len(previous_synthesis.patterns)}条）：
{chr(10).join(f'  {i+1}. {p[:100]}' for i, p in enumerate(previous_synthesis.patterns[:5]))}
- 已有假设（{len(previous_synthesis.hypotheses)}条）：
{chr(10).join(f'  {i+1}. {h[:100]}' for i, h in enumerate(previous_synthesis.hypotheses[:5]))}
- 尚未解释的现象（{len(previous_synthesis.unexplained_phenomena)}个）：
{chr(10).join(f'  - {p[:100]}' for p in previous_synthesis.unexplained_phenomena[:3])}

## 新增事实（本轮补充调查）
{new_facts_text or '无显著新增'}

## 更新后的主要矛盾
{principal.description if principal else '未变化'}

## 你的任务

这不是重新综合——而是在原有认识基础上**加深**：

1. **本质判断的修正**：上一轮的本质判断是否需要调整？新证据支持还是削弱了它？
2. **规律的边界条件**：已识别的规律在什么条件下成立？新事实是否揭示了例外情况？
3. **假设的验证**：上一轮提出的假设，哪些现在可以确认？哪些被证伪？
4. **未解现象的突破**：之前无法解释的现象，现在能用新证据解释了吗？
5. **新的抽象层次**：是否可以在更高层次上统一之前分散的认识？

输出格式（严格 JSON）：
{{
  "abstract_from": "本轮深化从哪些新认识出发",
  "essence": "修正后的本质判断（若无需修正，复制上一轮）",
  "patterns": ["规律1（新增或修正）", "规律2（保留）"],
  "hypotheses": ["假设1（新增）", "假设2（已验证，升级为规律）"],
  "return_to_concrete": "用深化后的本质解释新观察到的具体现象",
  "unexplained_phenomena": ["仍然无法解释的现象"],
  "synthesis_text": "深化后的完整理性认识论述，说明从上一轮到本轮的认识进步",
  "contradiction_motion": "矛盾运动的新判断",
  "quantitative_changes": ["新的量变积累"],
  "qualitative_threshold": "质变条件的更新认识",
  "negation_of_negation": "螺旋路径的深化",
  "fact_foundation": "本轮深化依赖的核心新事实"
}}

只输出 JSON。
"""
        system = load_phase_prompt("rational", _RATIONAL_PROMPT)
        response = await self.llm.call(
            messages=[{"role": "user", "content": deepen_prompt}],
            system=system,
            temperature=getattr(self.config, "temperature", 0.5),
            max_tokens=getattr(self.config, "max_tokens", 8192),
        )

        result = self._parse(response.content)
        log.info("rational.deepen_done",
                 essence_changed=(result.essence != previous_synthesis.essence),
                 n_new_patterns=len(result.patterns) - len(previous_synthesis.patterns))
        return result
