'''Praxic Agent -- 反思引擎（基于实践结果的全流程复盘 + 流程控制）'''
from __future__ import annotations
import json
from typing import Optional
import structlog
from ..api.schemas.models import CognitiveTrace, ReflectionReport
from ..config import load_phase_prompt
from ..llm.base import BaseLLM

log = structlog.get_logger(__name__)

_REFLECTION_PROMPT = '''
你正在研究用户提出的问题，当前正处于【反思】阶段。
核心信条：实践是检验真理的唯一标准。
在本轮认知循环结束后，你要基于实践检验的结果，对整条认知轨迹进行全流程复盘：
哪些结论被实践验证了？哪些被削弱了？接下来应该怎么做？

核心原则：实践是检验真理的唯一标准。通过实践结果检验认识，修正认识，再回到实践。

你的任务：
1. 基于实践结果，复盘调查研究：哪些事实关键，哪些被高估/低估？信息缺口是否被实践填补？
2. 检验矛盾分析是否准确：主要矛盾识别对了吗？实践中有没有暴露新的矛盾？
3. 评估决策质量：哪些行动项经受住了实践检验？哪些被实践证伪？
4. 解读实践分析：实践结论（confirmed/challenged/falsified）说明什么？可信度如何变化？
5. 识别认知偏差和逻辑漏洞
6. 总结可复用的经验教训
7. 判断是否需要触发新一轮调查研究，以及收敛度（0.0~1.0）
   7a. 参考下方【终止判定参考数据】中的子问题覆盖、决策验证、矛盾状态数据——
       这些数据是系统自动收集的结构性事实（非LLM产出），
       用来帮助判断收敛度，但不构成刚性规则。
       如果有未覆盖的子问题但对最终回答不关键，可以不把它当作继续的理由。
8. 如果实践阶段产出的是【知性分析（边界模式）】而非执行验证：
   - 收敛评分应更保守（偏低 0.1-0.2）
   - 主动关注：哪些主张被评估为"challenged"？它们是否影响决策方向？
   - 在 focus_hints 中为下一轮 practice 阶段标注：
     "如果用户能提供真实数据或试验结果，应优先将其注入实践阶段"
   - 重要：边界模式下，调查/矛盾分析/理性认识本身就是认知工作的核心产出，
     不要因为实践阶段无法执行代码而否定前序阶段的认知成果。
     评估收敛度时，重点看矛盾是否清晰、理性认识是否自洽、决策是否有据，
     而非实践是否产生了可观测结果。
9. **矛盾追踪**：比较本轮各阶段的矛盾判断
    - 主要矛盾是否发生了变化？是否有矛盾被实践证伪或削弱？
    - 如果有 contradiction_feedback（实践对矛盾分析的反馈），重点讨论：
      哪些矛盾判断被实践支持？哪些被削弱？是否暴露了新矛盾？
    - 矛盾的转化是否在发生？哪些条件在推动？
    - 矛盾判断的演变说明认识在进步还是退步？
10. 【最终回答】如果判断无需重新调查（should_reinvestigate=false），
   你必须为用户提供一个全面的最终回答（final_answer）：
   - 综合调查研究的事实基础（不要跳过事实）
   - 体现矛盾分析的结构（什么矛盾推动了事物的运动？）
   - 纳入理性认识的本质和规律（透过现象看本质）
   - 结合决策的方向和建议（应该怎么做）
   - 诚实标注哪些部分已经过实践检验、哪些仍属于知性推断
   - 如果实践阶段为边界模式，明确指出：
     "以下分析基于调查搜索和矛盾分析，属于知性认识层面。
     由于该问题无法通过代码实验验证，建议用户在现实中通过[具体方式]进一步检验。"
   - final_answer 应为自然段落，300-800字，直接面向用户回答其原始问题
   - recommend_detailed_report：若本问题值得一份更详实的报告式回答（探索理解/因果解释类、涉及多方面复杂分析、且收敛度较高）则设为 true；若问题简单（单一事实/单一行动）则为 false

新增任务：矛盾稳定性与认识层次评估
- contradiction_stability（0~1）：若上一轮也有矛盾分析，比较两轮主要矛盾判断的一致性
- contradiction_shift_detected：本轮矛盾结构是否发生了质变
- understanding_level：本轮认识层次（"感性"/"知性"/"理性"）
- qualitative_leap：是否发生了认识层次的跃升

流程控制权限（保守原则）：
- skip_phases：仅当某阶段结论已充分稳固时才建议跳过
  重要：如果 should_reinvestigate=true（需要重新调查），则禁止在 skip_phases 中加入 "practice"。
  逻辑是：重新调查意味着新事实新矛盾，上一轮的实践结论随之过时，
  新一轮决策会产生新的行动项，它们需要新的实践检验。
- focus_hints：下一轮该阶段执行时额外收到的专项提示
- recommended_mode：建议运行模式 fast/standard/deep，留空=保持当前

输出格式（严格JSON）：
{
  "quality_assessment": "整体质量评估（含0-10评分）",
  "investigation_retrospective": "调查研究复盘",
  "contradiction_retrospective": "矛盾分析复盘",
  "decision_retrospective": "决策质量复盘",
  "practice_retrospective": "实践检验复盘——结果是否验证了前序结论？",
  "cognitive_biases_found": ["偏差1"],
  "lessons_learned": ["经验1"],
  "should_reinvestigate": false,
  "reinvestigation_focus": "若需重新调查的方向",
  "convergence_score": 0.85,
  "contradiction_stability": 0.85,
  "contradiction_shift_detected": false,
  "contradiction_shift_description": "",
  "understanding_level": "知性",
  "qualitative_leap": false,
  "level_progression": "",
  "skip_phases": [],
  "focus_hints": {"investigation": "..."},
  "recommended_mode": "",
  "final_answer": "（如果 should_reinvestigate=false，则填写300-800字面向用户的全面回答；否则留空字符串）",
  "recommend_detailed_report": false,
  "skill_draft_candidates": [
    注释：仅当满足所有条件时才填充（否则返回 []）：
    条件1: convergence_score >= 0.65
    条件2: should_reinvestigate = false
    条件3: 本轮实践阶段有成功执行的步骤
    如果满足条件，从本轮认知循环中提取可复用的操作模式：
    {
      "suggested_name": "技能名（英文小写连字符分隔）",
      "suggested_description": "一句话描述（中文）",
      "suggested_type": "execution 或 methodology",
      "suggested_active_phases": ["practice"],
      "trigger_pattern": "什么情况下应触发此技能（中文）",
      "core_operations": "核心步骤（中文，3-5步）",
      "confidence": 0.7
    }
  ]
}
只输出JSON。
'''


class ReflectionEngine:
    """反思引擎 -- 基于实践结果对全流程复盘"""

    def __init__(self, llm: Optional[BaseLLM] = None, phase_config=None):
        if llm is None:
            from ..llm import get_llm
            llm = get_llm()
        self.llm = llm
        self.config = phase_config or {}

    async def reflect(self, question: str, trace: CognitiveTrace, user_feedback: str = "", termination_evidence: dict = None) -> ReflectionReport:
        log.info("reflection.start")
        trace_summary = self._summarize_trace(trace)
        user_content = f"## 原始问题\n{question}\n\n## 认知轨迹摘要\n{trace_summary}"
        
        # ── 终止判定参考数据（由系统自动收集，非LLM产出）──
        if termination_evidence:
            user_content += "\n\n" + self._format_termination_evidence(termination_evidence)
        if user_feedback:
            user_content += f"\n## 用户反馈\n{user_feedback}"

        system = load_phase_prompt("reflection", _REFLECTION_PROMPT)
        temperature = getattr(self.config, "temperature", 0.4)
        max_tokens = getattr(self.config, "max_tokens", 2048)

        response = await self.llm.call(
            messages=[{"role": "user", "content": user_content}],
            system=system, temperature=temperature, max_tokens=max_tokens,
        )
        report = self._parse_response(response.content)
        log.info("reflection.done",
                 should_reinvestigate=report.should_reinvestigate,
                 convergence=report.convergence_score)
        return report


    @staticmethod
    def _format_termination_evidence(evidence: dict) -> str:
        """将结构性终止证据格式化为 Reflection prompt 段"""
        lines = ["## 终止判定参考数据",
                 "以下数据由系统自动收集（非LLM产出），供你判定 should_reinvestigate 时参考。",
                 "这些数据不构成刚性规则——你可以判断某条'未覆盖'对最终回答不重要。"]
        
        sq = evidence.get("sub_question_coverage")
        if sq:
            lines.append(f"\n### 子问题覆盖：{sq['covered']}/{sq['total']} 已覆盖")
            if sq.get("uncovered_list"):
                for u in sq["uncovered_list"]:
                    lines.append(f"  - [未覆盖] {u}")
        
        av = evidence.get("action_verification")
        if av:
            lines.append(f"\n### 决策验证：{av['verified']}/{av['total']} 已验证")
            if av.get("unverified_list"):
                for u in av["unverified_list"]:
                    lines.append(f"  - [未验证] {u}")
            if av.get("unverifiable_list"):
                for u in av["unverifiable_list"]:
                    lines.append(f"  - [需人工] {u['item']}（{u['why']}）")
        
        cs = evidence.get("contradiction_status")
        if cs:
            lines.append(f"\n### 矛盾状态：{cs['resolved']}/{cs['total']} 已解决")
            if cs.get("pending_list"):
                for p in cs["pending_list"]:
                    lines.append(f"  - [待解决] {p['contradiction']}（{p['reason']}）")
        
        lines.append("\n请在判断 should_reinvestigate 时综合考虑以上数据。")
        lines.append("未全覆盖不一定意味着需要继续——有些缺口可能对最终回答无关紧要。")
        return "\n".join(lines)

    def _summarize_trace(self, trace: CognitiveTrace) -> str:
        parts = []

        if trace.investigation:
            inv_parts = [
                f"【调查研究】发现{len(trace.investigation.facts)}条事实，"
                f"{len(trace.investigation.gaps)}个信息缺口"
            ]
            if hasattr(trace.investigation, 'expanded_question') and trace.investigation.expanded_question:
                inv_parts.append(f"扩展问题：{trace.investigation.expanded_question[:150]}")
            if hasattr(trace.investigation, 'question_intent') and trace.investigation.question_intent:
                inv_parts.append(f"用户意图：{trace.investigation.question_intent[:100]}")
            inv_parts.append(f"摘要：{trace.investigation.summary[:200]}")
            parts.append("\n".join(inv_parts))

        if trace.contradictions and trace.contradictions.principal_contradiction:
            parts.append(
                f"【主要矛盾】{trace.contradictions.principal_contradiction.description[:200]}"
            )
            if trace.contradictions.system_model:
                sm = trace.contradictions.system_model
                parts.append(
                    f"【系统模型】{len(sm.elements)}个要素，"
                    f"{len(sm.relationships)}组关系，"
                    f"{len(sm.feedback_loops)}个反馈回路，"
                    f"{len(sm.emergent_properties)}个涌现属性\n"
                    f"边界：{sm.system_boundary[:150]}"
                )
            if trace.contradictions.secondary_contradictions:
                n = len(trace.contradictions.secondary_contradictions)
                secs = "；".join(
                    c.description[:80]
                    for c in trace.contradictions.secondary_contradictions[:3]
                )
                parts.append(f"【次要矛盾（{n}个）】{secs}")

        if trace.rational_synthesis:
            parts.append(
                f"【理性认识】\n本质：{trace.rational_synthesis.essence[:200]}\n"
                f"规律：{', '.join(trace.rational_synthesis.patterns[:5])}\n"
                f"假设：{', '.join(trace.rational_synthesis.hypotheses[:5])}"
            )

        if trace.decision:
            parts.append(
                f"【决策方案】{trace.decision.summary or trace.decision.strategic_assessment[:200]}\n"
                f"行动项（{len(trace.decision.action_items)}项）：" +
                "；".join(a.description[:80] for a in trace.decision.action_items[:5])
            )
            if trace.decision.risks:
                parts.append(f"风险：{'；'.join(trace.decision.risks[:5])}")

        if trace.practice:
            p = trace.practice

            # 标注认识论地位
            if p.mode in ("partial", "epistemic_only"):
                parts.append(
                    "【实践模式】" +
                    ("部分知性分析（可信度上限 V2）——部分行动项未经过直接实践检验"
                     if p.mode == "partial" else
                     "知性分析（可信度上限 V2）——此问题无法进行直接实践检验")
                )
            else:
                parts.append(f"【实践模式】{p.mode}")

            if p.practice_summary:
                parts.append(f"【实践结论】{p.practice_summary[:200]}")

            if p.steps_taken:
                step_lines = []
                for s in p.steps_taken[:8]:
                    detail = f"  - {s.description}"
                    if s.observed_result and len(s.observed_result) > 10:
                        obs = s.observed_result[:150].replace('\n', ' ')
                        detail += f"\n    结果：{obs}"
                    step_lines.append(detail)
                parts.append(f"【实践步骤（{len(p.steps_taken)}步）】\n" + "\n".join(step_lines))
            else:
                parts.append("【实践步骤】无有效执行步骤。若问题本质为调研/分析型（非技术验证），"
                             "请勿因此全面否定前序认知成果。")

            if p.observed_outcomes:
                outcomes_text = "\n".join(
                    f"  - {o[:200]}" for o in p.observed_outcomes[:5]
                )
                parts.append(f"【观测结果】\n{outcomes_text}")

            if p.success_indicators:
                parts.append(f"【成功指标】{'；'.join(p.success_indicators[:6])}")
            if p.failure_indicators:
                parts.append(f"【失败指标】{'；'.join(p.failure_indicators[:6])}")

            if p.unexpected_findings:
                parts.append(f"【意外发现】{'；'.join(p.unexpected_findings[:6])}")
                if trace.contradictions and trace.contradictions.principal_contradiction:
                    parts.append("请反思阶段重点检查：上述意外发现是否推翻了矛盾分析和理性认识的结论？")

            if p.unexpected_insights:
                parts.append(f"【意外洞察】{'；'.join(p.unexpected_insights[:3])}")

            if p.analysis_summary:
                parts.append(f"【知性分析摘要】{p.analysis_summary[:300]}")

            if p.claim_assessments:
                cl_lines = ["【各主张评估】"]
                for c in p.claim_assessments[:5]:
                    status = c.get("assessment", "?")
                    claim = c.get("claim", "")[:100]
                    basis = c.get("basis", "")[:100]
                    cl_lines.append(f"  [{status}] {claim} - {basis}")
                parts.append("\n".join(cl_lines))

            if p.real_world_practice_needed:
                n = len(p.real_world_practice_needed)
                task_summaries = "；".join(
                    t.hypothesis[:60] if hasattr(t, 'hypothesis') else str(t)[:60]
                    for t in p.real_world_practice_needed[:3]
                )
                parts.append(f"【现实世界待验证（{n} 项）】{task_summaries}")
                parts.append(
                    "反思提示：上述验证任务需要用户在现实中执行，智能体无法完成。"
                    "收敛判断应审慎——认识论地位上限为 V2。"
                )

            # 改进六：实践对矛盾分析的反馈
            if p.contradiction_feedback:
                fb_lines = ["【矛盾反馈（实践检验）】以下矛盾判断被实践挑战"]
                for fb in p.contradiction_feedback[:5]:
                    fb_lines.append(
                        f"- [{fb.get('challenge_type', '?')}] {fb.get('contradiction', '')[:120]}\n"
                        f"  证据：{fb.get('evidence', '')[:150]}\n"
                        f"  建议修正：{fb.get('suggested_revision', '')[:150]}"
                    )
                parts.append("\n".join(fb_lines))
                parts.append(
                    "⚠️ 在判断是否重新调查时，请重点考虑上述矛盾修正信号。"
                    "如果主要矛盾判断被实践削弱（weakened）或证伪（falsified），"
                    "should_reinvestigate 应为 true，reinvestigation_focus 应指向重新分析矛盾结构。"
                )

        if trace.perspectives:
            pv = trace.perspectives
            if pv.critical_warnings:
                parts.append(f"【多视角警告】{'；'.join(pv.critical_warnings[:5])}")
            if pv.synthesized_insight:
                parts.append(f"【多视角综合】{pv.synthesized_insight[:200]}")

        return "\n\n".join(parts) or "（轨迹为空）"

    def _parse_response(self, raw: str) -> ReflectionReport:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip().rstrip("`")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("reflection.parse_error", raw=raw[:200])
            return ReflectionReport(
                quality_assessment=raw[:300],
                convergence_score=0.5,
            )

        conv = data.get("convergence_score", 0.8)
        if isinstance(conv, str):
            try:
                conv = float(conv)
            except ValueError:
                conv = 0.8

        return ReflectionReport(
            quality_assessment=data.get("quality_assessment", ""),
            cognitive_biases_found=data.get("cognitive_biases_found", []),
            lessons_learned=data.get("lessons_learned", []),
            should_reinvestigate=data.get("should_reinvestigate", False),
            reinvestigation_focus=data.get("reinvestigation_focus", ""),
            convergence_score=float(conv),
            investigation_retrospective=data.get("investigation_retrospective", ""),
            contradiction_retrospective=data.get("contradiction_retrospective", ""),
            decision_retrospective=data.get("decision_retrospective", ""),
            skip_phases=data.get("skip_phases", []),
            focus_hints=data.get("focus_hints", {}),
            recommended_mode=data.get("recommended_mode", ""),
            contradiction_stability=float(data.get("contradiction_stability", 0.5)),
            contradiction_shift_detected=data.get("contradiction_shift_detected", False),
            contradiction_shift_description=data.get("contradiction_shift_description", ""),
            understanding_level=data.get("understanding_level", "感性"),
            qualitative_leap=data.get("qualitative_leap", False),
            level_progression=data.get("level_progression", ""),
            final_answer=data.get("final_answer", ""),
            recommend_detailed_report=bool(data.get("recommend_detailed_report", False)),
            skill_draft_candidates=data.get("skill_draft_candidates", []),
        )
