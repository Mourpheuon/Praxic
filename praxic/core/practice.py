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
    RealWorldPracticeTask,
)
from ..config import PhaseConfig, load_phase_prompt, settings
from ..llm.base import BaseLLM
from ..tools.filesystem import WorkspaceToolkit
from ..tools.base import ActionKind, ToolCallRecord, ToolStatus
from ..tools.registry import ToolRegistry
from ..tools.permissions import PermissionPolicy
from ..tools.shell import ShellTool
from ..tools.filesystem import FileReadTool, FileWriteTool, FileListTool, FileDeleteTool
from ..tools.python_exec import PythonExecTool

from . import practice_harness as harness

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

## 输出格式（严格 JSON）
{
  "verdict": "confirmed|partially_confirmed|challenged|falsified|inconclusive|execution_error",
  "analysis": "3-5句综合分析",
  "surprises": ["意外发现"],
  "confidence_change": "可信度变化说明",
  "reinvestigation_needed": false,
  "reinvestigation_focus": "",
  "key_findings": ["发现1", "发现2"],
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
        self.max_retries = max_retries
        self.practice_rounds = practice_rounds
        self._background_procs: dict[str, dict] = {}
        self._fallback_registry: ToolRegistry | None = None

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
        decision_report=None,
        steering_checkpoint: callable = None,
    ) -> Optional[PracticeReport]:
        # 兼容迁移前的第三位置调用：practice(question, trace, decision)
        # 与当前回调签名可以共存，新的调用优先使用关键字参数。
        if decision_report is None and on_progress is not None and not callable(on_progress):
            decision_report = on_progress
            on_progress = None

        def _notify(summary: str, data=None):
            if on_progress:
                on_progress("practice", summary, data=data)

        self._current_question = question
        if decision_report is not None and trace.decision is None:
            trace.decision = decision_report
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
        all_call_records: list[dict] = []
        all_action_records: list[dict] = []
        all_verification_results: list[dict] = []
        failure_classes: list[str] = []
        world_changed = False
        overall_rationale = ""

        r1_plan = await self._plan_round1(question, trace, wm=wm)
        overall_rationale = r1_plan.get("round_rationale", "")

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

        for r in range(2, self.practice_rounds + 1):
            bg_results = await self._collect_background_results()
            if bg_results:
                for bg in bg_results:
                    bg_log = f"[后台完成] {bg['cmd'][:60]} exit={bg['returncode']} dur={bg['duration']:.1f}s"
                    full_execution_log.append(bg_log)

            ctx = self._build_next_round_context(r, question, trace, round_contexts, full_execution_log)
            rn_plan = await self._plan_next_round(ctx)
            if rn_plan.get("done"):
                log.info("practice.rounds_done_early", rounds_completed=r - 1)
                break

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
            rounds=round_records,
            tool_call_records=all_call_records,
            action_records=all_action_records,
            verification_results=all_verification_results,
            failure_classes=failure_classes,
            world_changed=world_changed,
            cache_metrics=wm.get_cache_metrics() if wm and hasattr(wm, "get_cache_metrics") else {},
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
        policy = PermissionPolicy(allowed_roots=roots)
        registry = ToolRegistry(policy=policy)
        if workspace:
            registry.register(FileReadTool(workspace))
            registry.register(FileWriteTool(workspace))
            registry.register(FileListTool(workspace))
            registry.register(FileDeleteTool(workspace))
            registry.register(PythonExecTool(workspace_dir=workspace))
            registry.register(ShellTool(allowed_roots=roots))
        self._fallback_registry = registry
        return registry

    # ── Round 1 planning ──

    async def _plan_round1(self, question: str, trace: CognitiveTrace, wm=None) -> dict:
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
        decision_text = "（尚未形成独立行动编排）"
        if trace.decision:
            action_lines = []
            for item in trace.decision.action_items[:6]:
                action_lines.append(
                    f"- [{item.practice_feasibility}] {item.description}"
                    f"；预期：{item.expected_outcome[:120]}"
                )
            decision_text = (
                f"战略评估：{trace.decision.strategic_assessment[:500]}\n"
                "行动项：\n" + ("\n".join(action_lines) or "（无）")
            )

        prompt = harness.R1_PLAN
        if wm:
            try:
                skill_ctx = wm.get("_skill_context_practice", "")
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
        prompt = prompt.replace("{decision_text}", decision_text)

        plan = await self._call_planner(prompt, "基于前序认知产出，设计第一轮实验。提炼可检验论断，设计工具调用序列。")
        return plan

    async def _plan_next_round(self, ctx: dict) -> dict:
        prompt = harness.RN_PLAN
        for key, value in ctx.items():
            prompt = prompt.replace("{" + key + "}", str(value))
        return await self._call_planner(prompt, f"规划第 {ctx.get('round_num', '?')} 轮实验，done=true 可提前结束。")

    async def _call_planner(self, system_prompt: str, user_msg: str) -> dict:
        try:
            resp = await self.llm.call(
                messages=[{"role": "user", "content": user_msg}],
                system=system_prompt,
                temperature=getattr(self.config, "temperature", 0.4),
                max_tokens=getattr(self.config, "max_tokens", 8192),
            )
            plan = self._parse_json_safe(resp.content.strip(), {})
            if not plan:
                raise ValueError("empty plan")
            plan.setdefault("round_rationale", "")
            plan.setdefault("tool_calls", [])
            plan.setdefault("expected_outcomes", [])
            return plan
        except Exception as e:
            log.warning("practice.plan_error", error=str(e))
            return {"round_rationale": f"规划失败: {str(e)[:100]}", "tool_calls": [], "expected_outcomes": []}

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
        for tc in tool_calls:
            tool_name = tc.get("tool", "")
            params = tc.get("params", {})
            if not tool_name:
                continue
            result = await registry.call(tool_name, **params) if registry else None
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
                log_parts.append(f"[{tool_name}] {classification}: {(result.content or '')[:200]}")
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
                log_parts.append(f"[{tool_name}] FAIL: {err}")
                outcomes.append(f"FAIL {tool_name}")
                failure.append(f"{tool_name}: {err}")
                steps.append(PracticeStep(
                    description=f"失败 {tool_name}", action_taken=str(params)[:200],
                    observed_result=err[:300], matched_expectation=False, tool=tool_name,
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

    async def _normalise_tool_calls(self, plan: dict) -> list[dict]:
        """Accept the current tool_calls schema and the earlier file/command schema."""
        calls = list(plan.get("tool_calls") or [])
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
        response = await self.llm.call(
            messages=[{"role": "user", "content": f"为文件 {path} 生成可运行内容。用途：{purpose}"}],
            system=prompt,
            temperature=getattr(self.config, "temperature", 0.3),
            max_tokens=getattr(self.config, "max_tokens", 8192),
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
        decision_text = "（尚未形成独立行动编排）"
        if trace.decision:
            decision_text = trace.decision.summary[:500] or trace.decision.strategic_assessment[:500]
            actions = [
                f"- [{item.practice_feasibility}] {item.description[:160]}"
                for item in trace.decision.action_items[:6]
            ]
            if actions:
                decision_text += "\n" + "\n".join(actions)
        prev = round_contexts[-1] if round_contexts else {}
        return {
            "round_num": str(round_num), "question": question,
            "facts_text": "\\n".join(facts_lines) or "（无）", "gaps_text": "\\n".join(gaps_lines) or "（无）",
            "contradiction_text": ct, "essence_text": et, "hypotheses_text": ht,
            "decision_text": decision_text,
            "prev_round_num": str(prev.get("round_num", round_num - 1)),
            "prev_round_plan": prev.get("plan_json", "（无）")[:3000],
            "prev_round_results": prev.get("results", "（无）")[:3000],
            "prev_round_duration": prev.get("duration", "未知"),
            "all_rounds_log": "\\n\\n".join(full_execution_log)[:4000] if full_execution_log else "（无）",
        }

    def _summarise_round(self, r: int, plan: dict, outcomes, unexpected, failures, all_ok):
        return f"第{r}轮: {plan.get('round_rationale','')[:100]} ok={all_ok}"

    async def _analyze_all_rounds(self, question: str, trace: CognitiveTrace, rationale: str, all_rounds_log: str) -> Optional[dict]:
        try:
            ht = ""
            if trace.rational_synthesis:
                ht = "\\n".join(f"- {h}" for h in trace.rational_synthesis.hypotheses[:5])
            prompt = _FINAL_ANALYSIS_PROMPT.replace("{question}", question).replace("{hypotheses}", ht or "（无）").replace("{decision_summary}", ht or "（无）").replace("{practice_rationale}", rationale or "（无）").replace("{all_rounds_log}", all_rounds_log[:6000])
            resp = await self.llm.call(messages=[{"role": "user", "content": "综合分析全部轮次实验结果。"}], system=prompt, temperature=0.3, max_tokens=1024)
            raw = resp.content.strip()
            while raw.startswith("```"):
                idx = raw.find("\\n")
                raw = raw[idx+1:] if idx >= 0 else raw[3:]
            if raw.endswith("```"): raw = raw[:-3]
            return json.loads(raw.strip().rstrip("`"))
        except Exception as e:
            log.warning("practice.analysis_error", error=str(e))
            return None

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

    def _parse_json_safe(self, raw: str, default=None):
        if default is None: default = {}
        raw = raw.strip()
        while raw.startswith("```"):
            idx = raw.find("\\n")
            raw = raw[idx+1:] if idx >= 0 else raw[3:]
        if raw.endswith("```"): raw = raw[:-3]
        raw = raw.strip().rstrip("`")
        for p in ["json\\n", "json"]:
            if raw.startswith(p): raw = raw[len(p):]; break
        raw = raw.strip()
        try: return json.loads(raw)
        except json.JSONDecodeError:
            for s in ['}', '}]}', ']}]}', '}]}]}']:
                try: return json.loads(raw + s)
                except json.JSONDecodeError: continue
            log.warning("practice.json_parse_error", raw=raw[:200])
            return default
