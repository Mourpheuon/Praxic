"""
Praxic Agent —— 多视角审查模块
核心原则：从群众中来，到群众中去 —— 多轮收敛的完整循环

角色动态生成：根据问题上下文生成 3-5 个相关利益/领域视角，始终包含「群众代表」。
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

import structlog

from ..api.schemas.models import (
    ContradictionGraph,
    DecisionReport,
    PerspectiveSynthesis,
    PerspectiveView,
)
from ..config import settings
from ..llm.base import BaseLLM
from ..llm import get_llm as _get_default_llm

log = structlog.get_logger(__name__)

_PERSPECTIVE_GENERATION_PROMPT = """
你是一个多视角分析的设计师。你的任务是根据用户的问题和分析背景，设定一组最适合用于审查决策的多视角角色。

## 原则
1. 每个角色代表一个**具体的利益相关方或专业领域视角**，它们有明确的立场和关注点
2. 角色之间应有足够的差异性，避免重叠
3. 角色设定的依据是问题本身的领域和利益相关方（如开源社区问题会涉及维护者、贡献者、用户等）
4. **必须包含「群众代表」**：代表最广泛受众的真实感受和利益，关注方案对人的实际影响
5. 每个角色应有：名称（2-4字）、角色描述（一句话说明立场和关注点）
6. 生成 3-5 个角色（含群众代表在内）

## 输入
### 原始问题
{question}

### 决策摘要
{decision_summary}

### 主要行动项
{action_items}

## 输出格式（严格 JSON）
{{
  "perspectives": [
    {{
      "name": "角色名称",
      "role": "一句话角色描述，说明这个角色的立场和核心关注点",
      "temperature": 0.6
    }}
  ]
}}
只输出 JSON。
"""

_PERSPECTIVE_PROMPT_TEMPLATE = """
你是PraxicAgent的多视角审查模块，现在作为【{name}】进行审查。

## 你的角色
{role}

## 审查对象
以下是已经完成的分析摘要，请从你的特定角度进行审查：

{context}

## 输出要求
1. 从【{name}】的角度，写出2-4段深度评论
2. 列出3-5个关键洞察点或值得关注的问题
3. 语气：直接、有力，不要和稀泥

请直接开始输出（不需要 JSON 格式），用以下结构：
[评论正文]
---关键洞察---
- 洞察1
- 洞察2
...
"""

_REVISION_PROMPT_TEMPLATE = """
你是PraxicAgent的多视角审查模块，现在作为【{name}】进行第{round}轮审查。

## 你的角色（不变）
{role}

## 审查对象（不变）
{context}

## 其他视角的观点（到群众中去）
以下是上一轮审查中其他视角的观点摘要。请你：
1. 认真阅读其他视角的观点
2. 如果其他视角提出了你之前没考虑到的点，请吸收并修正你的观点
3. 如果你坚持自己的观点与其他视角不同，请明确指出分歧并说明理由
4. 更新你的关键洞察列表

{feedback_context}

## 输出要求
1. 从【{name}】的角度，写出修正后的评论（2-4段）
2. 列出3-5个关键洞察点
3. 如果与其他视角有明确共识或分歧，请指出

格式同上：
[评论正文]
---关键洞察---
- 洞察1
...
---共识---
- 与XX视角的共识...
---分歧---
- 与XX视角的分歧及理由...
"""

_SYNTHESIS_PROMPT_V2 = """
你是PraxicAgent的多视角综合器。以下是经过{rounds}轮审查后的视角意见汇总：

{perspectives_text}

## 你的任务
1. 综合所有视角，提炼最有价值的跨视角洞察
2. 区分"共识"和"分歧"：
   - 共识点（consensus_points）：多个视角一致认为的关键点
   - 分歧点（divergence_points）：不同视角之间存在根本性差异的判断
3. 共识点按可信度分级标注："全部一致" / "多数一致" / "少数观点"

输出格式（JSON）：
{
  "synthesized_insight": "跨视角综合洞察，2-3段",
  "critical_warnings": ["警告1", "警告2", "警告3"],
  "consensus_points": ["共识点1", "共识点2"],
  "divergence_points": ["分歧点1", "分歧点2"]
}

只输出 JSON。
"""


class MultiPerspectiveReview:
    """多视角审查模块 —— 角色动态生成 + 多轮收敛"""

    def __init__(self, llm=None, phase_config=None):
        self.llm = llm or _get_default_llm()
        if hasattr(phase_config, "__dataclass_fields__"):
            self.review_model = getattr(phase_config, "model", None)
            self.max_tokens = getattr(phase_config, "max_tokens", 1024)
        else:
            cfg = phase_config or {}
            self.review_model = getattr(cfg, "model", None)
            self.max_tokens = getattr(cfg, "max_tokens", 1024)

    async def _generate_perspectives(self, question, decision_report):
        action_text = "\n".join(f"- {a.description}" for a in decision_report.action_items[:5])
        prompt = (_PERSPECTIVE_GENERATION_PROMPT
                  .replace("{question}", question)
                  .replace("{decision_summary}", decision_report.summary or decision_report.strategic_assessment[:200])
                  .replace("{action_items}", action_text or "（无）"))
        response = await self.llm.call(
            messages=[{"role": "user", "content": "请根据问题生成审查视角。"}],
            system=prompt, temperature=0.7, max_tokens=1024,
        )
        raw = response.content.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            if len(parts) >= 2:
                raw = parts[1]
                if raw.startswith("json"):
                    raw = raw[4:]
        raw = raw.strip()
        try:
            data = json.loads(raw)
            perspectives = data.get("perspectives", [])
            if not perspectives:
                raise ValueError("empty")
            mass_rep = None
            others = []
            for p in perspectives:
                if "群众代表" in p.get("name", ""):
                    mass_rep = p
                else:
                    others.append(p)
            result = others[:4]
            if mass_rep:
                result.append(mass_rep)
            else:
                result.append({"name": "群众代表", "role": "代表实际受众的需求、感受和利益。关注方案对普通人的实际影响。", "temperature": 0.6})
            return result
        except (json.JSONDecodeError, ValueError):
            log.warning("perspectives.generation_fallback")
            return [
                {"name": "批判者", "role": "寻找逻辑漏洞、反例和被忽视的风险。", "temperature": 0.6},
                {"name": "实践者", "role": "关注可操作性、落地难度和执行障碍。", "temperature": 0.5},
                {"name": "战略者", "role": "关注长远影响、全局格局和战略意义。", "temperature": 0.5},
                {"name": "群众代表", "role": "代表实际受众的需求、感受和利益。", "temperature": 0.6},
            ]

    async def review(self, question, contradiction_graph, decision_report, rounds=1):
        perspectives = await self._generate_perspectives(question, decision_report)
        log.info("perspectives.start", n_roles=len(perspectives), rounds=rounds)
        context = self._build_shared_context(question, contradiction_graph, decision_report)
        views = await asyncio.gather(*[self._single_perspective_review(p, context) for p in perspectives])
        for r in range(2, rounds + 1):
            fc = self._build_feedback_context(context, views)
            views = await asyncio.gather(*[self._revision_round(p, fc, r) for p in perspectives])
        synthesis = await self._synthesize_with_consensus(views, rounds)
        return PerspectiveSynthesis(
            views=views,
            synthesized_insight=synthesis.get("synthesized_insight", ""),
            critical_warnings=synthesis.get("critical_warnings", []),
            consensus_points=synthesis.get("consensus_points", []),
            divergence_points=synthesis.get("divergence_points", []),
        )

    def _build_shared_context(self, question, contradiction_graph, decision_report):
        pc_desc = "未识别"
        if contradiction_graph and contradiction_graph.principal_contradiction:
            pc_desc = contradiction_graph.principal_contradiction.description or "未识别"
        return f"""## 原始问题\n{question}\n\n## 主要矛盾\n{pc_desc}\n\n## 决策\n{decision_report.summary}\n\n## 行动项\n{chr(10).join(f"- {a.description[:100]}" for a in decision_report.action_items[:5])}\n\n## 风险\n{chr(10).join(f"- {r}" for r in decision_report.risks[:5])}"""

    def _build_feedback_context(self, shared_context, views):
        parts = [shared_context, "\n## 上一轮各视角观点摘要\n"]
        for v in views:
            parts.append(f"### {v.perspective_name}\n{v.critique[:400]}\n")
        return "\n".join(parts)

    async def _single_perspective_review(self, perspective, context):
        name = perspective["name"]
        role = perspective["role"]
        temp = perspective.get("temperature", 0.5)
        system = _PERSPECTIVE_PROMPT_TEMPLATE.replace("{name}", name).replace("{role}", role).replace("{context}", context)
        response = await self.llm.call(messages=[{"role": "user", "content": f"请以{name}视角进行审查。"}], system=system, temperature=temp, max_tokens=self.max_tokens)
        content = response.content.strip()
        return PerspectiveView(perspective_name=name, critique=content, key_points=self._parse_insights(content))

    async def _revision_round(self, perspective, feedback_context, round_num):
        name = perspective["name"]
        role = perspective["role"]
        temp = perspective.get("temperature", 0.5)
        system = _REVISION_PROMPT_TEMPLATE.replace("{name}", name).replace("{role}", role).replace("{context}", feedback_context).replace("{round}", str(round_num)).replace("{feedback_context}", feedback_context)
        response = await self.llm.call(messages=[{"role": "user", "content": f"请以{name}视角进行第{round_num}轮审查。"}], system=system, temperature=temp, max_tokens=self.max_tokens)
        content = response.content.strip()
        insights = self._parse_insights(content)
        consensus, divergence = self._parse_consensus_divergence(content)
        return PerspectiveView(perspective_name=name, critique=content, key_points=insights, consensus=consensus, divergence=divergence)

    def _parse_insights(self, content):
        insights = []
        if "---关键洞察---" in content:
            s = content.split("---关键洞察---")[1]
            if "---" in s:
                s = s.split("---")[0]
            for line in s.strip().split("\n"):
                line = line.strip().lstrip("- ").strip()
                if line and not line.startswith("---"):
                    insights.append(line)
        return insights

    def _parse_consensus_divergence(self, content):
        consensus, divergence = [], []
        if "---共识---" in content:
            part = content.split("---共识---")[1]
            if "---分歧---" in part:
                part = part.split("---分歧---")[0]
            for line in part.strip().split("\n"):
                line = line.strip().lstrip("- ").strip()
                if line:
                    consensus.append(line)
        if "---分歧---" in content:
            part = content.split("---分歧---")[1]
            for line in part.strip().split("\n"):
                line = line.strip().lstrip("- ").strip()
                if line:
                    divergence.append(line)
        return consensus, divergence

    async def _synthesize_with_consensus(self, views, rounds):
        pt = "\n\n".join(f"## {v.perspective_name}\n{v.critique[:500]}" for v in views)
        system = _SYNTHESIS_PROMPT_V2.replace("{rounds}", str(rounds)).replace("{perspectives_text}", pt)
        response = await self.llm.call(messages=[{"role": "user", "content": "请综合所有视角。"}], system=system, temperature=0.4, max_tokens=self.max_tokens)
        raw = response.content.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            if len(parts) >= 2:
                raw = parts[1]
                if raw.startswith("json"):
                    raw = raw[4:]
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("perspectives.synthesis_parse_error")
            return {"synthesized_insight": raw[:500], "critical_warnings": [], "consensus_points": [], "divergence_points": []}
