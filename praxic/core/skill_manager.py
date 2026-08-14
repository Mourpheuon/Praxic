"""
Praxic Agent -- 技能管理器
实现渐进式披露（Progressive Disclosure）:
  - Phase 1: 会话启动，只加载 YAML frontmatter 元数据
  - Phase 2: 阶段执行时，按需加载 SKILL.md 正文 + references/
"""
from __future__ import annotations
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
import structlog

from ..api.schemas.models import (
    CognitivePhaseName, SkillMetadata, SkillBody,
    SkillDraftCandidate, SkillValidationRecord,
)
from ..llm.base import BaseLLM

log = structlog.get_logger(__name__)


class SkillManager:
    """技能管理器。

    使用规则：
    1. 在 CognitiveLoop.__init__() 中实例化一次
    2. 每个 CognitiveLoop.run() 调用前，调用 inject_to_working_memory(wm)
    3. 各阶段模块通过 WorkingMemory.get_context_for_phase() 获得技能上下文
    """

    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)
        self.registry_path = self.skills_dir / "registry.json"
        self._catalog: dict[str, SkillMetadata] = {}
        self._phase_index: dict[str, list[str]] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        if not self.registry_path.exists():
            self._save_registry({
                "version": "1.0.0", "last_updated": "",
                "skills": [], "drafts": [],
            })
            return

        try:
            with open(self.registry_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # registry 损坏（如写入被中断而截断）绝不能拖垮整个 agent：
            # 备份损坏文件、以空注册表启动并告警，让Praxic仍能运行。
            backup = self.registry_path.with_suffix(".json.corrupt")
            try:
                shutil.copy(self.registry_path, backup)
            except OSError:
                backup = None
            log.warning("skill_manager.registry_corrupt",
                        error=str(e),
                        backup=str(backup) if backup else None)
            data = {"version": "1.0.0", "last_updated": "", "skills": [], "drafts": []}

        self._catalog.clear()
        self._phase_index.clear()

        for entry in data.get("skills", []):
            if entry.get("status") != "active":
                continue
            meta = SkillMetadata(**entry)
            self._catalog[meta.name] = meta
            for phase in meta.active_phases:
                self._phase_index.setdefault(phase, []).append(meta.name)

        log.info("skill_manager.loaded", count=len(self._catalog))

    def _save_registry(self, data: dict) -> None:
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        data["last_updated"] = datetime.now().isoformat()
        # 原子写入：先写临时文件、fsync、再 os.replace 原子替换，
        # 避免写入被中断而截断损坏整个 registry。
        tmp = self.registry_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.registry_path)

    # ── Phase 2: 按需加载 ─────────────────────────────

    def _load_skill_body(self, skill_name: str) -> Optional[SkillBody]:
        meta = self._catalog.get(skill_name)
        if not meta or not meta.file_path:
            return None

        skill_path = Path(meta.file_path)
        if not skill_path.exists():
            skill_path = self.skills_dir / skill_name / "SKILL.md"

        if not skill_path.exists():
            log.warning("skill_manager.file_not_found", skill=skill_name)
            return None

        with open(skill_path, encoding="utf-8") as f:
            raw = f.read()

        body = re.sub(r"^---\n.*?\n---\n", "", raw, flags=re.DOTALL).strip()

        phase_methods: dict[str, str] = {}
        methods_dir = skill_path.parent / "references" / "methods"
        if methods_dir.exists():
            for method_file in methods_dir.glob("*.md"):
                phase_name = method_file.stem
                with open(method_file, encoding="utf-8") as f:
                    phase_methods[phase_name] = f.read()

        return SkillBody(metadata=meta, body=body, phase_methods=phase_methods)

    def get_skills_for_phase(
        self, phase: str, wm, llm: Optional[BaseLLM] = None,
    ) -> list[SkillBody]:
        """Phase 2: 获取指定阶段应注入的技能列表."""
        from ..config import settings

        candidates = self._phase_index.get(phase, [])
        results: list[SkillBody] = []

        context_text = wm.get_context_for_phase(phase).lower()
        contradiction_ctx = ""
        try:
            contradiction_ctx = wm.get_contradiction_context().lower()
        except Exception:
            pass
        # 也纳入原始/扩展问题，提升触发命中率
        extra = ""
        try:
            extra = " ".join(str(wm.get(k, "")) for k in (
                "question", "expanded_question", "original_question",
                "question_domains",
            ))
        except Exception:
            pass
        combined_ctx = (context_text + " " + contradiction_ctx + " " + extra).lower()

        # 先按触发关键词命中数排序，命中越多越相关，避免通用词把无关技能挤进配额
        scored: list[tuple[int, str]] = []
        for skill_name in candidates:
            meta = self._catalog[skill_name]
            if meta.trigger_conditions:
                keywords = self._extract_keywords(meta.trigger_conditions)
                hits = sum(1 for kw in keywords if kw in combined_ctx)
                if hits == 0:
                    continue
            else:
                hits = 0  # 无触发条件的技能默认低优先级
            scored.append((hits, skill_name))

        scored.sort(key=lambda x: -x[0])
        max_skills = getattr(settings, "skill_max_per_phase", 3)

        for hits, skill_name in scored[:max_skills]:
            body = self._load_skill_body(skill_name)
            if body:
                results.append(body)
                self._catalog[skill_name].usage_count += 1
                log.info("skill_manager.triggered", skill=skill_name,
                         phase=phase, hits=hits)

        return results

    @staticmethod
    def _extract_keywords(conditions):
        """将触发条件（自然语言短语）切分为关键词。

        在多种分隔符（中英文逗号、顿号、分号、空格、括号等）上切分，
        过滤掉过短或无区分度的停用词，返回小写关键词列表。
        """
        _STOP = {
            "行动项", "涉及", "需要", "处理", "或", "和", "与", "的", "了",
            "以及", "包括", "进行", "使用", "相关", "数据", "任务",
        }
        keywords = []
        for cond in conditions:
            for tok in re.split(r"[，,、；;：:\s（）()【】\[\]/]+", cond):
                tok = tok.strip().lower()
                if len(tok) >= 2 and tok not in _STOP:
                    keywords.append(tok)
        return keywords

    def get_catalog_summary(self) -> str:
        if not self._catalog:
            return ""
        lines = ["## 已安装技能（按需激活）"]
        for meta in self._catalog.values():
            phases = ", ".join(
                p.value if hasattr(p, "value") else str(p)
                for p in meta.active_phases
            )
            lines.append(f"- **{meta.name}** [{phases}]: {meta.description}")
        return "\n".join(lines)

    def get_phase_skill_catalog(self, phase: str) -> str:
        """E1: 返回指定阶段可用技能的目录摘要（名称+一句话描述），不含正文。

        完整指令由 skill 工具按名加载。相位过滤：只列出在该阶段激活的技能，
        避免无关技能挤占上下文。
        """
        names = self._phase_index.get(phase, [])
        if not names:
            return ""
        lines = [f"## 本阶段可用技能（按需加载，需要时调用 skill(name) 取回完整指令）"]
        for name in names:
            meta = self._catalog.get(name)
            if meta:
                lines.append(f"- **{name}**: {meta.description}")
        return "\n".join(lines)

    def load_skill_body_for_tool(self, name: str) -> Optional[str]:
        """供 skill 工具按名加载完整指令（不含 YAML frontmatter）。"""
        body = self._load_skill_body(name)
        if body is None:
            return None
        return body.body if hasattr(body, "body") and body.body else str(getattr(body, "body", ""))

    def inject_to_working_memory(self, wm) -> None:
        summary = self.get_catalog_summary()
        if summary:
            wm.set("_skill_catalog_summary", summary)

    def inject_phase_skills(self, phase: str, wm) -> None:
        skills = self.get_skills_for_phase(phase, wm)
        if not skills:
            return

        parts: list[str] = []
        max_chars_per_skill = 4000

        for skill in skills:
            method_content = skill.phase_methods.get(phase, "")
            content = method_content if method_content else skill.body

            if len(content) > max_chars_per_skill:
                content = content[:max_chars_per_skill] + "\n\n[...技能内容已截断]"

            parts.append(f"### 技能: {skill.metadata.name}\n\n{content}")

        combined = "\n\n---\n\n".join(parts)
        wm.set_skill_context_for_phase(phase, combined)

    # ── 生命周期管理 ─────────────────────────────

    def create_skill(self, metadata: SkillMetadata, body: str) -> Path:
        skill_dir = self.skills_dir / metadata.name
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_path = skill_dir / "SKILL.md"
        frontmatter = self._metadata_to_frontmatter(metadata)
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(frontmatter + "\n\n" + body)

        metadata.file_path = str(skill_path)
        self._catalog[metadata.name] = metadata
        self._rebuild_phase_index()
        self._update_registry_entry(metadata)

        log.info("skill_manager.created", skill=metadata.name, status=metadata.status)
        return skill_path

    def create_draft(self, candidate: SkillDraftCandidate) -> Path:
        draft_name = f"auto-{candidate.suggested_name}"
        draft_dir = self.skills_dir / "drafts" / draft_name
        draft_dir.mkdir(parents=True, exist_ok=True)

        meta = SkillMetadata(
            name=draft_name,
            description=candidate.suggested_description,
            type=candidate.suggested_type,
            active_phases=candidate.suggested_active_phases,
            trigger_conditions=[candidate.trigger_pattern],
            created_by="auto",
            created_at=datetime.now().strftime("%Y-%m-%d"),
            status="draft",
            validation_count=0,
            validation_required=3,
            file_path=str(draft_dir / "SKILL.md"),
        )

        body = f"""# {draft_name}

> 自动蒸馏自会话 {candidate.extracted_from_session}
> 置信度 {candidate.confidence:.0%}

## 触发条件
{candidate.trigger_pattern}

## 核心操作
{candidate.core_operations}

## 注意事项
此技能为自动生成草稿，需经过 {meta.validation_required} 次验证后方可升级。
"""
        # 直接写入 draft_dir，保持草稿文件同目录（不经过 create_skill，
        # 后者会写到非草稿位置 skills_dir/<name>/ 并覆盖 file_path）
        skill_path = draft_dir / "SKILL.md"
        frontmatter = self._metadata_to_frontmatter(meta)
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(frontmatter + "\n\n" + body)

        self._catalog[meta.name] = meta
        self._update_registry_entry(meta)

        val_log = {"skill_name": draft_name, "records": []}
        with open(draft_dir / "validation_log.json", "w", encoding="utf-8") as f:
            json.dump(val_log, f, ensure_ascii=False, indent=2)

        log.info("skill_manager.draft_created", skill=draft_name,
                 confidence=candidate.confidence)
        return draft_dir

    def record_validation(self, skill_name: str, record: SkillValidationRecord) -> None:
        meta = self._catalog.get(skill_name)
        if not meta:
            log.warning("skill_manager.record_validation.not_found", skill=skill_name)
            return

        meta.validation_count += 1
        if record.practice_outcome == "confirmed":
            meta.success_rate = (
                (meta.success_rate * (meta.validation_count - 1) + 1.0)
                / meta.validation_count
            )
        else:
            meta.success_rate = (
                (meta.success_rate * (meta.validation_count - 1))
                / meta.validation_count
            )

        skill_path = Path(meta.file_path)
        skill_dir = skill_path.parent
        val_log_path = skill_dir / "validation_log.json"
        if val_log_path.exists():
            with open(val_log_path, encoding="utf-8") as f:
                val_log = json.load(f)
        else:
            val_log = {"skill_name": skill_name, "records": []}

        val_log["records"].append(record.model_dump())
        with open(val_log_path, "w", encoding="utf-8") as f:
            json.dump(val_log, f, ensure_ascii=False, indent=2)

        if (meta.status == "draft"
                and meta.validation_count >= meta.validation_required
                and meta.success_rate >= 0.6):
            meta.status = "validated"
            log.info("skill_manager.promoted_to_validated", skill=skill_name,
                     rate=meta.success_rate, count=meta.validation_count)

        self._update_registry_entry(meta)

    def promote_to_active(self, skill_name: str) -> None:
        meta = self._catalog.get(skill_name)
        if not meta or meta.status != "validated":
            return
        meta.status = "active"
        self._rebuild_phase_index()
        self._update_registry_entry(meta)
        log.info("skill_manager.promoted_to_active", skill=skill_name)

    def deprecate(self, skill_name: str, reason: str = "") -> None:
        meta = self._catalog.get(skill_name)
        if not meta:
            return
        meta.status = "deprecated"
        if skill_name in self._catalog:
            del self._catalog[skill_name]
        self._rebuild_phase_index()
        self._update_registry_entry(meta)
        log.info("skill_manager.deprecated", skill=skill_name, reason=reason)

    def lint(self) -> list[str]:
        issues: list[str] = []
        for name, meta in self._catalog.items():
            if not Path(meta.file_path).exists():
                issues.append(f"[BROKEN LINK] {name}: {meta.file_path} 不存在")
            if not meta.description:
                issues.append(f"[MISSING DESC] {name}: description 为空")
            if not meta.active_phases:
                issues.append(f"[NO PHASES] {name}: active_phases 为空")
        return issues

    # ── 内部工具 ─────────────────────────────

    def _metadata_to_frontmatter(self, meta: SkillMetadata) -> str:
        phases = [p.value if hasattr(p, "value") else str(p)
                  for p in meta.active_phases]
        lines = [
            "---",
            f"name: {meta.name}",
            f'description: "{meta.description}"',
            f"type: {meta.type}",
            f"version: {meta.version}",
            "active_phases:",
        ]
        for p in phases:
            lines.append(f"  - {p}")
        if meta.trigger_conditions:
            lines.append("trigger_conditions:")
            for tc in meta.trigger_conditions:
                lines.append(f'  - "{tc}"')
        if meta.hard_rules:
            lines.append("hard_rules:")
            for hr in meta.hard_rules:
                lines.append(f'  - "{hr}"')
        lines += [
            f"created_by: {meta.created_by}",
            f'created_at: "{meta.created_at}"',
            f"status: {meta.status}",
            f"validation_count: {meta.validation_count}",
            f"usage_count: {meta.usage_count}",
            f"success_rate: {meta.success_rate:.2f}",
            "---",
        ]
        return "\n".join(lines)

    def _rebuild_phase_index(self) -> None:
        self._phase_index.clear()
        for meta in self._catalog.values():
            if meta.status != "active":
                continue
            for phase in meta.active_phases:
                self._phase_index.setdefault(phase, []).append(meta.name)

    def _update_registry_entry(self, meta: SkillMetadata) -> None:
        if not self.registry_path.exists():
            data = {"version": "1.0.0", "last_updated": "",
                    "skills": [], "drafts": []}
        else:
            with open(self.registry_path, encoding="utf-8") as f:
                data = json.load(f)

        entry_dict = meta.model_dump()
        entry_dict["active_phases"] = [
            p.value if hasattr(p, "value") else str(p)
            for p in meta.active_phases
        ]

        target_list = "drafts" if meta.status == "draft" else "skills"
        found = False
        for i, entry in enumerate(data.get(target_list, [])):
            if entry.get("name") == meta.name:
                data[target_list][i] = entry_dict
                found = True
                break
        if not found:
            data.setdefault(target_list, []).append(entry_dict)

        self._save_registry(data)
