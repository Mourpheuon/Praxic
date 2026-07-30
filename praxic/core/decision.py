"""
Praxic Agent —— 决策引擎
核心原则：战略上藐视困难，战术上重视困难
改进二：矛盾贯穿——以矛盾的转化为决策的根本目的
"""
from __future__ import annotations

import json
import re
from typing import Optional

import structlog

from ..api.schemas.models import (
    ActionItem,
    ContradictionGraph,
    DecisionReport,
    FactReport,
    RationalSynthesis,
    SystemModel,
)
from ..config import load_phase_prompt, settings
from ..llm.base import BaseLLM
from ..llm import get_llm as _get_default_llm

log = structlog.get_logger(__name__)

_DECISION_PROMPT = """
你正在研究用户提出的问题，当前正处于【决策输出】阶段。
核心信条：战略上藐视困难，战术上重视困难。

## 核心原则：以矛盾为决策的根本依据

你不是在抽象地"做决策"。你的决策只有一个目的：促成主要矛盾的转化。

决策的合法性来自矛盾分析：
- 你面前的主要矛盾是 X。这个矛盾的两极是 A 和 B。A 当前是主要方面。
- 你的决策不是在 A 和 B 之间"选择一个"——而是对 B 施加条件，使矛盾的主要方面从 A 转移到 B。
- 每一个行动项必须回答：它作用于矛盾的哪一极？它如何改变矛盾双方的力量对比？它预期的转化效果是什么？

## 你的任务

### 1. 矛盾驱动的战略评估

- 主要矛盾当前的态势是什么？（哪方强、哪方弱、趋势如何）
- 矛盾的转化条件是什么？当前离这些条件有多远？
- 次要矛盾中，哪个可能取代主要矛盾的地位？如何防止或促成？

### 2. 以矛盾转化为目标的战术规划

- 你的行动项不是"建议"——它们是矛盾转化的操作杠杆
- 每个行动项必须选择一种矛盾操作策略

### 3. 矛盾操作策略分类（每个 action_item 必须选择一个 contradiction_resolution 角色）

- "weaken_principal_aspect"：削弱主要矛盾的主要方面（使其不能再主导）
- "strengthen_secondary_aspect"：强化主要矛盾的次要方面（积累反方向力量）
- "exploit_transformation_condition"：触发或加速矛盾的转化条件
- "elevate_secondary_contradiction"：将某个次要矛盾提升为主要矛盾（战略转向）
- "neutralize_destructive_loop"：打断正反馈的破坏性循环
- "investigate_uncertainty"：当矛盾判断不够确定时，先获取更多信息

### 4. 风险分析

充分估计困难，列举主要风险——特别是操作矛盾杠杆时可能引发的意外连锁反应。

### 5. 一句话结论

高度概括的最终判断——以矛盾转化为核心表述。

### 6. 实践可行性预判

你不是在列出行动项之后就结束了。每个行动项都需要你判断：这个行动项能否被智能体直接检验？

- 如果可以通过运行代码、读写文件、联网搜索等方式获得检验反馈 → practice_feasibility: "direct"
- 如果检验需要真实世界的操作（用户访谈、组织试点、发送邮件等）→ practice_feasibility: "indirect"
- 如果你不确定 → practice_feasibility: "unknown"

对于 indirect 的行动项，在 why_cannot_practice 中说明用户需要在现实中做什么来验证。
对于 direct 的行动项，在 suggested_practice_form 中简要说明检验思路。
把实践可行性预判作为决策质量的一部分——不能检验的行动，其正确性终究是悬置的。

## CRITICAL: Output ONLY valid JSON

{
  "strategic_assessment": "基于矛盾的宏观战略评估。当前主要矛盾的态势、转化条件、力量对比。1-2段",
  "tactical_plan": "战术规划详细说明——每个行动矛盾操作策略的具体实施方案",
  "action_items": [
    {
      "description": "具体行动描述",
      "priority": 1,
      "timeline": "本周内",
      "expected_outcome": "预期效果——尤其说明这个行动如何改变矛盾双方的力量对比",
      "targets_contradiction": "这个行动针对的矛盾描述（引用前文中的主要矛盾或次要矛盾描述）",
      "contradiction_resolution": "weaken_principal_aspect",
      "based_on_facts": "这个行动决策基于什么事实",
      "practice_feasibility": "direct",
      "suggested_practice_form": "如何检验这个行动的效果——例如写性能测试脚本比对优化前后数据",
      "why_cannot_practice": ""
    }
  ],
  "risks": ["风险1——操作矛盾杠杆的意外后果", "风险2"],
  "summary": "一句话结论——以矛盾转化为核心表述"
}
"""


class DecisionEngine:
    """决策引擎 —— 战略上藐视，战术上重视"""

    def __init__(
        self,
        llm: Optional[BaseLLM] = None,
        phase_config: Optional[dict] = None,
    ):
        self.llm = llm or _get_default_llm()
        self.config = phase_config or {}

    async def decide(
        self,
        question: str,
        fact_report: FactReport,
        contradiction_graph: ContradictionGraph,
        rational_synthesis: RationalSynthesis,
        system_model: Optional[SystemModel] = None,
        additional_context: str = "",
    ) -> DecisionReport:
        log.info("decision.start")

        # None 保护：当 investigation / contradiction / rational 被 skip 时，
        # 这些参数会为 None。用空默认值替换而不是崩溃。
        if fact_report is None:
            fact_report = FactReport(summary="（调查被跳过）")
        if contradiction_graph is None:
            contradiction_graph = ContradictionGraph(synthesis="（矛盾分析被跳过）")
        if rational_synthesis is None:
            rational_synthesis = RationalSynthesis(essence="（理性分析被跳过）")

        principal = contradiction_graph.principal_contradiction
        principal_text = (
            principal.description if principal else "未识别主要矛盾"
        )
        # 改进五：注入矛盾特殊性
        if principal and principal.particularity_description:
            principal_text += f"\n（特殊性：{principal.particularity_description[:150]}）"
        # 改进四：注入推导链摘要
        if principal and principal.derivation_chain:
            principal_text += f"\n（推导逻辑：{principal.derivation_chain.summary[:150]}）"

        secondary_text = "\n".join(
            f"- {c.description[:100]}"
            for c in contradiction_graph.secondary_contradictions[:3]
        )

        user_content = f"""## 用户问题
{question}

## 调查摘要
{fact_report.summary}

## 主要矛盾
{principal_text}

## 次要矛盾
{secondary_text or "无"}

## 理性认识（本质与规律）
{rational_synthesis.essence}

## 核心假设
{chr(10).join(f"- {h}" for h in rational_synthesis.hypotheses[:4])}

## 矛盾综合说明
{contradiction_graph.synthesis}
"""
        if additional_context:
            user_content += f"\n## 当前运行上下文\n{additional_context[:12000]}\n"

        system = load_phase_prompt("decision", _DECISION_PROMPT)
        try:
            from .autonomy import get_autonomy_instruction
            system = system + "\n" + get_autonomy_instruction(settings.autonomy_level, "decision")
        except ImportError:
            pass
        temperature = getattr(self.config, "temperature", 0.5)
        max_tokens = getattr(self.config, "max_tokens", 4096)

        response = await self.llm.call(
            messages=[{"role": "user", "content": user_content}],
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        report = self._parse_response(response.content)
        log.info("decision.done", n_actions=len(report.action_items))
        return report

    def _parse_response(self, raw: str) -> DecisionReport:
        original = raw
        raw = raw.strip()

        cleaned = raw
        while cleaned.startswith("```"):
            idx = cleaned.find("\n")
            cleaned = cleaned[idx+1:] if idx >= 0 else ""
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip().rstrip("`")

        data = None
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        if data is None:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                candidate = raw[start:end+1]
                for suffix in ["}", "}]}", "]}]}", "}]}]}"]:
                    try:
                        data = json.loads(candidate + suffix)
                        break
                    except json.JSONDecodeError:
                        continue
                if data is None:
                    try:
                        data = json.loads(candidate)
                    except json.JSONDecodeError:
                        pass

        if data is None:
            return self._prose_fallback(original)

        action_items = [
            ActionItem(
                description=a.get("description", ""),
                priority=a.get("priority", 1),
                timeline=a.get("timeline", ""),
                expected_outcome=a.get("expected_outcome", ""),
                targets_contradiction=a.get("targets_contradiction", ""),
                contradiction_resolution=a.get("contradiction_resolution", ""),
                based_on_facts=a.get("based_on_facts", ""),
                practice_feasibility=a.get("practice_feasibility", "unknown"),
                suggested_practice_form=a.get("suggested_practice_form", ""),
                why_cannot_practice=a.get("why_cannot_practice", ""),
            )
            for a in data.get("action_items", [])
        ]

        return DecisionReport(
            strategic_assessment=data.get("strategic_assessment", ""),
            tactical_plan=data.get("tactical_plan", ""),
            action_items=action_items,
            risks=data.get("risks", []),
            summary=data.get("summary", ""),
            autonomous_recommendation=data.get("autonomous_recommendation", ""),
            clarifying_questions=data.get("clarifying_questions", []) or [],
        )

    def _prose_fallback(self, raw: str) -> DecisionReport:
        log.info("decision.prose_fallback", len_raw=len(raw))

        strategic = ""
        tactical = ""
        summary = ""
        risks = []
        actions = []

        sections = re.split(
            r'(?:###?\s*)?(?:战略评估|战术规划|风险分析|行动建议|一句话结论|总结|结论)[：:]',
            raw
        )

        action_pattern = r'(?:^|\n)\s*(?:\d+[.、]|\-\s)\s*(.+?)(?=\n\s*(?:\d+[.、]|\-\s|$))'
        action_matches = re.findall(action_pattern, raw, re.MULTILINE)
        for i, m in enumerate(action_matches[:6]):
            m_clean = m.strip()[:200]
            if len(m_clean) > 10:
                actions.append(ActionItem(
                    description=m_clean,
                    priority=i + 1,
                ))

        risk_pattern = r'(?:风险|risk)[：:]\s*(.+?)(?=\n\n|\n(?:[^-\d])|$)'
        risk_match = re.search(risk_pattern, raw, re.IGNORECASE)
        if risk_match:
            risks = [r.strip() for r in re.split(r'[,，;；]', risk_match.group(1))[:5]]

        summary = raw[:200].replace('\n', ' ')

        conclusion_patterns = [
            r'(?:一句话结论|总结|结论|综上所述)[：:]\s*(.+?)(?=\n\n|$)',
        ]
        for pat in conclusion_patterns:
            m = re.search(pat, raw)
            if m:
                summary = m.group(1).strip()[:200]
                break

        return DecisionReport(
            strategic_assessment=raw[:500],
            tactical_plan="",
            action_items=actions if actions else [
                ActionItem(description="散文输出，详见strategic_assessment", priority=1)
            ],
            risks=risks,
            summary=summary,
        )
