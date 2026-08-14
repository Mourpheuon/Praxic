"""Praxic Agent -- 工作记忆"""
from __future__ import annotations
from typing import Any, Optional
from ..api.schemas.models import ContradictionGraph
from .context_cache import ContextBlock, ContextCompiler, GLOBAL_CONTEXT_COMPILER

class WorkingMemory:
    def __init__(self, session_id="", project_id="", model="", context_compiler: ContextCompiler | None = None):
        self.session_id = session_id
        self.project_id = project_id
        self.model = model
        self._store = {}
        self._phase_history = []
        self._context_compiler = context_compiler or GLOBAL_CONTEXT_COMPILER
        self._last_context = None

    def set(self, key, value):
        self._store[key] = value
        if str(key).startswith("_world_") or key in {
            "_uploaded_files_context", "practice_surprises", "reinvestigation_focus",
        }:
            self.invalidate_context(reason=f"context_changed:{key}")

    def get(self, key, default=None):
        return self._store.get(key, default)

    def record_phase(self, phase, summary, data=None):
        self._phase_history.append({"phase": phase, "summary": summary, "data": data})

    def set_contradiction(self, graph):
        self._store["_contradiction_graph"] = graph
        summary_parts = []
        if graph.principal_contradiction:
            pc = graph.principal_contradiction
            summary_parts.append("[主要矛盾] %s\n  矛盾方面：%s\n  主要方面：%s\n  转化条件：%s" % (pc.description, ' vs '.join(pc.tension_poles), pc.primary_aspect, pc.transformation_condition))
        for i, sc in enumerate(graph.secondary_contradictions, 1):
            summary_parts.append("[次要矛盾%d] %s\n  主要方面：%s" % (i, sc.description, sc.primary_aspect))
        if graph.dynamic_note:
            summary_parts.append("[矛盾动态] %s" % graph.dynamic_note)
        self._store["_contradiction_context"] = "\n\n".join(summary_parts)

    def get_contradiction_context(self):
        return self._store.get("_contradiction_context", "")

    def get_contradiction_graph(self):
        return self._store.get("_contradiction_graph")

    def get_context_for_phase(self, phase, model: str = "", token_budget: int = 0):
        parts = []
        user_context = str(self._store.get("context", "") or "").strip()
        if user_context and phase != "practice":
            parts.append("## 用户补充背景（本轮）\n" + user_context)
        conversation_history = str(self._store.get("conversation_history", "") or "").strip()
        if conversation_history:
            parts.append("## 当前对话前文（用于理解本轮追问）\n" + conversation_history)
        # 当前日期时间（全阶段无条件可见）——“今天几号”“现在几点”直接据此回答，
        # 不要当作需要调查搜索的信息缺口。
        cur_dt = self._store.get("_current_datetime", "")
        if cur_dt:
            parts.append("## 当前时间\n%s（智能体运行环境的本地时间）" % cur_dt)
        # 问题预处理——注入扩展后的问题理解
        eq = self._store.get("expanded_question", "")
        qi = self._store.get("question_intent", "")
        qd = self._store.get("question_domains", [])
        ciq = self._store.get("contradiction_in_question", "")
        ca = self._store.get("core_anxiety", "")
        qp = self._store.get("questionable_premises", [])
        of = self._store.get("overlooked_factors", [])
        ssq = self._store.get("structured_sub_questions", [])
        if eq:
            preprocess_lines = ["## 问题预处理（入口阶段对用户问题的深度解析）", "扩展问题：" + eq]
            if qi:
                preprocess_lines.append("用户意图：" + qi)
            if qd:
                preprocess_lines.append("相关领域：" + "、".join(qd))
            if ciq:
                preprocess_lines.append("问题表面呈现的张力（用户视角的提法，非最终判断；矛盾分析阶段须独立认定主要矛盾，勿默认此即主要矛盾的两极）：" + ciq)
            if ca:
                preprocess_lines.append("用户深层关切：" + ca)
            if qp:
                preprocess_lines.append("⚠ 待核实的预设（不可当作已证实事实；调查阶段须优先证伪/证实，其他阶段勿在其上直接推理）：\n  - " + "\n  - ".join(qp))
            if of:
                preprocess_lines.append("＋ 被用户框架遗漏、需一并考察的力量/因素（勿只围绕用户点名的对象；调查须为其取证，矛盾分析须将其纳入系统要素）：\n  - " + "\n  - ".join(of))
            if ssq:
                preprocess_lines.append("结构化子问题：\n  - " + "\n  - ".join(ssq))
            parts.append("\n".join(preprocess_lines))
        ri = self._store.get("reinvestigation_focus", "")
        if ri:
            parts.append("[重新调查方向] %s" % ri)
        li = self._store.get("last_investigation", "")
        if li and phase != "investigation":
            parts.append("[上轮调查摘要] %s" % li)
        if phase != "contradiction":
            cc = self.get_contradiction_context()
            if cc:
                if phase == "investigation":
                    parts.append("## 上一轮识别的矛盾结构（作为本轮调查的检验对象：可验证、深化或推翻，勿默认其为正确）\n%s" % cc)
                else:
                    parts.append("## 当前矛盾结构（贯穿本轮所有阶段）\n%s" % cc)
        if phase in ("rational", "practice", "reflection"):
            sm = self._store.get("_system_model")
            if sm:
                element_names = [e.name for e in sm.elements]
                fb_summary = "; ".join(
                    "[%s] %s" % (f.loop_type, f.description[:60])
                    for f in sm.feedback_loops
                )
                parts.append(
                    "## 系统模型（贯穿矛盾分析之后的各阶段）\n"
                    "要素：%s\n"
                    "反馈回路：%s" % ("、".join(element_names), fb_summary)
                )
        # 技能上下文（Phase 2 按需加载的技能正文，由 SkillManager.inject_phase_skills 注入）
        skill_ctx = self._store.get("_skill_context_%s" % phase, "")
        if skill_ctx:
            parts.append("## 可用技能引导（优先复用，无需从零实现）\n%s" % skill_ctx)
        # 用户上传文件（仅注入调查阶段；后续阶段基于调查提炼的事实工作，避免 token 膨胀）
        if phase == "investigation":
            uploaded = self._store.get("_uploaded_files_context", "")
            if uploaded:
                parts.append("## 用户上传的文件内容\n%s" % uploaded)
        # Agent 角色设定与用户自定义知识（全阶段可见）
        persona = self._store.get("_persona_context", "")
        if persona:
            parts.append(persona)
        blocks = [
            ContextBlock(name=f"{phase}:{index}", content=content, stable=True)
            for index, content in enumerate(parts)
            if content
        ]
        compiled = self._context_compiler.compile(
            blocks,
            session_id=self.session_id,
            project_id=self.project_id,
            model=model or self.model,
            token_budget=token_budget,
        )
        self._last_context = compiled
        return compiled.content

    def invalidate_context(self, reason: str = ""):
        self._context_compiler.invalidate_scope(
            session_id=self.session_id,
            project_id=self.project_id,
            reason=reason or "working_memory_changed",
        )

    def get_cache_metrics(self) -> dict:
        report = self._context_compiler.cache_report()
        # Keep the historical flat counters while exposing the separated
        # context and local-KV reports for newer clients.
        metrics = dict(report["context"])
        metrics["context"] = report["context"]
        metrics["kv_cache"] = report["kv_cache"]
        metrics["kv_capabilities"] = report["kv_capabilities"]
        metrics["session_id"] = self.session_id
        metrics["project_id"] = self.project_id
        if self._last_context is not None:
            metrics["last_context"] = self._last_context.to_dict()
        return metrics

    def set_skill_context_for_phase(self, phase, content):
        self._store[f"_skill_context_{phase}"] = content

    def get_skill_catalog_summary(self):
        return self._store.get("_skill_catalog_summary", "")

    def get_full_history(self):
        return list(self._phase_history)

    def clear(self):
        self.invalidate_context(reason="working_memory_clear")
        self._store.clear()
        self._phase_history.clear()

    def __repr__(self):
        return "WorkingMemory(session=%s, keys=%s)" % (self.session_id, list(self._store.keys()))
