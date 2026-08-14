"""
Praxic Agent —— 矛盾分析模块
核心原则：分析事物的矛盾法则，抓主要矛盾。

改造：
- 系统-矛盾交替分析。在同一个分析过程中交替深化系统建模和矛盾识别。
- 改进二：矛盾贯穿全流程 —— 矛盾是思维的操作系统
- 改进三：抽象声明 —— 从具体到抽象的自觉记录
- 改进四：推导链 —— 从事实到矛盾判断的推理过程显式化
- 改进五：矛盾特殊性 —— 此时此事此地的具体形式
"""
from __future__ import annotations

import json
import re
from typing import Optional

import structlog

from ..api.schemas.models import (
    Contradiction,
    ContradictionGraph,
    ContradictionPositionShift,
    ContradictionType,
    DerivationChain,
    DerivationStep,
    FactReport,
    SystemModel,
    SystemElement,
    SystemRelationship,
    FeedbackLoop,
    EmergentProperty,
)
from ..config import load_phase_prompt, settings
from ..llm.base import BaseLLM

log = structlog.get_logger(__name__)

def _get_default_llm():
    from ..llm import get_llm
    return get_llm()

_SYSTEM_CONTRADICTION_PROMPT = """
你正在研究用户提出的问题，当前正处于【矛盾分析】阶段。

核心信条：
- 统一物之分为两个部分以及对它的矛盾着的部分的认识，是辩证法的实质（列宁）
- 不了解矛盾的各个方面，就不能了解矛盾的总体（毛泽东）
- 系统是各要素有机联系的整体，整体功能超越孤立要素的简单总和

## 首要警戒：不要被问题的框架俘获
用户问题里出现的对立（例如"A vs B"）至多是一个候选，绝不能默认它就是主要矛盾的两极。
- 系统要素必须来自调查事实中实际起作用的所有力量，而不是用户在问题里点名的那几方
- 若背景上下文列出了"被用户框架遗漏、需纳入考察的力量/因素"，必须把它们作为候选要素一并纳入系统建模，并主动在事实中为其寻找依据
- 主要矛盾的两极由系统运动本身决定，完全可能根本不是用户设想的那一对
- 判断主要矛盾时，不得仅因"用户在问题里强调了某对张力"就默认它是主要矛盾
- 但也不必为跳出而跳出：若事实确实支持用户提出的那对张力就是主要矛盾，照实认定即可——关键是让结论由事实决定，而非由用户的提法或你的逆反决定
- 若某个关键力量在现有事实中缺乏支撑，宁可写入 uncertainty_areas 提示补充调查，也不要用用户的二元框架强行填充

## 你的任务：系统-矛盾交替分析

你的分析分为五个步骤，在同一输出中依次完成。每个步骤的结论会成为下一步的基础。

### 第一步：初步系统建模

基于调查事实，建立对所研究问题的系统认知：

1. **系统边界**：你研究的是什么系统？它的边界在哪里？什么属于系统内，什么是外部的环境？
2. **关键要素识别**：系统内有哪些关键要素？列出每个要素的名字、描述、在系统中的功能。要素来自事实中所有实际起作用的力量，不局限于用户点名的对象——主动追问：除用户提到的，还有哪些群体／机构／外部行动者在影响系统？
3. **初步关系图谱**：要素之间存在哪些关系？
   - 关系类型：依存（dependency）、供养（supply）、调节（regulation）、对抗（antagonism）、级联（cascade）、协同（synergy）
4. **涌现属性**：系统整体表现出了哪些单个要素没有的属性？
5. **反馈结构**：识别系统内的正反馈和负反馈回路

### 第二步：在系统框架下识别矛盾（含特殊性和推导链）

现在基于系统模型，分析系统内部的矛盾结构：

1. **矛盾定位**：第一步识别的"对抗型关系"中，哪些构成了真正的矛盾？
2. **矛盾在系统中的位置**：每个矛盾处于什么反馈回路中？
3. **矛盾的系统驱动力**：结构性的、周期性的、还是过渡性的？
4. **抓主要矛盾**：哪一对矛盾是主要矛盾？判断标准不是"哪对张力最大"，而是"哪对矛盾的运动会带动系统整体变化"。
5. **矛盾的主要方面**：每个矛盾中，哪一方当前居于主导地位？
6. **转化条件**：在什么条件下矛盾的次要方面会上升为主要方面？

#### 矛盾的特殊性（CRITICAL）

在识别每一个矛盾时，你必须回答一个问题：
**这个矛盾在此时此事此地的具体形式是什么？**

"外交象征性 vs 实质性结果"可以用在2017年、2024年任何外国领导人访华——这不是特殊性。
特殊性要求你回答：
- **时间特殊性**：当前历史阶段的什么特征使这个矛盾表现为现在的样子？
- **对象特殊性**：矛盾涉及的主体有什么独特性？
- **环境特殊性**：外部条件有什么独特性使这个矛盾此时激化（或缓和）？

每个矛盾的 particularity_description 必须包含上述三个维度的具体说明（200字）。

#### 推导链记录（CRITICAL）

对于主要矛盾和每个次要矛盾，你必须记录从具体事实到矛盾判断的推导过程。
这不是形式要求——推导链让推理可追溯、可检验、可修正。

每个矛盾的 derivation_chain 包含：
- chain_id：推导链标识（如"c1"）
- summary：整体推导逻辑概述（100字）
- factual_foundation：核心依赖的事实ID列表
- steps：2-5步推理，每一步包含：
  * step_id：步骤标识
  * fact_basis：此步依赖的事实ID列表
  * inference：推理过程（从事实中如何得出此结论，具体推理而非泛泛而谈）
  * conclusion：中间结论
  * confidence：此步推理的置信度（0.0~1.0）
  * reversible：如果新事实出现，此结论是否可被推翻

### 第三步：系统模型修正

矛盾分析会暴露第一步系统建模的不足：
1. 新发现的要素 2. 关系修正 3. 边界调整
4. 涌现属性与矛盾的关联 5. 反馈回路修正

### 第四步：抽象声明 —— 从具体到抽象的自觉记录

在进行深层综合之前，你必须明确记录你从调查事实中"抽象"了什么：

- **保留了哪些事实**：在矛盾分析中，哪些具体事实被保留为核心判断依据？
- **舍弃了哪些细节**：哪些细节在抽象过程中被有意舍弃？为什么它们不是本质的？
- **上升到了什么**：通过舍弃次要细节、保留核心关系，得出了什么更一般的认识？
- **抽象的风险**：这种抽象可能遗漏什么？有没有事实因为"不够典型"被忽略了？

（这些内容纳入 synthesis 字段中，不单独输出。）

### 第五步：深层结构综合

1. **系统-矛盾统一**：系统结构和矛盾运动如何统一？
2. **系统运动全景**（synthesis）：用系统+矛盾的视角，描述整个系统的当前状态和运动趋势
3. **转化路径**（dynamic_note）：系统在什么条件下会发生结构性质变？

## 输出格式

CRITICAL: 只输出 JSON，不要任何其他文字。

### 字段分层（重要）

本阶段输出分为两层，职责不同：
- **结论层**（对外结论，必出）：`principal_contradiction`、`secondary_contradictions`、`dynamic_note`、`synthesis`。这些是要交给下游阶段和最终回答使用的结论。
- **推理层**（内部推理支撑，按档位输出）：每条矛盾内的 `derivation_chain`、`system_model`、`contradiction_derivation`。它们说明“为什么这样判断”，用于检验与增量维护，不直接对外。

当前档位要求哪种输出范围，以输出范围指令为准（见 system 提示末尾“## 输出范围（本档）”）。若本档为 STANDARD/SHALLOW，推理层字段必须置为 null/空，不要生成；若为 DEEP，则完整输出。

{
  "system_model": {
    "system_boundary": "系统边界描述，100-200字",
    "external_environment": "外部环境特征",
    "elements": [
      {
        "name": "要素名称",
        "description": "要素描述",
        "function_in_system": "该要素在系统中的功能",
        "property_outside_system": "脱离系统后属性变化",
        "based_on_fact_ids": ["f1", "f3"]
      }
    ],
    "relationships": [
      {
        "source_element": "A",
        "target_element": "B",
        "relationship_type": "dependency",
        "description": "关系说明",
        "direction": "unidirectional",
        "intensity": "strong",
        "is_contradiction_source": false,
        "based_on_fact_ids": ["f2"]
      }
    ],
    "feedback_loops": [
      {
        "description": "回路描述",
        "loop_type": "positive",
        "elements_involved": ["A", "B"],
        "mechanism": "反馈机制说明",
        "effect_on_system": "对系统整体行为的影响"
      }
    ],
    "emergent_properties": [
      {
        "property_name": "涌现属性",
        "description": "属性描述",
        "emerges_from": ["A", "B"],
        "cannot_be_reduced_to": "为什么不能还原为单个要素的属性",
        "based_on_fact_ids": ["f5"]
      }
    ],
    "uncertainty_areas": ["要素X和要素Y的关系缺乏足够事实支撑"]
  },

  "principal_contradiction": {
    "description": "深度分析（2-3句）——在系统框架下，这个矛盾是什么，涉及哪些要素，如何驱动系统运动",
    "tension_poles": ["矛盾一方", "矛盾另一方"],
    "contradiction_type": "internal",
    "rank": 1,
    "primary_aspect": "当前主要方面",
    "transformation_condition": "转化条件——从系统角度看，什么改变了这个矛盾的一方就会变为另一方？",
    "basis_fact_ids": ["f1", "f3"],
    "basis_summary": "这个矛盾判断基于哪些事实",
    "involving_elements": ["核心维护者", "贡献者"],
    "position_in_feedback": "这个矛盾处于什么反馈回路中，正反馈还是负反馈，对矛盾趋势的影响",
    "systemic_drive": "结构性的/周期性的/过渡性的——矛盾的系统驱动力类型",
    "particularity_description": "矛盾的特殊性——这个矛盾在此时此事此地的具体形式。时间特殊性+对象特殊性+环境特殊性，200字",
    "derivation_chain": {
      "chain_id": "c1",
      "summary": "从事实到主要矛盾判断的整体推导逻辑",
      "factual_foundation": ["f1", "f3", "f7"],
      "steps": [
        {
          "step_id": "c1_step1",
          "fact_basis": ["f1", "f3"],
          "inference": "从F1观察到A和B之间的此消彼长关系，F3进一步证明这种关系在多个时间点上持续存在，因此A和B之间存在系统的而非偶然的对立",
          "conclusion": "A和B构成一个矛盾对——它们相互依存又相互排斥",
          "confidence": 0.85,
          "reversible": true
        },
        {
          "step_id": "c1_step2",
          "fact_basis": ["f5", "f7"],
          "inference": "...",
          "conclusion": "这个矛盾对驱动了系统的主要变化，因此是主要矛盾",
          "confidence": 0.75,
          "reversible": true
        }
      ]
    }
  },

  "secondary_contradictions": [
    {
      "description": "...",
      "tension_poles": ["...", "..."],
      "contradiction_type": "internal",
      "rank": 2,
      "primary_aspect": "...",
      "transformation_condition": "...",
      "basis_fact_ids": [],
      "basis_summary": "",
      "involving_elements": ["要素A", "要素B"],
      "position_in_feedback": "...",
      "systemic_drive": "周期性的",
      "particularity_description": "此矛盾的特殊性",
      "derivation_chain": {
        "chain_id": "c2",
        "summary": "...",
        "factual_foundation": ["f4", "f6"],
        "steps": [
          {
            "step_id": "c2_step1",
            "fact_basis": ["f4"],
            "inference": "...",
            "conclusion": "...",
            "confidence": 0.8,
            "reversible": true
          }
        ]
      }
    }
  ],

  "dynamic_note": "从系统运动角度看矛盾的动态变化——矛盾是激化、缓和还是转化？反馈回路在加速还是抑制？200字",
  "synthesis": "系统-矛盾统一的整体描述。含抽象声明（保留了哪些事实、舍弃了哪些细节、上升到了什么认识、抽象的风险）。300-400字"
}

## 分析质量要求

1. 所有判断都要有事实基础。如果某个要素/关系/矛盾缺乏调查事实支撑，标注在 uncertainty_areas 中，不要臆造。
2. 要素数量控制在 3-8 个。
3. 涌现属性必须解释为什么不能还原。
4. 主要矛盾要回答"为什么是主要的"——必须论证它对系统运动的驱动力。
5. 矛盾特殊性必须是具体的，不能是通用公式。"理想vs现实"、"效率vs公平"这类通用对子必须辅以此时此事此地的具体内容。
6. 推导链的每一步 inference 必须是具体的推理——"因为F1和F3显示..."，而不是"综合考虑..."。

只输出 JSON。
"""


class ContradictionAnalyzer:
    """矛盾分析模块 —— 系统-矛盾交替分析"""

    def __init__(
        self,
        llm: Optional[BaseLLM] = None,
        phase_config: Optional[dict] = None,
    ):
        self.llm = llm or _get_default_llm()
        self.config = phase_config or {}

    async def analyze(
        self,
        fact_report: FactReport,
        question: str,
        rational_context: str = "",
        additional_context: str = "",
        budget: dict = None,
    ) -> ContradictionGraph:
        log.info("contradiction.start", n_facts=len(fact_report.facts))

        facts_text = "\n".join(
            f"- [可信度:{f.credibility:.2f}] {f.content}" for f in fact_report.facts
        )
        user_content = f"""## 用户问题
{question}

## 已调查的事实
{facts_text}

## 调查摘要
{fact_report.summary}
"""
        # 改进一：如有解剖麻雀的结果，注入
        if fact_report.illustrative_case:
            ic = fact_report.illustrative_case
            user_content += f"""
## 解剖麻雀 —— 典型案例
案例名称：{ic.name}
案例描述：{ic.description}
为什么典型：{ic.why_typical}
纵深分析：{ic.deep_analysis}
揭露的矛盾：{", ".join(ic.contradictions_revealed)}
可推广认识：{ic.lessons_generalizable}
"""
        if rational_context:
            user_content += f"\n## 已有的理性认识上下文\n{rational_context}"
        if additional_context:
            user_content += f"\n## 背景上下文（含被用户框架遗漏、需纳入系统要素一并考察的力量/因素）\n{additional_context}"

        system = load_phase_prompt("contradiction", _SYSTEM_CONTRADICTION_PROMPT)
        try:
            from .autonomy import get_autonomy_instruction
            system = system + "\n" + get_autonomy_instruction(settings.autonomy_level, "contradiction")
        except ImportError:
            pass
        temperature, max_tokens, depth, scope_note = self._resolve_budget(budget)
        system = system + scope_note

        response = await self.llm.call(
            messages=[{"role": "user", "content": user_content}],
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        graph = self._parse_response(response.content)
        # B方案：思维链仅供展示，随图存储，不进后续输入
        graph.thinking_trace = (response.metadata or {}).get("reasoning", "")
        # C3：DEEP 要求完整 system_model，缺失时 log warning（不崩溃，走既有 fallback）
        from .depth import Depth
        if depth == Depth.DEEP and graph.system_model is None:
            log.warning("contradiction.schema_level_missing_system_model", depth="deep")
        log.info(
            "contradiction.done",
            has_principal=graph.principal_contradiction is not None,
            n_secondary=len(graph.secondary_contradictions),
            has_system_model=graph.system_model is not None,
            n_elements=len(graph.system_model.elements) if graph.system_model else 0,
            has_derivation=graph.principal_contradiction.derivation_chain is not None
                if graph.principal_contradiction else False,
        )
        return graph

    def _resolve_budget(self, budget: dict) -> tuple:
        """
        解析阶段预算 budget，返回 (temperature, max_tokens, depth, schema_scope_note)。
        供 analyze 与 maintain_contradictions 共用，保证两路径的 depth/schema 分层一致。
        """
        from .phase_budget import budget_max_tokens, budget_depth
        from .depth import Depth
        temperature = getattr(self.config, "temperature", 0.3)
        max_tokens = getattr(self.config, "max_tokens", 16384)
        budget = budget or {}
        depth = budget_depth(budget) or Depth.STANDARD
        max_tokens = budget_max_tokens(budget, max_tokens)
        # B方案：STANDARD 档正文只出结论层，但 thinking 模式默认开启，
        # DeepSeek 的 max_tokens 同时承载思维链 + 正文，必须给足（实测思维链 8k~14k）。
        if depth == Depth.STANDARD and max_tokens < 16384:
            max_tokens = 16384
        # 按深度注入输出 schema 分层说明（B方案：结论层与推理层分离）：
        #   SHALLOW → 仅 principal_contradiction；
        #   STANDARD → 结论层全量（principal+secondary+dynamic_note+synthesis），推理层留空；
        #   DEEP → 结论层 + 推理层全量（system_model + derivation_chain + contradiction_derivation）
        _schema_scope = {
            Depth.SHALLOW: (
                "\n\n## 输出范围（本档）\n"
                "仅需输出 principal_contradiction（不含 derivation_chain），"
                "secondary_contradictions、system_model、contradiction_derivation 全部留空。"
            ),
            Depth.STANDARD: (
                "\n\n## 输出范围（本档）\n"
                "只输出结论层：principal_contradiction、secondary_contradictions、dynamic_note、synthesis。"
                "不要输出推理层——derivation_chain（每条矛盾内）、system_model、contradiction_derivation "
                "均为内部推理支撑，本档一律置为 null/空，不生成。"
            ),
            Depth.DEEP: (
                "\n\n## 输出范围（本档）\n"
                "输出结论层（principal_contradiction、secondary_contradictions、dynamic_note、synthesis）"
                "与完整推理层：system_model（elements/relationships/feedback_loops/emergent_properties）"
                "、每条矛盾的 derivation_chain（每步给出具体推理）与整体 contradiction_derivation。"
            ),
        }.get(depth, "")
        return temperature, max_tokens, depth, _schema_scope

    def _parse_response(self, raw: str) -> ContradictionGraph:
        original = raw
        raw = raw.strip()

        data = None

        cleaned = raw
        while cleaned.startswith("```"):
            idx = cleaned.find("\n")
            cleaned = cleaned[idx+1:] if idx >= 0 else ""
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip().rstrip("`")

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        if data is None:
            data = self._extract_json_from_prose(raw)

        if data is None:
            return self._prose_fallback(original)

        # Parse system_model
        system_model = None
        sm_data = data.get("system_model")
        if sm_data and isinstance(sm_data, dict):
            try:
                system_model = SystemModel(
                    system_boundary=sm_data.get("system_boundary", ""),
                    external_environment=sm_data.get("external_environment", ""),
                    elements=[
                        SystemElement(
                            name=e.get("name", ""),
                            description=e.get("description", ""),
                            function_in_system=e.get("function_in_system", ""),
                            property_outside_system=e.get("property_outside_system", ""),
                            based_on_fact_ids=e.get("based_on_fact_ids", []),
                        )
                        for e in sm_data.get("elements", [])
                    ],
                    relationships=[
                        SystemRelationship(
                            source_element=r.get("source_element", ""),
                            target_element=r.get("target_element", ""),
                            relationship_type=r.get("relationship_type", ""),
                            description=r.get("description", ""),
                            direction=r.get("direction", "bidirectional"),
                            intensity=r.get("intensity", "medium"),
                            is_contradiction_source=r.get("is_contradiction_source", False),
                            based_on_fact_ids=r.get("based_on_fact_ids", []),
                        )
                        for r in sm_data.get("relationships", [])
                    ],
                    feedback_loops=[
                        FeedbackLoop(
                            description=f.get("description", ""),
                            loop_type=f.get("loop_type", "positive"),
                            elements_involved=f.get("elements_involved", []),
                            mechanism=f.get("mechanism", ""),
                            effect_on_system=f.get("effect_on_system", ""),
                        )
                        for f in sm_data.get("feedback_loops", [])
                    ],
                    emergent_properties=[
                        EmergentProperty(
                            property_name=ep.get("property_name", ""),
                            description=ep.get("description", ""),
                            emerges_from=ep.get("emerges_from", []),
                            cannot_be_reduced_to=ep.get("cannot_be_reduced_to", ""),
                            based_on_fact_ids=ep.get("based_on_fact_ids", []),
                        )
                        for ep in sm_data.get("emergent_properties", [])
                    ],
                    uncertainty_areas=sm_data.get("uncertainty_areas", []),
                )
            except Exception as e:
                log.warning("contradiction.system_model_parse_error", error=str(e))

        # Parse derivation chain helper
        def _parse_derivation_chain(dc_data: dict) -> Optional[DerivationChain]:
            if not dc_data or not isinstance(dc_data, dict):
                return None
            try:
                return DerivationChain(
                    chain_id=dc_data.get("chain_id", ""),
                    summary=dc_data.get("summary", ""),
                    factual_foundation=dc_data.get("factual_foundation", []),
                    steps=[
                        DerivationStep(
                            step_id=s.get("step_id", ""),
                            fact_basis=s.get("fact_basis", []),
                            inference=s.get("inference", ""),
                            conclusion=s.get("conclusion", ""),
                            confidence=s.get("confidence", 0.7),
                            reversible=s.get("reversible", True),
                        )
                        for s in dc_data.get("steps", [])
                    ],
                    generated_at_iteration=0,
                )
            except Exception:
                return None

        # Parse contradictions with new fields
        def _parse_c(d: dict, default_rank: int = 1) -> Contradiction:
            ctype_raw = d.get("contradiction_type", "internal")
            try:
                ctype = ContradictionType(ctype_raw)
            except ValueError:
                ctype = ContradictionType.INTERNAL
            return Contradiction(
                description=d.get("description", ""),
                tension_poles=d.get("tension_poles", []),
                contradiction_type=ctype,
                rank=d.get("rank", default_rank),
                primary_aspect=d.get("primary_aspect", ""),
                transformation_condition=d.get("transformation_condition", ""),
                basis_fact_ids=d.get("basis_fact_ids", []),
                basis_summary=d.get("basis_summary", ""),
                involving_elements=d.get("involving_elements", []),
                position_in_feedback=d.get("position_in_feedback", ""),
                systemic_drive=d.get("systemic_drive", ""),
                particularity_description=d.get("particularity_description", ""),
                derivation_chain=_parse_derivation_chain(d.get("derivation_chain")),
            )

        principal = None
        if data.get("principal_contradiction"):
            principal = _parse_c(data["principal_contradiction"], 1)

        secondary = [
            _parse_c(c, i + 2)
            for i, c in enumerate(data.get("secondary_contradictions", []))
        ]

        # Parse overall contradiction_derivation
        contradiction_derivation = _parse_derivation_chain(data.get("contradiction_derivation"))

        return ContradictionGraph(
            principal_contradiction=principal,
            secondary_contradictions=secondary,
            dynamic_note=data.get("dynamic_note", ""),
            synthesis=data.get("synthesis", ""),
            system_model=system_model,
            contradiction_derivation=contradiction_derivation,
        )

    def _extract_json_from_prose(self, raw: str) -> Optional[dict]:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        candidate = raw[start:end+1]
        for suffix in ["}", "}]}", "]}]}", "}]}]}", "}\n}", "]", "]}]"]:
            try:
                return json.loads(candidate + suffix)
            except json.JSONDecodeError:
                continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None

    def _prose_fallback(self, raw: str) -> ContradictionGraph:
        log.info("contradiction.prose_fallback", len_raw=len(raw))
        contradictions = []
        pattern = r'(?:矛盾\s*\d+[：:]|主要矛盾[：:]|次要矛盾[：:])\s*(.+?)(?=(?:矛盾\s*\d+[：:]|主要矛盾[：:]|次要矛盾[：:]|$))'
        matches = re.findall(pattern, raw, re.DOTALL)

        if not matches:
            return ContradictionGraph(
                synthesis=raw[:1000],
                dynamic_note="矛盾分析以散文形式返回，已提取原文作为综合描述",
                principal_contradiction=Contradiction(
                    description=raw[:300],
                    tension_poles=["散文输出——未提取到结构化矛盾"],
                    contradiction_type=ContradictionType.INTERNAL,
                    rank=1,
                )
            )

        for i, m in enumerate(matches):
            m_clean = re.sub(r'\s+', ' ', m.strip())[:300]
            contradictions.append(Contradiction(
                description=m_clean,
                tension_poles=["详见原文"],
                contradiction_type=ContradictionType.SECONDARY,
                rank=i + 1,
            ))

        return ContradictionGraph(
            principal_contradiction=contradictions[0] if contradictions else None,
            secondary_contradictions=contradictions[1:] if len(contradictions) > 1 else [],
            dynamic_note="从散文输出中提取矛盾结构",
            synthesis=raw[:500],
        )

    # ═══════════════════════════════════════════════════════════════════
    # I 线：迭代增量维护方法
    # ═══════════════════════════════════════════════════════════════════

    def _fork_derivation_chain(
        self,
        chain: DerivationChain,
        revised_step_index: int,
        revision_reason: str,
        new_step_content: dict,
    ) -> DerivationChain:
        """
        Fork 一条推导链：在 revised_step_index 处做修正，
        返回新链（parent_chain_id 指向原链）。
        同时将依赖被修正步骤的后续步骤标记为 needs_revalidation。
        """
        revised_step = chain.steps[revised_step_index]
        new_steps = []
        for i, step in enumerate(chain.steps):
            if i < revised_step_index:
                new_steps.append(step)
            elif i == revised_step_index:
                new_steps.append(DerivationStep(
                    step_id=f"{step.step_id}_r",
                    fact_basis=new_step_content.get("fact_basis", step.fact_basis),
                    inference=new_step_content.get("inference", step.inference),
                    conclusion=new_step_content.get("conclusion", step.conclusion),
                    confidence=new_step_content.get("confidence", step.confidence),
                    reversible=new_step_content.get("reversible", step.reversible),
                    depends_on_step_ids=step.depends_on_step_ids,
                    needs_revalidation=False,
                ))
            else:
                # 后续步骤：若依赖被修正步骤，标记为 needs_revalidation
                needs_reval = revised_step.step_id in step.depends_on_step_ids
                new_steps.append(step.model_copy(
                    update={"needs_revalidation": needs_reval}
                ))

        import uuid
        return DerivationChain(
            chain_id=str(uuid.uuid4())[:8],
            summary=chain.summary,
            steps=new_steps,
            factual_foundation=chain.factual_foundation,
            parent_chain_id=chain.chain_id,
            revision_reason=revision_reason,
        )

    async def maintain_contradictions(
        self,
        previous_graph: ContradictionGraph,
        updated_fact_report: FactReport,
        question: str,
        challenged_indices: list[int] = None,
        budget: dict = None,
    ) -> ContradictionGraph:
        """
        I线：增量维护矛盾图：
        - 未被挑战的矛盾：retain（保留，仅追加 basis_fact_ids）
        - 被挑战的矛盾：refine（深化 particularity_description，fork derivation_chain）
        - 新增矛盾：append

        同时检测矛盾地位转换事件（contradiction_position_shifts）。
        """
        log.info("contradiction.maintain", n_challenged=len(challenged_indices or []))

        challenged_indices = challenged_indices or []
        challenged_descs = [
            previous_graph.all_contradictions[i].description[:100]
            for i in challenged_indices
            if i < len(previous_graph.all_contradictions)
        ]

        # 构造维护提示
        existing_summary = "\n".join(
            f"[{'主要' if c == previous_graph.principal_contradiction else '次要'}矛盾] "
            f"{c.description[:150]}\n  推导摘要：{c.derivation_chain.summary[:100] if c.derivation_chain else '无'}"
            for c in previous_graph.all_contradictions
        )
        new_facts_text = "\n".join(
            f"- [NEW] {f.content[:120]}"
            for f in updated_fact_report.facts
            if not any(f.content[:60] in c.description for c in previous_graph.all_contradictions)
        )
        challenged_text = "\n".join(f"- {d}" for d in challenged_descs) or "无"

        maintain_prompt = f"""
你正在【维护】一个已有的矛盾分析结果，而不是重新做矛盾分析。

## 原有矛盾结构
{existing_summary}

## 新增事实（本轮补充调查产出）
{new_facts_text or '无'}

## 被挑战的矛盾（需要深化分析）
{challenged_text}

## 输出范围说明

本档输出范围由 system 提示末尾的“## 输出范围（本档）”指令决定。
- 若为 STANDARD/SHALLOW：只输出结论层，推理层（derivation_chain / system_model / contradiction_derivation）一律 null/空。Refine 的推导深化体现到结论层字段（description、particularity_description、basis_summary、transformation_condition 的更新）上。
- 若为 DEEP：输出结论层与完整推理层，被挑战矛盾的推导链按 fork 规则处理。

## 你的任务

1. **Retain（保留）**：未被挑战且新事实不影响的矛盾——保持描述不变，仅补充新的basis_fact_ids
2. **Refine（深化）**：被挑战的矛盾或被新事实显著影响的矛盾：
   - 更新 particularity_description（此时此地的具体形式）
   - 在现有推导链的基础上 fork：说明哪一步被修正了，为什么，新结论是什么
   - 注意：不是重写矛盾，是在原有认识基础上加深
3. **Append（新增）**：若新事实揭示了原来没有识别到的矛盾，追加新矛盾
4. **Position shift（地位转换）**：判断是否有次要矛盾应该提升为主要矛盾，或主要矛盾降为次要。如有，记录转化条件。

输出格式（严格 JSON）与正常矛盾分析相同，额外增加：
{{"retained_contradiction_ids": ["description前60字..."],
  "position_shifts": [
    {{
      "from_role": "secondary",
      "to_role": "principal",
      "contradiction_description": "...",
      "trigger_facts": ["..."],
      "transformation_condition_met": "..."
    }}
  ]
}}
"""
        system = load_phase_prompt("contradiction", _SYSTEM_CONTRADICTION_PROMPT)
        # 本档输出范围说明：与 analyze 共用 depth/schema 分层规则。
        temperature, max_tokens, _depth, _scope_note = self._resolve_budget(budget)
        response = await self.llm.call(
            messages=[{"role": "user", "content": maintain_prompt + f"\n\n问题：{question}"}],
            system=system + _scope_note,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        new_graph = self._parse_response(response.content)
        # B方案：思维链仅供展示，随图存储，不进后续输入
        new_graph.thinking_trace = (response.metadata or {}).get("reasoning", "")

        # 处理推导链 fork（被挑战矛盾）
        for i, c in enumerate(new_graph.all_contradictions):
            if i < len(previous_graph.all_contradictions):
                prev_c = previous_graph.all_contradictions[i]
                if c.derivation_chain and prev_c.derivation_chain:
                    if c.derivation_chain.summary != prev_c.derivation_chain.summary:
                        # 推导结论变化了——设置parent_chain_id
                        c.derivation_chain.parent_chain_id = prev_c.derivation_chain.chain_id
                        c.derivation_chain.revision_reason = f"第{previous_graph.iteration + 1}轮深化"
                    else:
                        # 结论未变——保留原链ID
                        c.derivation_chain.chain_id = prev_c.derivation_chain.chain_id

        # 解析并附加 position_shifts
        try:
            raw = response.content
            # 从已解析的 new_graph 中提取 position_shifts（由 _parse_response 忽略的额外字段）
            raw_clean = raw.strip()
            if raw_clean.startswith("```"):
                raw_clean = raw_clean.split("```")[1]
                if raw_clean.startswith("json"):
                    raw_clean = raw_clean[4:]
            raw_clean = raw_clean.strip().rstrip("`")
            data = json.loads(raw_clean)
            for ps_data in data.get("position_shifts", []):
                new_graph.position_shifts.append(ContradictionPositionShift(
                    from_role=ps_data.get("from_role", ""),
                    to_role=ps_data.get("to_role", ""),
                    contradiction_description=ps_data.get("contradiction_description", ""),
                    trigger_facts=ps_data.get("trigger_facts", []),
                    trigger_iteration=previous_graph.iteration + 1,
                    transformation_condition_met=ps_data.get("transformation_condition_met", ""),
                ))
        except Exception:
            pass

        # 继承历史 position_shifts（累积记录）
        new_graph.position_shifts = (previous_graph.position_shifts or []) + new_graph.position_shifts
        new_graph.iteration = previous_graph.iteration + 1

        log.info("contradiction.maintain_done",
                 n_shifts=len(new_graph.position_shifts),
                 n_contradictions=len(new_graph.all_contradictions))
        return new_graph
