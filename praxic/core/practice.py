"""
Praxic Agent —— 实践阶段模块（工具调用版 v3）
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import shlex
import time
from typing import Optional
import structlog

from ..api.schemas.models import (
    PracticeReport, PracticeRound, PracticeStep, CognitiveTrace,
    RealWorldPracticeTask, DirectionStateUpdate,
)
from ..config import PhaseConfig, load_phase_prompt, settings
from ..llm.base import BaseLLM
from ..tools.filesystem import WorkspaceToolkit
from ..tools.base import (
    ActionKind,
    ToolCallRecord,
    ToolStatus,
    ensure_summary,
    head_tail_truncate,
)
from ..tools.registry import ToolRegistry
from ..tools.permissions import PermissionPolicy
from ..tools.shell import ShellTool
from ..tools.python_exec import PythonExecTool
from ..tools.user_context import ReadUserContextTool

from . import practice_harness as harness
from .autonomy import get_autonomy_instruction, PermissionMode

log = structlog.get_logger(__name__)

_PRACTICE_PROMPT = """
你正在研究用户提出的问题，当前正处于【实践】阶段。
根本信条：实践是检验真理的唯一标准。

此前各阶段（调查->矛盾分析->理性认识）已经完成，产出了理论认识。
现在不是复述结论的时候——你要亲自把那些结论放回实践中去检验。

实践不是一次性运行。好的实践是一系列递进的实验
"""

_FINAL_ANALYSIS_PROMPT = """
你正在分析多轮实践实验的完整结果。

## 原始问题
{question}

## 前序假设（理性认识阶段提出）
{hypotheses}

## 实验设计意图
{practice_rationale}

## 全部轮次的执行记录
{all_rounds_log}

## 判定纪律（务必遵守）
1. verdict 必须基于**有效观测**：只有被回读验证或获得结构化有效数据的轮次才能参与判定。
   工具报错、超时、安全检查阻拦等**技术失败轮次不参与对论断的判定**——那是一次实践中断，不是认识否定。
2. analysis 必须说明本轮证据对前序理性认识（假设）的**认识变化**：是支持、动摇还是证伪了
   某个论断；如果是证伪，明确是哪个论断、依据什么有效观测。
3. 每个 claim_assessments 条目必须给出可追溯的工具证据，不能只写“执行了、得到了数值”——
   数据是感性材料，对论断的判定才是理性认识。
4. 若证据不足以下判定，明确写 inconclusive，并给出下一步调查/实验方向，为反思和后续轮次提供目标。

## 输出格式（严格 JSON）
{
  "verdict": "confirmed|partially_confirmed|challenged|falsified|inconclusive|execution_error",
  "analysis": "3-5句综合分析，必须说明认识变化（支持/动摇/证伪）及对前序理性认识的修正",
  "surprises": ["意外发现"],
  "confidence_change": "可信度变化说明",
  "reinvestigation_needed": false,
  "reinvestigation_focus": "",
  "key_findings": ["发现1", "发现2"],
  "claim_assessments": [
    {"claim": "被检验的论断", "assessment": "supported|challenged|falsified|inconclusive", "evidence": "对应工具证据（必须是有效观测）"}
  ],
  "contradiction_feedback": [
    {"contradiction": "...","challenge_type": "falsified|weakened|new_contradiction_found","evidence": "...","suggested_revision": "..."}
  ]
}
"""

_BOUNDARY_ANALYSIS_PROMPT = """
你当前正处于【实践——知性分析】阶段。
这个问题不属于可以通过代码执行来验证的技术类问题。
你当前能做的是知性分析——基于调查事实和矛盾分析，对各核心主张进行推断评估。
你的知性分析产出的认识论地位是 V2，不是 V3。
输出 JSON。
"""


class PracticeModule:
    """实践阶段 —— 多轮实验（工具调用模式 v3）"""

    def __init__(
        self,
        llm: Optional[BaseLLM] = None,
        phase_config: Optional[PhaseConfig] = None,
        workspace: Optional[WorkspaceToolkit] = None,
        max_retries: int = 3,
        practice_rounds: int = 3,
    ):
        if llm is None:
            from ..llm import get_llm
            llm = get_llm()
        self.llm = llm
        self.config = phase_config or PhaseConfig()
        self.workspace = workspace
        self._current_question: str = ""
        self._current_hypotheses: str = ""
        self._current_budget: dict = {}  # 实践阶段执行预算（经 practice() 入口从 wm 读取）
        self.max_retries = max_retries
        self.practice_rounds = practice_rounds
        self._background_procs: dict[str, dict] = {}
        self._fallback_registry: ToolRegistry | None = None
        self._direction_state = DirectionStateUpdate()
        self._direction_state_update = ""
        self._artifacts: list[dict] = []
        self._last_round_detail = None
        self._last_round_plan = None
        # E2: 上下文压缩状态 —— 历史轮日志超阈值时用 LLM 摘要节点替换，
        # 保留方向状态与产物台账，避免上下文无限膨胀。
        self._compressed_history: str = ""
        self._compressed_rounds: int = 0

    @property
    def can_execute(self) -> bool:
        return self.workspace is not None

    async def practice(
        self,
        question: str,
        trace: CognitiveTrace,
        on_progress: callable = None,
        wm = None,
        registry = None,
        steering_checkpoint: callable = None,
    ) -> Optional[PracticeReport]:
        def _notify(summary: str, data=None):
            if on_progress:
                on_progress("practice", summary, data=data)

        self._current_question = question
        self._current_wm = wm
        # 实践阶段执行预算（由反思写入 working_mem；无则空 → 与现状等价）
        _ph_budgets = (wm.get("phase_budgets", {}) if wm is not None else {}) or {}
        self._current_budget = _ph_budgets.get("practice", {}) or {}
        self._direction_state = DirectionStateUpdate()
        self._direction_state_update = ""
        self._artifacts = []
        self._last_round_detail = None
        self._last_round_plan = None
        self._compressed_history = ""
        self._compressed_rounds = 0
        hyps = []
        if trace.rational_synthesis:
            hyps = trace.rational_synthesis.hypotheses[:8]
        self._current_hypotheses = "\\n".join(f"- {h}" for h in hyps) if hyps else "（无）"

        registry = registry or self._get_fallback_registry()

        log.info("practice.start", has_workspace=self.workspace is not None)

        all_steps: list[PracticeStep] = []
        all_outcomes: list[str] = []
        all_unexpected: list[str] = []
        all_success: list[str] = []
        all_failure: list[str] = []
        round_summaries: list[str] = []
        full_execution_log: list[str] = []
        round_contexts: list[dict] = []
        round_records: list[PracticeRound] = []
        direction_state_history: list[DirectionStateUpdate] = []
        all_call_records: list[dict] = []
        all_action_records: list[dict] = []
        all_verification_results: list[dict] = []
        failure_classes: list[str] = []
        world_changed = False
        overall_rationale = ""

        # A4: 不具备执行能力 → 直接走知性分析（V2），不空跑三轮。
        if not self.can_execute:
            log.info("practice.no_execution_degrade", total_rounds=0)
            analysis = await self._boundary_analysis(
                question, trace, "无可用执行工作区，转入知性分析（V2）"
            )
            return self._build_epistemic_report(
                question, trace, analysis, mode="epistemic_only", reason="no_execution_capability"
            )

        r1_plan = await self._plan_round1(question, trace, wm=wm, registry=registry)
        overall_rationale = r1_plan.get("round_rationale", "")

        # A3+A4: 规划失败 → 不空跑三轮，直接知性分析（V2）。
        if r1_plan.get("plan_failed"):
            log.warning("practice.plan_failed_degrade", retries=self.max_retries)
            analysis = await self._boundary_analysis(
                question, trace, "首轮实验规划失败，转入知性分析（V2）"
            )
            return self._build_epistemic_report(
                question, trace, analysis, mode="partial", reason="plan_failed"
            )

        t0 = time.time()
        r1_steps, r1_outcomes, r1_unexpected, r1_success, r1_failure, r1_log, r1_ok, r1_detail = await self._execute_round(
            r1_plan, 1, registry, on_progress=on_progress, wm=wm,
            steering_checkpoint=steering_checkpoint,
        )
        r1_duration = time.time() - t0

        all_steps.extend(r1_steps)
        all_outcomes.extend(r1_outcomes)
        all_unexpected.extend(r1_unexpected)
        all_success.extend(r1_success)
        all_failure.extend(r1_failure)
        full_execution_log.append(f"=== 第 1 轮 (耗时 {r1_duration:.1f}s) ===\\n{r1_log}")
        r1_detail.duration_ms = round(r1_duration * 1000, 3)
        round_records.append(r1_detail)
        world_changed = world_changed or r1_detail.world_changed
        all_call_records.extend(r1_detail.tool_calls)
        all_action_records.extend(
            record for record in r1_detail.tool_calls
            if record.get("action_kind") in (ActionKind.CHANGE.value, ActionKind.EXTERNAL.value)
        )
        all_verification_results.extend(
            record.get("result", {}).get("verification", {})
            for record in r1_detail.tool_calls
            if record.get("result", {}).get("verification")
        )
        for failure_class in (r1_detail.failure_class,):
            if failure_class and failure_class not in failure_classes:
                failure_classes.append(failure_class)

        round_contexts.append({"round_num": 1, "plan_json": json.dumps(r1_plan, ensure_ascii=False, indent=2), "results": r1_log, "duration": f"{r1_duration:.1f}s"})
        round_summaries.append(self._summarise_round(1, r1_plan, r1_outcomes, r1_unexpected, r1_failure, r1_ok))
        r1_direction_state = self._update_direction_state(
            r1_plan, r1_outcomes, r1_failure, round_num=1, detail=r1_detail,
        )
        r1_detail.direction_state = r1_direction_state
        direction_state_history.append(r1_direction_state)
        self._last_round_detail = r1_detail
        self._last_round_plan = r1_plan
        # 产物台账：收集本轮生成/修改的文件，供下一轮直接引用。
        self._merge_artifacts(self._collect_artifacts(r1_detail, 1))

        from .phase_budget import validate_positive_int
        budget_rounds = validate_positive_int(self._current_budget.get("max_rounds"))
        _effective_rounds = budget_rounds if budget_rounds is not None else self.practice_rounds

        for r in range(2, _effective_rounds + 1):
            bg_results = await self._collect_background_results()
            if bg_results:
                for bg in bg_results:
                    bg_log = f"[后台完成] {bg['cmd'][:60]} exit={bg['returncode']} dur={bg['duration']:.1f}s"
                    full_execution_log.append(bg_log)

            # 标记上一轮引用过的产物为活跃（供智能注入分层）。
            if round_records:
                self._mark_artifacts_used(round_records[-1].tool_calls)
            # E2: 轮次足够后对早期历史做一次 LLM 压缩，生成摘要节点替代全量日志。
            if (r >= 3 and self._compressed_rounds == 0 and full_execution_log):
                compressed = await self._compress_history(
                    round_summaries, self._direction_state_update or "",
                )
                if compressed:
                    self._compressed_history = compressed
                    self._compressed_rounds = r - 1
                    log.info("practice.history_compressed", at_round=r)
            ctx = self._build_next_round_context(r, question, trace, round_contexts, full_execution_log)
            rn_plan = await self._plan_next_round(ctx, registry=registry)
            # done 是结束信号：本轮 tool_calls 照常执行（收尾动作不丢），执行完再结束。
            finish_after_round = bool(rn_plan.get("done"))

            if rn_plan.get("plan_failed"):
                # 后续轮规划连续失败：补齐方向状态日志后提前收束，不耗尽剩余轮次。
                log.warning("practice.next_round_plan_failed", round_num=r, retries=self.max_retries)
                direction_state_history.append(
                    self._update_direction_state(
                        rn_plan, [], ["规划失败，未执行"], round_num=r,
                    )
                )
                full_execution_log.append(f"=== 第 {r} 轮 规划失败，本轮无执行 ===\n（规划重试耗尽，记录为技术中断，不构成对论断的证伪）")
                round_contexts.append({
                    "round_num": r,
                    "plan_json": json.dumps(rn_plan, ensure_ascii=False, indent=2),
                    "results": "（规划失败，未执行）",
                    "duration": "0s",
                })
                round_summaries.append(self._summarise_round(r, rn_plan, [], [], [], False))
                continue

            t0 = time.time()
            rn_steps, rn_outcomes, rn_unexpected, rn_success, rn_failure, rn_log, rn_ok, rn_detail = await self._execute_round(
                rn_plan, r, registry, on_progress=on_progress, wm=wm,
                steering_checkpoint=steering_checkpoint,
            )
            rn_duration = time.time() - t0

            all_steps.extend(rn_steps); all_outcomes.extend(rn_outcomes)
            all_unexpected.extend(rn_unexpected); all_success.extend(rn_success)
            all_failure.extend(rn_failure)
            full_execution_log.append(f"=== 第 {r} 轮 (耗时 {rn_duration:.1f}s) ===\\n{rn_log}")
            rn_detail.duration_ms = round(rn_duration * 1000, 3)
            round_records.append(rn_detail)
            world_changed = world_changed or rn_detail.world_changed
            all_call_records.extend(rn_detail.tool_calls)
            all_action_records.extend(
                record for record in rn_detail.tool_calls
                if record.get("action_kind") in (ActionKind.CHANGE.value, ActionKind.EXTERNAL.value)
            )
            all_verification_results.extend(
                record.get("result", {}).get("verification", {})
                for record in rn_detail.tool_calls
                if record.get("result", {}).get("verification")
            )
            if rn_detail.failure_class and rn_detail.failure_class not in failure_classes:
                failure_classes.append(rn_detail.failure_class)
            round_contexts.append({"round_num": r, "plan_json": json.dumps(rn_plan, ensure_ascii=False, indent=2), "results": rn_log, "duration": f"{rn_duration:.1f}s"})
            round_summaries.append(self._summarise_round(r, rn_plan, rn_outcomes, rn_unexpected, rn_failure, rn_ok))
            # C5: 用本轮证据对锚点的可观测影响更新方向状态，供下一轮锚点。
            rn_direction_state = self._update_direction_state(
                rn_plan, rn_outcomes, rn_failure, round_num=r, detail=rn_detail,
            )
            rn_detail.direction_state = rn_direction_state
            direction_state_history.append(rn_direction_state)
            self._last_round_detail = rn_detail
            self._last_round_plan = rn_plan
            # 产物台账：本轮产物并入累积清单。
            self._merge_artifacts(self._collect_artifacts(rn_detail, r))
            if finish_after_round:
                log.info("practice.rounds_done", rounds_completed=r)
                break

        all_log_text = "\\n\\n".join(full_execution_log)
        analysis = await self._analyze_all_rounds(question, trace, overall_rationale, all_log_text)

        total_rounds = len(round_summaries)
        summary = ""
        if analysis:
            verdict = analysis.get("verdict", "unknown")
            summary = f"[{verdict}] {analysis.get('analysis', '')}"
            if analysis.get("surprises"):
                for s in analysis["surprises"][:3]:
                    if s not in all_unexpected: all_unexpected.append(s)
            if analysis.get("reinvestigation_needed"):
                summary += f" -> 建议重新调查：{analysis.get('reinvestigation_focus', '')[:80]}"
        else:
            summary = overall_rationale or f"完成 {total_rounds} 轮实验"

        summary = f"[共 {total_rounds} 轮实验] {summary}"
        log.info("practice.done", rounds=total_rounds, verdict=analysis.get("verdict") if analysis else "no_analysis", unexpected=len(all_unexpected))

        report = PracticeReport(
            mode="executed", confidence_ceiling="V3",
            steps_taken=all_steps, observed_outcomes=all_outcomes,
            unexpected_findings=all_unexpected, practice_summary=summary,
            success_indicators=all_success[:10], failure_indicators=all_failure[:10],
            contradiction_feedback=analysis.get("contradiction_feedback", []) if analysis else [],
            analysis_summary=(analysis or {}).get("analysis", "") if analysis else "",
            claim_assessments=(analysis or {}).get("claim_assessments", []) if analysis else [],
            unexpected_insights=(analysis or {}).get("surprises", []) if analysis else [],
            reinvestigation_needed=bool((analysis or {}).get("reinvestigation_needed", False)) if analysis else False,
            reinvestigation_focus=(analysis or {}).get("reinvestigation_focus", "") if analysis else "",
            rounds=round_records,
            tool_call_records=all_call_records,
            action_records=all_action_records,
            verification_results=all_verification_results,
            failure_classes=failure_classes,
            world_changed=world_changed,
            cache_metrics=wm.get_cache_metrics() if wm and hasattr(wm, "get_cache_metrics") else {},
            direction_state=self._direction_state,
            direction_state_history=direction_state_history,
        )
        if analysis:
            report.success_indicators.append(f"实验结论：{analysis.get('verdict', '')}")
            report.failure_indicators.append(f"可信度变化：{analysis.get('confidence_change', '')}")
        return report

    def _get_fallback_registry(self) -> ToolRegistry:
        """Keep direct PracticeModule users on the same structured execution path."""
        if self._fallback_registry is not None:
            return self._fallback_registry
        workspace = self.workspace.workspace if self.workspace else None
        roots = (workspace,) if workspace else ()
        policy = PermissionPolicy(
            permission_mode=settings.permission_mode,
            allowed_roots=roots,
        )
        registry = ToolRegistry(policy=policy)
        if workspace:
            from ..tools.assembler import register_workspace_tools
            register_workspace_tools(registry, workspace)
            registry.register(PythonExecTool(workspace_dir=workspace))
            registry.register(ShellTool(allowed_roots=roots))
        if policy.permission_mode == PermissionMode.AUTO_REVIEW:
            # 与 CognitiveLoop 一致：AUTO_REVIEW 下为越界/外部操作挂语义审核器。
            from ..core.reviewer import build_reviewer
            policy.reviewer = build_reviewer(self.llm, max_tokens=256)
        registry.register(ReadUserContextTool())
        # E1: 技能按需加载工具（少存多指路）；技能管理器从 settings.skills_dir 读取。
        try:
            from ..core.skill_manager import SkillManager
            from ..tools.skill import SkillLoadTool
            skill_manager = SkillManager(settings.skills_dir)
            registry.register(SkillLoadTool(manager=skill_manager))
        except Exception:
            log.warning("practice.skill_tool_register_error", exc_info=True)
        # 插件（档 3）：与 CognitiveLoop 一致，从 data_dir/plugins 加载。
        from ..tools.assembler import register_plugins
        register_plugins(registry)
        self._fallback_registry = registry
        return registry

    # ── 方向锚点 & 工具清单 ──

    def _build_direction_anchor(self, trace: CognitiveTrace, wm) -> str:
        anchor_parts = []
        if wm:
            anxiety = wm.get("core_anxiety", "")
            if anxiety:
                anchor_parts.append(f"### 用户深层关切\n{anxiety}")
        if trace.contradictions and trace.contradictions.principal_contradiction:
            anchor_parts.append(
                "### 主要矛盾\n"
                + trace.contradictions.principal_contradiction.description[:300]
            )
        if trace.rational_synthesis and trace.rational_synthesis.hypotheses:
            anchor_parts.append(
                "### 核心假设\n"
                + "\n".join(f"- {h}" for h in trace.rational_synthesis.hypotheses[:6])
            )
        if wm:
            hints = wm.get("focus_hints") or {}
            if hints.get("practice"):
                anchor_parts.append("### 反思提示\n" + hints["practice"])
        return "\n\n".join(anchor_parts) or "（无额外锚点，以原始问题为准）"

    def _build_tools_text(self, registry) -> str:
        """工具清单 + 工作区路径语义提示（模型要知道路径是相对工作区的）。"""
        hint_lines = ["## 工作区根目录", f"当前工作区：{self._workspace_root_text()}", ""
                      "所有文件工具（file_*/data_query/sqlite_query/pdf_extract/archive_*）的路径参数",
                      "都是相对工作区根目录的路径。例如工作区内文件 sales_data.csv，路径应写 sales_data.csv，",
                      "不要加工作区目录前缀。", ""]
        if registry is not None:
            try:
                return "\n".join(hint_lines) + registry.format_for_prompt()
            except Exception as e:
                log.warning("practice.tools_text_error", error=str(e))
        return "\n".join(hint_lines) + harness.DEFAULT_TOOLS

    def _workspace_root_text(self) -> str:
        if self.workspace is not None:
            try:
                return str(self.workspace.workspace.resolve())
            except Exception:
                pass
        return "（无工作区）"

    # ── Round 1 planning ──

    async def _plan_round1(self, question: str, trace: CognitiveTrace, wm=None, registry=None) -> dict:
        facts_lines = []
        if trace.investigation:
            for f in trace.investigation.facts[:6]:
                facts_lines.append(f"- [{f.credibility:.0%}] {f.content[:120]}")
        gaps_lines = []
        if trace.investigation:
            for g in trace.investigation.gaps[:5]:
                gaps_lines.append(f"- [{g.importance}] {g.description[:120]}")
        contradiction_text = "（未识别）"
        if trace.contradictions and trace.contradictions.principal_contradiction:
            contradiction_text = trace.contradictions.principal_contradiction.description[:300]
        essence_text = "（未形成）"
        if trace.rational_synthesis:
            essence_text = trace.rational_synthesis.essence[:300]
        hypotheses_text = "（无）"
        if trace.rational_synthesis:
            hypotheses_text = "\\n".join(f"- {h}" for h in trace.rational_synthesis.hypotheses[:6])
        practice_direction_text = "实践阶段负责从前序认识中提炼可检验论断，并自主编排行动与风险边界"
        if trace.rational_synthesis and trace.rational_synthesis.contradiction_motion:
            practice_direction_text += (
                "\n矛盾运动提示：" + trace.rational_synthesis.contradiction_motion[:300]
            )

        prompt = harness.R1_PLAN
        if wm:
            try:
                # E1: 技能注入只含目录摘要（阶段内可用技能的 name+描述），
                # 完整指令由 skill 工具按名加载，避免全量正文挤占上下文。
                skill_ctx = wm.get("_skill_catalog_summary", "")
                if skill_ctx:
                    prompt = "## 可用技能\\n" + skill_ctx + "\\n\\n---\\n\\n" + prompt
            except Exception:
                pass
        prompt = prompt.replace("{question}", question)
        prompt = prompt.replace("{facts_text}", "\\n".join(facts_lines) or "（无）")
        prompt = prompt.replace("{gaps_text}", "\\n".join(gaps_lines) or "（无）")
        prompt = prompt.replace("{contradiction_text}", contradiction_text)
        prompt = prompt.replace("{essence_text}", essence_text)
        prompt = prompt.replace("{hypotheses_text}", hypotheses_text)
        prompt = prompt.replace("{practice_direction_text}", practice_direction_text)
        # C1: 注入方向锚点与动态工具清单。
        prompt = prompt.replace("{direction_anchor}", self._build_direction_anchor(trace, wm))
        prompt = prompt.replace("{tools_text}", self._build_tools_text(registry))

        plan = await self._call_planner(
            prompt, "基于前序认知产出，设计第一轮实验。提炼可检验论断，设计工具调用序列。",
            registry=registry,
        )
        return plan

    async def _plan_next_round(self, ctx: dict, registry=None) -> dict:
        prompt = harness.RN_PLAN
        for key, value in ctx.items():
            prompt = prompt.replace("{" + key + "}", str(value))
        prompt = prompt.replace("{tools_text}", self._build_tools_text(registry))
        return await self._call_planner(
            prompt, f"规划第 {ctx.get('round_num', '?')} 轮实验，done=true 可提前结束。",
            registry=registry,
        )

    def _practice_budget_kwargs(self, depth=None) -> tuple[dict, int]:
        """返回实践阶段 LLM 调用的推理控制 kwargs 与默认 max_tokens。

        practice 默认关闭思维链（enable_reasoning=False 是现行为，深度体系保留）。
        max_tokens：预算显式 max_tokens 优先；否则按 depth 查 DEPTH_CONFIG。
        depth 默认读 self._current_budget.depth，否则 STANDARD。
        """
        from .depth import parse_depth, DEPTH_CONFIG, Depth as _Depth
        from .phase_budget import validate_positive_int
        budget = self._current_budget or {}
        reasoning_kwargs = {"enable_reasoning": False}
        if depth is None:
            depth = parse_depth(budget.get("depth"), default=_Depth.STANDARD)
        else:
            depth = parse_depth(depth)
        _cfg = DEPTH_CONFIG.get(depth) or {}
        _dflt_tok = int(_cfg.get("max_tokens", 4096))
        max_tokens = validate_positive_int(budget.get("max_tokens"))
        if max_tokens is None:
            max_tokens = max(_dflt_tok, getattr(self.config, "max_tokens", 4096))
        return reasoning_kwargs, max_tokens

    def _analyze_max_tokens(self, fallback: int = 8192) -> int:
        """实践分析类调用的 max_tokens：分析类固定 STANDARD 档（_analyze_all_rounds /_boundary_analysis）。
        有预算显式 max_tokens 则取预算，否则取 STANDARD 档 DEEP/STANDARD 混合中的更大值兜底。"""
        from .phase_budget import validate_positive_int
        from .depth import DEPTH_CONFIG
        budget = self._current_budget or {}
        v = validate_positive_int(budget.get("max_tokens"))
        if v is not None:
            return v
        _std = DEPTH_CONFIG.get("standard", {}).get("max_tokens", 4096)
        return max(fallback, int(_std))

    async def _call_planner(self, system_prompt: str, user_msg: str, registry=None) -> dict:
        """
        规划调用。使用 self.max_retries 循环重试：每次失败把解析/校验错误与
        LLM 原始输出片段（截断）追加回消息，让模型知道为何被拒绝。
        重试耗尽返回带 plan_failed 标记的空计划，由上层决定降级。
        """
        system_prompt += get_autonomy_instruction(settings.autonomy_level, "practice")
        # 按当前深度注入规划输出 schema 分层：
        #   SHALLOW → tool_calls + directional_claim；STANDARD → 加 testable_claims + rationale；
        #   DEEP → 再加策略推演（strategy_deliberation）。
        from .depth import parse_depth, Depth as _Depth
        _depth = parse_depth((self._current_budget or {}).get("depth"), default=_Depth.STANDARD)
        if _depth == _Depth.SHALLOW:
            system_prompt += (
                "\n\n## 规划输出范围（本档）\n"
                "本轮规划仅需输出 tool_calls 与 directional_claim，其余可省略默认值。"
            )
        elif _depth == _Depth.STANDARD:
            system_prompt += (
                "\n\n## 规划输出范围（本档）\n"
                "输出 tool_calls、directional_claim、testable_claims、round_rationale，"
                "给出每轮检验可测试的论断与依据。"
            )
        else:  # DEEP
            system_prompt += (
                "\n\n## 规划输出范围（本档）\n"
                "在 STANDARD 基础上增加策略推演（strategy_deliberation）：说明为何选此检验路径、"
                "预期的认识变化与备选方向。"
            )
        retries = max(1, int(self.max_retries or 3))
        last_error = ""
        last_snippet = ""

        for attempt in range(1, retries + 1):
            msg = user_msg
            if last_error:
                msg = (
                    user_msg
                    + "\n\n## 上一次规划被拒绝\n"
                    + f"[原因] {last_error}\n"
                    + f"[上次原始输出片段] {last_snippet}\n\n"
                    + "请修正上述问题后，重新输出严格 JSON 对象。"
                )
            resp = None
            try:
                # B2: JSON mode，仅首轮尝试并带安全网；provider 不支持则降级文本模式。
                _reasoning_kwargs, _plan_max_tokens = self._practice_budget_kwargs()
                call_kwargs: dict = dict(_reasoning_kwargs)
                if attempt == 1:
                    call_kwargs["response_format"] = {"type": "json_object"}
                try:
                    resp = await self.llm.call(
                        messages=[{"role": "user", "content": msg}],
                        system=system_prompt,
                        temperature=getattr(self.config, "temperature", 0.4),
                        max_tokens=_plan_max_tokens,
                        **call_kwargs,
                    )
                except Exception as e:
                    err = str(e)
                    if call_kwargs and self._looks_like_unsupported_response_format(err):
                        log.warning(
                            "practice.plan_json_mode_degraded",
                            attempt=attempt, error=err[:200],
                        )
                        resp = await self.llm.call(
                            messages=[{"role": "user", "content": msg}],
                            system=system_prompt,
                            temperature=getattr(self.config, "temperature", 0.4),
                            max_tokens=_plan_max_tokens,
                            **dict(_reasoning_kwargs),
                        )
                    else:
                        raise

                plan = self._parse_json_safe(resp.content.strip(), {})
                if not plan or not isinstance(plan, dict):
                    raise ValueError("空计划或不含 JSON 对象")

                # B2 + C2: 结构校验（tool 名在 registry、参数类型、方向字段）。
                errs = self._validate_plan_schema(plan, registry)
                if errs:
                    raise ValueError("；".join(errs))

                plan.setdefault("round_rationale", "")
                plan.setdefault("tool_calls", [])
                plan.setdefault("expected_outcomes", [])
                self._default_direction_fields(plan)
                return plan
            except Exception as e:
                last_error = str(e)
                last_snippet = ""
                if resp is not None:
                    last_snippet = self._truncate(resp.content, 400)
                log.warning(
                    "practice.plan_attempt_failed",
                    attempt=attempt, retries=retries, error=last_error,
                    raw=last_snippet,
                )

        return {
            "plan_failed": True,
            "round_rationale": f"规划在 {retries} 次尝试后仍失败: {last_error[:120]}",
            "tool_calls": [],
            "expected_outcomes": [],
        }

    @staticmethod
    def _truncate(text: object, length: int = 400) -> str:
        s = str(text or "")
        return s[:length] if len(s) <= length else s[:length] + "...[truncated]"

    @staticmethod
    def _looks_like_unsupported_response_format(err: str) -> bool:
        low = err.lower()
        return any(
            token in low
            for token in ("response_format", "json_mode", "json_object", "400", "unsupported")
        )

    def _validate_plan_schema(self, plan: dict, registry=None) -> list[str]:
        """返回校验错误列表；为空表示通过。"""
        errs: list[str] = []

        # ── B2: tool_calls 结构校验（仅当计划使用新 tool_calls 契约）──
        tool_calls = plan.get("tool_calls")
        if tool_calls is not None and not isinstance(tool_calls, list):
            errs.append("tool_calls 必须是数组")
            tool_calls = []
        elif tool_calls is None:
            tool_calls = []

        if tool_calls:
            known = set(registry.get_names()) if registry else set()
            for tc in tool_calls:
                if not isinstance(tc, dict) or not tc.get("tool"):
                    errs.append("tool_calls 中存在缺 tool 名的条目")
                    continue
                tname = str(tc["tool"])
                params = tc.get("params", {})
                if not isinstance(params, dict):
                    errs.append(f"工具 {tname} 的 params 必须是对象")
                if registry and tname not in known:
                    errs.append(f"工具 {tname} 不在已注册工具清单中")

            # ── C2: 新契约下方向字段为非空可追溯要求 ──
            directional_claim = plan.get("directional_claim")
            if not directional_claim or not str(directional_claim).strip():
                errs.append("directional_claim 为空，须可追溯至方向锚点中的假设或矛盾")
            role = plan.get("epistemic_role")
            if role not in (None, "", "exploration", "verification", "revision"):
                errs.append(f"epistemic_role 取值非法: {role}")
            if "deviation_rationale" in plan and not isinstance(plan.get("deviation_rationale"), str):
                errs.append("deviation_rationale 必须是字符串")

        # ── 旧契约兼容：方向字段软校验，只记录缺失，不阻断旧调用方 ──
        legacy_contract = not tool_calls and any(
            key in plan for key in ("files_to_create", "commands_to_run")
        )
        if legacy_contract:
            missing = [
                key for key in ("epistemic_role", "directional_claim", "deviation_rationale")
                if not plan.get(key)
            ]
            if missing:
                log.warning(
                    "practice.legacy_plan_missing_direction_fields",
                    fields=missing,
                    compatibility_path=True,
                )
        return errs

    @staticmethod
    def _default_direction_fields(plan: dict) -> dict:
        plan.setdefault("directional_claim", "")
        plan.setdefault("deviation_rationale", "")
        plan.setdefault("epistemic_role", "exploration")
        return plan

    async def _execute_round(self, plan: dict, round_num: int, registry=None, on_progress=None, wm=None, steering_checkpoint=None) -> tuple:
        """Execute tools from plan's tool_calls list."""
        steps, outcomes, unexpected, success, failure, log_parts = [], [], [], [], [], []
        all_ok = True
        records: list[dict] = []
        failure_classes: list[str] = []
        world_changed = False

        rationale = plan.get("round_rationale", "")
        if rationale:
            steps.append(PracticeStep(description=f"第{round_num}轮: {rationale}", action_taken=rationale, observed_result="开始", matched_expectation=True))

        tool_calls = await self._normalise_tool_calls(plan)
        # B2: 先并发调度与执行，把每个调用的结果按声明顺序收齐，再统一处理。
        # 并发安全的工具进有界并行池；非安全工具构成独占屏障（等并行池排空
        # 后才执行）。结果顺序与模型声明一致（单车道：策略串行，执行体并发）。
        call_records = await self._schedule_tool_calls(
            tool_calls, registry, wm=wm,
        )
        for tool_name, params, result in call_records:
            if not tool_name:
                continue
            record = None
            if result is not None:
                record = next((r for r in reversed(registry.records) if r.call_id == result.call_id), None)
                record_dict = record.to_dict() if record else {
                    "call_id": result.call_id, "tool": tool_name, "result": result.to_dict()
                }
                records.append(record_dict)
                world_changed = world_changed or result.world_changed is True
                may_have_changed = (
                    result.action_kind in (ActionKind.CHANGE, ActionKind.EXTERNAL)
                    and result.world_changed is not False
                )
                if may_have_changed and wm is not None:
                    wm.invalidate_context(reason=f"world_state_may_have_changed:{tool_name}")
                if result.failure_class and result.failure_class not in failure_classes:
                    failure_classes.append(result.failure_class)
                if result.state_classification == "world_unchanged" and "world_unchanged" not in failure_classes:
                    failure_classes.append("world_unchanged")
                if result.state_classification == "change_unverified" and "change_unverified" not in failure_classes:
                    failure_classes.append("change_unverified")
                if on_progress:
                    try:
                        on_progress(
                            "practice",
                            f"{tool_name}：{result.state_classification}",
                            data={"event_type": "tool_call", "record": record_dict, "tool": tool_name},
                        )
                    except Exception:
                        log.warning("practice.progress_callback_error", exc_info=True)
                if steering_checkpoint:
                    try:
                        steering = await steering_checkpoint(tool_name, result)
                        if steering:
                            log_parts.append(f"[用户插话] {steering}")
                    except Exception:
                        log.warning("practice.steering_checkpoint_error", tool=tool_name, exc_info=True)
            if result and result.ok:
                classification = result.state_classification
                # A1: 回填下一轮上下文用一句话摘要而非 content 全量，避免模型抄证据导致 JSON 超长。
                log_parts.append(f"[{tool_name}] {classification}: {ensure_summary(result)}")
                outcomes.append(f"{classification} {tool_name}")
                success.append(f"{tool_name} {classification}")
                steps.append(PracticeStep(
                    description=f"调用 {tool_name}", action_taken=str(params)[:200],
                    observed_result=(result.content or "")[:300], matched_expectation=classification != "verification_failed",
                    tool=tool_name, action_kind=result.action_kind.value,
                    permission=result.permission.to_dict() if result.permission else {},
                    tool_result=result.to_dict(),
                    verification=result.verification.to_dict() if result.verification else {},
                    world_changed=result.world_changed, state_classification=classification,
                ))
                if classification == "verification_failed":
                    all_ok = False
                    failure.append(f"{tool_name}: 回读验证失败")
                    unexpected.append(f"工具 {tool_name} 执行成功但回读验证失败")
                elif classification == "world_unchanged":
                    all_ok = False
                    failure.append(f"{tool_name}: 世界状态未改变")
                    unexpected.append(f"工具 {tool_name} 成功返回但世界状态未改变")
                elif classification == "change_unverified":
                    all_ok = False
                    failure.append(f"{tool_name}: 世界状态变化未经独立回读验证")
                    unexpected.append(f"工具 {tool_name} 已执行，但缺少世界状态回读证据")
            else:
                err = result.error if result else "registry= None"
                # A2: 失败原因通常在输出尾部，用保头尾截断避免错误信息丢失
                err_trunc = head_tail_truncate(err, head_chars=200, tail_chars=300)
                log_parts.append(f"[{tool_name}] FAIL: {err}")
                outcomes.append(f"FAIL {tool_name}")
                failure.append(f"{tool_name}: {err}")
                steps.append(PracticeStep(
                    description=f"失败 {tool_name}", action_taken=str(params)[:200],
                    observed_result=err_trunc, matched_expectation=False, tool=tool_name,
                    action_kind=result.action_kind.value if result else "",
                    permission=result.permission.to_dict() if result and result.permission else {},
                    tool_result=result.to_dict() if result else {},
                    verification=result.verification.to_dict() if result and result.verification else {},
                    world_changed=result.world_changed if result else None,
                    state_classification=result.state_classification if result else "tool_error",
                ))
                unexpected.append(f"工具 {tool_name} 失败: {err}")
                all_ok = False

        detail = PracticeRound(
            round_num=round_num,
            rationale=rationale,
            testable_claims=plan.get("testable_claims", []),
            expected_outcomes=plan.get("expected_outcomes", []),
            tool_calls=records,
            outcome="success" if all_ok and records else ("failed" if records else "no_action"),
            failure_class=";".join(failure_classes),
            world_changed=world_changed,
        )
        return (steps, outcomes, unexpected, success, failure, "\\n".join(log_parts) or "（空）", all_ok, detail)

    async def _schedule_tool_calls(
        self,
        tool_calls: list[dict],
        registry=None,
        wm=None,
        max_parallel: int = 4,
    ) -> list[tuple[str, dict, ToolResult | None]]:
        """B2: 同轮工具并发调度，按模型声明顺序返回 [(tool, params, result)]。

        规则（参考 DSH 单车道模型：策略串行、执行体并发、提交保序）：
        - 并发安全工具（is_concurrency_safe=True）进有界并行池（max_parallel）。
        - 非安全工具构成独占屏障：前一个完成后才执行下一个，且必须等
          并行池排空，避免读写竞态（fail-closed，默认串行）。
        - read_user_context 的 _user_context 只在已授权执行时注入。
        """
        if registry is None:
            return [
                (tc.get("tool", ""), tc.get("params", {}) or {}, None)
                for tc in tool_calls
            ]

        semaphore = asyncio.Semaphore(max(max_parallel, 1))
        pending: list[asyncio.Task] = []
        results: list[tuple[str, dict, ToolResult | None]] = []

        async def _dispatch(tc: dict):
            tool_name = tc.get("tool", "")
            params = tc.get("params", {}) or {}
            if not tool_name:
                return (tool_name, params, None)
            call_params = dict(params)
            if tool_name == "read_user_context" and wm is not None:
                call_params["_user_context"] = str(wm.get("context", "") or "")
            try:
                async with semaphore:
                    result = await registry.call(tool_name, **call_params)
            except Exception as exc:
                log.warning("practice.schedule_tool_error", tool=tool_name, error=str(exc))
                result = ToolResult(
                    status=ToolStatus.ERROR,
                    content="",
                    error=f"调度执行异常: {exc}",
                    failure_class="tool_error",
                )
            return (tool_name, params, result)

        async def _drain():
            if not pending:
                return
            for fut in pending:
                results.append(await fut)
            pending.clear()

        for tc in tool_calls:
            tool_name = tc.get("tool", "")
            is_safe = False
            reg_get = getattr(registry, "get", None)
            if tool_name and callable(reg_get):
                reg_tool = reg_get(tool_name)
                is_safe = bool(
                    reg_tool is not None
                    and getattr(reg_tool, "is_concurrency_safe", False)
                )
            if is_safe:
                pending.append(asyncio.create_task(_dispatch(tc)))
            else:
                # 非安全工具：独占屏幕，先排空并行池，再串行执行
                await _drain()
                results.append(await _dispatch(tc))
        await _drain()
        return results

    async def _normalise_tool_calls(self, plan: dict) -> list[dict]:
        """Accept the current tool_calls schema and the earlier file/command schema.

        B3: 规划与代码生成分离。新契约下 python_exec 的 params.code 由
        code_ref（代码意图描述）替代；执行前先经 _generate_file_content
        生成实际代码再调用，规划输出量显著减小。
        """
        calls = list(plan.get("tool_calls") or [])
        for tc in calls:
            if tc.get("tool") != "python_exec" or not isinstance(tc.get("params"), dict):
                continue
            params = tc["params"]
            if "code_ref" in params:
                code_ref = params.get("code_ref")
                code = await self._generate_file_content(
                    path="<python_exec>",
                    purpose=str(code_ref or ""),
                    plan=plan,
                )
                params["code"] = code
                params.pop("code_ref", None)
        if calls:
            return calls
        generated_files: dict[str, str] = {}
        for item in plan.get("files_to_create", []) or []:
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            content = await self._generate_file_content(path, str(item.get("purpose", "")), plan)
            generated_files[self._normalise_legacy_path(path)] = content
            calls.append({"tool": "file_write", "params": {"path": path, "content": content, "mode": "write"}})
        for item in plan.get("commands_to_run", []) or []:
            command = item.get("cmd") or item.get("command")
            if not command:
                continue
            python_call = self._legacy_python_exec_call(
                command,
                generated_files,
                timeout_seconds=item.get("timeout_seconds", 30),
            )
            if python_call is not None:
                calls.append(python_call)
                continue
            calls.append({
                "tool": "shell_exec",
                "params": {
                    "command": command,
                    "cwd": item.get("working_dir", ""),
                    "timeout_seconds": item.get("timeout_seconds", 30),
                },
            })
        return calls

    @staticmethod
    def _normalise_legacy_path(path: str) -> str:
        normalized = path.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized

    def _legacy_python_exec_call(
        self,
        command,
        generated_files: dict[str, str],
        *,
        timeout_seconds: float,
    ) -> dict | None:
        try:
            argv = shlex.split(command, posix=False) if isinstance(command, str) else [str(part) for part in command]
        except ValueError:
            return None
        if len(argv) != 2 or Path(argv[0]).name.lower() not in {"py", "py.exe", "python", "python.exe"}:
            return None
        script = self._normalise_legacy_path(argv[1].strip("\"'"))
        code = generated_files.get(script)
        if code is None or Path(script).suffix.lower() != ".py":
            return None
        return {
            "tool": "python_exec",
            "params": {"code": code, "timeout_seconds": timeout_seconds},
        }

    async def _generate_file_content(self, path: str, purpose: str, plan: dict) -> str:
        prompt = harness.FILE_CONTENT
        replacements = {
            "{question}": self._current_question,
            "{hypotheses}": self._current_hypotheses,
            "{plan_summary}": plan.get("round_rationale", ""),
            "{file_path}": path,
            "{purpose}": purpose,
        }
        for key, value in replacements.items():
            prompt = prompt.replace(key, str(value))
        _rkw, _mtok = self._practice_budget_kwargs(depth="shallow")  # 代码生成固定 SHALLOW，无需推理链
        response = await self.llm.call(
            messages=[{"role": "user", "content": f"为文件 {path} 生成可运行内容。用途：{purpose}"}],
            system=prompt,
            temperature=getattr(self.config, "temperature", 0.3),
            max_tokens=_mtok,
            **_rkw,
        )
        content = response.content.strip()
        if content.startswith("```"):
            first_newline = content.find("\n")
            content = content[first_newline + 1:] if first_newline >= 0 else content[3:]
            if content.endswith("```"):
                content = content[:-3].rstrip()
        return content

    def _build_next_round_context(self, round_num: int, question: str, trace: CognitiveTrace, round_contexts: list[dict], full_execution_log: list[str]) -> dict:
        facts_lines = []
        if trace.investigation:
            for f in trace.investigation.facts[:6]:
                facts_lines.append(f"- [{f.credibility:.0%}] {f.content[:120]}")
        gaps_lines = []
        if trace.investigation:
            for g in trace.investigation.gaps[:5]:
                gaps_lines.append(f"- [{g.importance}] {g.description[:120]}")
        ct = "（未识别）"
        if trace.contradictions and trace.contradictions.principal_contradiction:
            ct = trace.contradictions.principal_contradiction.description[:300]
        et = "（未形成）"
        if trace.rational_synthesis:
            et = trace.rational_synthesis.essence[:300]
        ht = "（无）"
        if trace.rational_synthesis:
            ht = "\\n".join(f"- {h}" for h in trace.rational_synthesis.hypotheses[:6])
        practice_direction_text = "实践阶段根据前序认识自主调整下一轮检验方向"
        if trace.rational_synthesis and trace.rational_synthesis.synthesis_text:
            practice_direction_text += (
                "\n前序综合判断：" + trace.rational_synthesis.synthesis_text[:400]
            )
        prev = round_contexts[-1] if round_contexts else {}
        current_anchor = self._build_direction_anchor(trace, self._current_wm)
        direction_state = getattr(self, "_direction_state", None)
        if direction_state and direction_state.evidence_status != "no_observation":
            state_payload = self._direction_state_to_dict(direction_state)
            current_anchor += (
                "\n\n### 本轮证据对锚点的影响（上一轮结构化状态）\n"
                + json.dumps(state_payload, ensure_ascii=False, indent=2)
            )
        return {
            "round_num": str(round_num), "question": question,
            "facts_text": "\\n".join(facts_lines) or "（无）", "gaps_text": "\\n".join(gaps_lines) or "（无）",
            "contradiction_text": ct, "essence_text": et, "hypotheses_text": ht,
            "practice_direction_text": practice_direction_text,
            "direction_anchor": current_anchor,
            "artifacts_text": self._artifacts_text(),
            "execution_status_text": self._execution_status_text(),
            "prev_round_num": str(prev.get("round_num", round_num - 1)),
            "prev_round_plan": head_tail_truncate(prev.get("plan_json", "（无）"), max_len=3000),
            "prev_round_results": head_tail_truncate(prev.get("results", "（无）"), max_len=3000),
            "prev_round_duration": prev.get("duration", "未知"),
            "all_rounds_log": self._build_all_rounds_log(full_execution_log, round_num),
        }

    def _build_all_rounds_log(self, full_execution_log: list[str], round_num: int) -> str:
        # E2: 已被摘要压缩的早期轮次不再全量注入，改为摘要节点；
        # 只保留最近一轮原始日志 + 压缩前的摘要节点，方向状态不丢。
        recent = (
            full_execution_log[-1][:1200] if full_execution_log else ""
        )
        parts: list[str] = []
        if getattr(self, "_compressed_history", ""):
            parts.append(self._compressed_history)
        if recent:
            parts.append(recent)
        if not parts:
            return "（无）" if not full_execution_log else head_tail_truncate(
                "\n\n".join(full_execution_log), max_len=4000,
            )
        return head_tail_truncate("\n\n".join(parts), max_len=4000)

    def _execution_status_text(self) -> str:
        """把前一轮工具执行结果结构化：成功 / 技术中断 / 权限拒绝，含失败原因。

        同时对比规划 vs 实际执行，暴露“计划了但未执行”的偏差，
        供下一轮规划避免重复规划失败的或未落地的动作。
        """
        last = getattr(self, "_last_round_detail", None)
        if last is None or not (last.tool_calls or []):
            return "（暂无执行记录）"
        lines = [f"第 {last.round_num} 轮工具执行结果："]
        for record in (last.tool_calls or []):
            tool = record.get("tool", "?")
            result = record.get("result") or {}
            status = result.get("status", "?")
            classification = result.get("state_classification", "")
            failure_class = result.get("failure_class") or ""
            error = head_tail_truncate(str(result.get("error") or ""), head_chars=80, tail_chars=160)
            if status == "error" or classification in ("tool_error", "verification_failed", "permission_denied", "authorization_expired"):
                # C1: 区分失败类型，让模型能给出正确修复动作（超时可加大超时重试，
                # 输出超限该裁剪，权限拒绝该升级）。
                if "permission" in classification or "authorization" in classification:
                    tag = "[权限拒绝]"
                elif failure_class == "timeout":
                    tag = "[超时]"
                elif failure_class == "output_limit":
                    tag = "[输出超限]"
                elif failure_class in ("abort", "worker_exit"):
                    tag = f"[执行中断:{failure_class}]"
                else:
                    tag = "[技术中断]"
                detail = error or classification
                if failure_class and failure_class not in (
                    "permission_denied", "authorization_expired", "authorization_pending"
                ):
                    detail = f"{failure_class} | {detail}"
                lines.append(f"  {tag} {tool}: {detail}")
            else:
                lines.append(f"  [成功] {tool}: {classification or status}")

        # 计划偏差：规划了但执行记录里没有的（未执行/被跳过）
        plan = getattr(self, "_last_round_plan", None) or {}
        planned = [str(tc.get("tool", "")) for tc in (plan.get("tool_calls") or []) if tc.get("tool")]
        executed = [str(rec.get("tool", "")) for rec in (last.tool_calls or []) if rec.get("tool")]
        if planned:
            missed = [t for t in planned if t not in executed]
            if missed:
                lines.append(f"  计划偏差：规划了但未执行 [{', '.join(missed)}]（可能被跳过、权限拦截或计划变更）")
        return "\n".join(lines)

    def _summarise_round(self, r: int, plan: dict, outcomes, unexpected, failures, all_ok):
        return f"第{r}轮: {plan.get('round_rationale','')[:100]} ok={all_ok}"

    async def _compress_history(self, round_summaries: list[str], direction_update: str = "") -> str:
        """E2: 用 LLM 把早期轮次历史压缩成一个摘要节点，替代全量日志。

        保留方向状态（direction_update）与结论，丢弃过程性全文，控制上下文不膨胀。
        返回的摘要节点以 <history-summary> 标记包围，便于后续识别。
        """
        if not round_summaries:
            return ""
        try:
            source = "\n".join(round_summaries[-8:])
            task = (
                "把以下多轮实践的历史压缩成一段可复核的摘要节点"
                "（≤250字中文），保留每轮验证了哪个论断、得到什么有效观测、"
                "出现了哪些技术失败或意外发现；不要复述工具原始输出。"
                "只输出摘要正文。"
            )
            content = (
                f"## 方向状态（保留）\n{direction_update or '（无）'}\n\n"
                f"## 已有轮次摘要\n{source}\n"
            )
            _rkw, _mtok = self._practice_budget_kwargs(depth="shallow")
            resp = await self.llm.call(
                messages=[{"role": "user", "content": task + "\n\n" + content}],
                system=(
                    "你是 Praxic 实践阶段的上下文压缩器。请把早期轮次的过程性日志"
                    "总结成一个方向状态不丢的摘要节点，供后续轮次参考，避免上下文膨胀。"
                ),
                temperature=0.2,
                max_tokens=_mtok,
                **_rkw,
            )
            summary = (resp.content or "").strip()
            if not summary:
                return ""
            return "\n".join(
                [
                    "<history-summary>",
                    summary[:1200],
                    "</history-summary>",
                ]
            )
        except Exception as exc:
            log.warning("practice.compress_error", error=str(exc))
            return ""

    async def _analyze_all_rounds(self, question: str, trace: CognitiveTrace, rationale: str, all_rounds_log: str) -> Optional[dict]:
        try:
            ht = ""
            if trace.rational_synthesis:
                ht = "\\n".join(f"- {h}" for h in trace.rational_synthesis.hypotheses[:5])
            prompt = _FINAL_ANALYSIS_PROMPT.replace("{question}", question).replace("{hypotheses}", ht or "（无）").replace("{practice_rationale}", rationale or "（无）").replace("{all_rounds_log}", all_rounds_log[:6000])
            resp = await self.llm.call(messages=[{"role": "user", "content": "综合分析全部轮次实验结果。"}], system=prompt, temperature=0.3, max_tokens=self._analyze_max_tokens(), enable_reasoning=False)
            return self._parse_json_safe(resp.content, None)
        except Exception as e:
            log.warning("practice.analysis_error", error=str(e))
            return None

    async def _boundary_analysis(self, question: str, trace: CognitiveTrace, reason: str) -> Optional[dict]:
        """知性分析降级：无执行能力或规划失败时，用 V2 知性分析替代三轮实验。"""
        try:
            ht = ""
            if trace.rational_synthesis:
                ht = "\n".join(f"- {h}" for h in trace.rational_synthesis.hypotheses[:5])
            facts = ""
            if trace.investigation:
                facts = "\n".join(f"- {f.content[:150]}" for f in trace.investigation.facts[:6])
            prompt = (
                _BOUNDARY_ANALYSIS_PROMPT
                + "\n\n## 原始问题\n"
                + question
                + "\n\n## 调查事实\n"
                + (facts or "（无）")
                + "\n\n## 理性认识（假设）\n"
                + (ht or "（无）")
                + f"\n\n## 降级原因\n{reason}"
            )
            resp = await self.llm.call(
                messages=[{"role": "user", "content": "基于调查事实与矛盾分析，对核心主张做知性评估（V2）。"}],
                system=prompt,
                temperature=0.3,
                max_tokens=self._analyze_max_tokens(4096),
                enable_reasoning=False,
            )
            return self._parse_json_safe(resp.content, None)
        except Exception as e:
            log.warning("practice.boundary_analysis_error", error=str(e))
            return None

    def _build_epistemic_report(self, question: str, trace: CognitiveTrace, analysis: Optional[dict], mode: str, reason: str) -> PracticeReport:
        """构建 V2 知性分析报告（mode: partial / epistemic_only）。"""
        a = analysis or {}
        summary = (
            f"[{a.get('verdict', 'inconclusive')}] {a.get('analysis', '')}"
            if a else f"知性分析降级（{reason}），未能生成判定。"
        )
        summary = "[知性分析 V2，未执行工具实验] " + summary
        report = PracticeReport(
            mode=mode,
            confidence_ceiling="V2",
            steps_taken=[],
            observed_outcomes=[],
            unexpected_findings=[],
            practice_summary=summary,
            success_indicators=[],
            failure_indicators=[],
            contradiction_feedback=a.get("contradiction_feedback", []),
            analysis_summary=a.get("analysis", "") if a else "",
            claim_assessments=a.get("claim_assessments", []) if a else [],
            unexpected_insights=a.get("surprises", []) if a else [],
            reinvestigation_needed=bool(a.get("reinvestigation_needed", False)),
            reinvestigation_focus=a.get("reinvestigation_focus", "") if a else "",
            rounds=[],
            tool_call_records=[],
            action_records=[],
            verification_results=[],
            failure_classes=[],
            world_changed=False,
            cache_metrics=(
                self._current_wm.get_cache_metrics()
                if self._current_wm and hasattr(self._current_wm, "get_cache_metrics")
                else {}
            ),
        )
        log.info("practice.epistemic_report_built", mode=mode, reason=reason)
        return report

    @staticmethod
    def _direction_state_to_dict(state: DirectionStateUpdate) -> dict:
        if hasattr(state, "model_dump"):
            return state.model_dump(mode="json")
        return state.dict()

    def _update_direction_state(
        self,
        plan: dict,
        outcomes,
        failures,
        round_num: int = 0,
        detail: Optional[PracticeRound] = None,
    ) -> DirectionStateUpdate:
        """C5: persist a structured, non-verdict evidence update for the next round."""
        claim = str(plan.get("directional_claim") or "").strip()
        observations: list[str] = []
        technical_failures: list[str] = []
        decisive_classifications = {"observed", "world_changed"}
        technical_classifications = {
            "tool_error", "timeout", "permission_denied",
            "authorization_pending", "authorization_expired",
        }

        if detail:
            for record in detail.tool_calls:
                result = record.get("result") or {}
                tool_name = str(record.get("tool") or "unknown_tool")
                classification = str(result.get("state_classification") or "unknown")
                content = self._truncate(
                    result.get("content") or result.get("error") or classification,
                    180,
                )
                line = f"{tool_name} [{classification}]: {content}"
                if classification in technical_classifications or result.get("ok") is False:
                    technical_failures.append(line)
                else:
                    observations.append(line)
        else:
            observations.extend(
                str(item)[:180] for item in (outcomes or [])
                if not str(item).startswith("FAIL")
            )

        technical_failures.extend(str(item)[:180] for item in (failures or []))
        observations = list(dict.fromkeys(observations))[:6]
        technical_failures = list(dict.fromkeys(technical_failures))[:6]

        classifications = []
        if detail:
            classifications = [
                str((record.get("result") or {}).get("state_classification") or "")
                for record in detail.tool_calls
            ]
        if any(item in decisive_classifications for item in classifications):
            evidence_status = "effective_observation"
            impact = "已取得可用于认识更新的有效观测；支持、动摇或证伪仍由综合分析判定。"
        elif observations:
            evidence_status = "inconclusive"
            impact = "取得结果但尚不足以更新方向判断；验证失败或状态未变不能直接视为证伪。"
        elif technical_failures:
            evidence_status = "technical_failure"
            impact = "本轮发生技术中断，没有可用于否定方向锚点的有效观测。"
        else:
            evidence_status = "no_observation"
            impact = "本轮没有产生可审计的观测，方向锚点保持不变。"

        state = DirectionStateUpdate(
            round_num=round_num,
            directional_claim=claim,
            epistemic_role=str(plan.get("epistemic_role") or "exploration"),
            evidence_status=evidence_status,
            effective_observations=observations,
            technical_failures=technical_failures,
            impact=impact,
            next_focus=(
                f"下一轮继续围绕该论断闭合证据缺口：{claim[:160]}"
                if claim else "下一轮先从方向锚点中选择一个可检验论断。"
            ),
        )
        self._direction_state = state
        self._direction_state_update = json.dumps(
            self._direction_state_to_dict(state), ensure_ascii=False, indent=2,
        )
        return state

    async def _collect_background_results(self) -> list[dict]:
        completed = []
        still = {}
        for cmd, info in self._background_procs.items():
            p = info["proc"]
            if p.returncode is not None:
                try:
                    so, se = await p.communicate()
                except Exception:
                    so, se = b"", b""
                completed.append({"cmd": cmd, "returncode": p.returncode, "stdout": (so or b"").decode("utf-8","replace"), "stderr": (se or b"").decode("utf-8","replace"), "duration": time.time() - info["start_time"]})
            else:
                still[cmd] = info
        self._background_procs = still
        return completed

    def _collect_artifacts(self, round_detail, round_num: int) -> list[dict]:
        """从一轮的工具调用记录中提取产物（生成/修改的文件）。

        供下一轮上下文注入：模型可直接引用这些路径，不必猜。
        """
        artifacts: list[dict] = []
        for record in (round_detail.tool_calls or []):
            tool = record.get("tool")
            result = record.get("result") or {}
            if result.get("status") == "error":
                continue
            if tool == "file_write":
                path = (result.get("metadata") or {}).get("path") or (record.get("params") or {}).get("path", "")
                if path:
                    artifacts.append({"path": path, "tool": "file_write", "kind": "created", "round": round_num})
            elif tool == "file_edit":
                path = (result.get("metadata") or {}).get("path") or (record.get("params") or {}).get("path", "")
                if path:
                    artifacts.append({"path": path, "tool": "file_edit", "kind": "modified", "round": round_num})
            elif tool == "archive_extract":
                for name in ((result.get("data") or {}).get("extracted") or []):
                    artifacts.append({"path": name, "tool": "archive_extract", "kind": "extracted", "round": round_num})
        return artifacts

    def _merge_artifacts(self, new_artifacts: list[dict]) -> None:
        """并入新产物：同路径保留最新记录，避免台账重复条目无限增长。"""
        for a in new_artifacts:
            replaced = False
            for i, existing in enumerate(self._artifacts):
                if existing["path"] == a["path"]:
                    self._artifacts[i] = a
                    replaced = True
                    break
            if not replaced:
                self._artifacts.append(a)

    def _mark_artifacts_used(self, tool_calls: list[dict]) -> None:
        """标记本轮被引用/读取过的产物为活跃（供智能注入分层）。"""
        referenced = set()
        for record in (tool_calls or []):
            params = record.get("params") or {}
            for key in ("path", "query", "code_ref", "command"):
                val = params.get(key)
                if isinstance(val, str):
                    referenced.add(val)
        for a in self._artifacts:
            a["used"] = bool(referenced and a["path"] in referenced)

    def _artifacts_text(self) -> str:
        """智能注入：最近两轮 + 被引用过的产物全量；更早的只列路径提示可探索。"""
        items = getattr(self, "_artifacts", [])
        if not items:
            return "（暂无已生成的产物）"
        latest_round = max((a.get("round", 0) for a in items), default=0)
        active = [a for a in items if a.get("used") or a.get("round", 0) >= latest_round - 1]
        historical = [a for a in items if a not in active]

        lines = []
        for a in active:
            lines.append(f"- {a['path']}  [{a['tool']} / {a['kind']} / 第{a.get('round', '?')}轮]")
        if historical:
            paths = ", ".join(a["path"] for a in historical)
            lines.append(f"- （更早产物，未列详情，可直接用 file_list 探索工作区：{paths[:300]}）")
        return "\n".join(lines) if lines else "（暂无已生成的产物）"

    def _parse_json_safe(self, raw: str, default=None):
        if default is None: default = {}
        raw = raw.strip()
        while raw.startswith("```"):
            idx = raw.find("\n")
            raw = raw[idx+1:] if idx >= 0 else raw[3:]
        if raw.endswith("```"): raw = raw[:-3]
        raw = raw.strip().rstrip("`")
        for p in ["json\n", "json"]:
            if raw.startswith(p): raw = raw[len(p):]; break
        raw = raw.strip()
        try: return json.loads(raw)
        except json.JSONDecodeError:
            # 兜底：截取第一个 { 到最后一个 }（或 [ 到 ]）之间的子串再解析，
            # 容忍模型在 JSON 前后夹杂的解释性文字。
            fallback = self._extract_json_object(raw)
            if fallback is not None:
                try:
                    return json.loads(fallback)
                except json.JSONDecodeError:
                    pass
            for s in ['}', '}]}', ']}]}', '}]}]}']:
                try: return json.loads(raw + s)
                except json.JSONDecodeError: continue
            log.warning(
                "practice.json_parse_error",
                raw=raw[:500],
                endswith=raw[-80:],
            )
            return default

    @staticmethod
    def _extract_json_object(raw: str):
        """从任意文本中截取最外层 JSON 对象/数组子串。"""
        if not raw:
            return None
        import re
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start = raw.find(open_ch)
            end = raw.rfind(close_ch)
            if start != -1 and end != -1 and end > start:
                return raw[start:end + 1]
        return None
