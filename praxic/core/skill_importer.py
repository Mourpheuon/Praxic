"""
Praxic Agent -- 技能导入器 (SkillImporter)

把 praxic/skills/ 下的外部 Claude 格式技能（裸露的 SKILL.md）适配为Praxic五阶段
技能系统可用的技能，写入 registry.json。

混合策略：
  - 确定性：解析 YAML frontmatter + 依据 IMPORT_RULES.md 的关键词表预判阶段/触发词/兼容性
  - LLM 精炼：让 LLM 依据规则文件判定 active_phases 与生成 trigger_conditions
       （--no-llm 时跳过，仅用确定性结果）

规则来源：praxic/skills/IMPORT_RULES.md（权威规则文件，人可编辑、机可解析）。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog
import yaml

from ..llm.base import BaseLLM

log = structlog.get_logger(__name__)

_VALID_PHASES = {
    "investigation", "contradiction", "rational",
    "practice", "reflection",
}


class SkillImporter:
    """外部技能 → Praxic技能系统的适配导入器。"""

    def __init__(
        self,
        skills_dir: Path,
        rules_path: Optional[Path] = None,
        llm: Optional[BaseLLM] = None,
    ):
        self.skills_dir = Path(skills_dir)
        self.registry_path = self.skills_dir / "registry.json"
        self.rules_path = Path(rules_path) if rules_path else (self.skills_dir / "IMPORT_RULES.md")
        self.llm = llm
        self._rules = self._load_rules()

    # -- 规则加载 --------------------------------------------------

    def _load_rules(self) -> dict:
        """从 IMPORT_RULES.md 解析机读 YAML 块 + LLM 提示模板。"""
        if not self.rules_path.exists():
            log.warning("skill_importer.rules_missing", path=str(self.rules_path))
            return self._default_rules()
        text = self.rules_path.read_text(encoding="utf-8")

        yaml_blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
        rules = {}
        if yaml_blocks:
            try:
                rules = yaml.safe_load(yaml_blocks[0]) or {}
            except yaml.YAMLError as e:
                log.warning("skill_importer.rules_yaml_error", error=str(e))
                rules = {}

        prompt_blocks = re.findall(r"```text\n(.*?)```", text, re.DOTALL)
        rules["_llm_prompt_template"] = prompt_blocks[0] if prompt_blocks else ""

        base = self._default_rules()
        base.update({k: v for k, v in rules.items() if v})
        return base

    @staticmethod
    def _default_rules() -> dict:
        return {
            "phase_keywords": {p: [] for p in _VALID_PHASES},
            "compatibility_keywords": {},
            "default_phase": "practice",
            "import_policy": {
                "default_status": "active",
                "skip_if_registered": True,
                "max_trigger_conditions": 6,
                "min_phases": 1,
                "max_phases": 3,
            },
            "_llm_prompt_template": "",
        }

    @property
    def _policy(self) -> dict:
        return self._rules.get("import_policy", {})

    # -- frontmatter 解析 ------------------------------------------

    @staticmethod
    def parse_skill_file(skill_md: Path) -> tuple[dict, str]:
        """返回 (frontmatter_dict, body)。"""
        raw = skill_md.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.DOTALL)
        if not m:
            return {}, raw.strip()
        fm_text, body = m.group(1), m.group(2)
        try:
            fm = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError:
            fm = {}
        if not isinstance(fm, dict):
            fm = {}
        return fm, body.strip()

    # -- 确定性预判 ------------------------------------------------

    def _heuristic_phases(self, text: str) -> list[str]:
        text_l = text.lower()
        hits: list[tuple[str, int]] = []
        for phase, kws in self._rules.get("phase_keywords", {}).items():
            n = sum(1 for kw in kws if kw.lower() in text_l)
            if n > 0:
                hits.append((phase, n))
        hits.sort(key=lambda x: -x[1])
        max_phases = self._policy.get("max_phases", 3)
        phases = [p for p, _ in hits[:max_phases]]
        if not phases:
            phases = [self._rules.get("default_phase", "practice")]
        return phases

    def _compat_flags(self, text: str) -> list[str]:
        text_l = text.lower()
        flags = []
        for flag, kws in self._rules.get("compatibility_keywords", {}).items():
            if any(kw.lower() in text_l for kw in kws):
                flags.append(flag)
        return flags

    def _heuristic_triggers(self, text: str) -> list[str]:
        text_l = text.lower()
        found = []
        for kws in self._rules.get("phase_keywords", {}).values():
            for kw in kws:
                if kw.lower() in text_l and kw not in found:
                    found.append(kw)
        cap = self._policy.get("max_trigger_conditions", 6)
        return found[:cap]

    # -- LLM 精炼 --------------------------------------------------

    async def _llm_classify(
        self, name: str, description: str, body: str,
        heuristic_phases: list[str], compat_flags: list[str],
    ) -> Optional[dict]:
        if not self.llm:
            return None
        template = self._rules.get("_llm_prompt_template", "")
        if not template:
            return None
        body_excerpt = body[:600]
        prompt = (template
                  .replace("{name}", name)
                  .replace("{description}", description[:800])
                  .replace("{body_excerpt}", body_excerpt)
                  .replace("{heuristic_phases}", ", ".join(heuristic_phases))
                  .replace("{compat_flags}", ", ".join(compat_flags) or "native"))
        try:
            resp = await self.llm.call(
                messages=[{"role": "user", "content": f"适配技能：{name}"}],
                system=prompt,
                temperature=0.2,
                max_tokens=1024,
            )
            raw = resp.content.strip()
            raw = re.sub(r"^```(json)?\n?", "", raw)
            raw = raw.rstrip("`").rstrip()
            if raw.endswith("```"):
                raw = raw[:-3]
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception as e:
            log.warning("skill_importer.llm_classify_failed", skill=name, error=str(e))
            return None

    # -- 单个技能适配 ---------------------------------------------

    async def build_entry(self, skill_md: Path, use_llm: bool = True) -> Optional[dict]:
        fm, body = self.parse_skill_file(skill_md)
        name = fm.get("name") or skill_md.parent.name
        description = fm.get("description", "") or ""
        if not description:
            description = body[:200]

        combined = f"{name} {description} {body[:1000]}"
        heuristic_phases = self._heuristic_phases(combined)
        compat_flags = self._compat_flags(combined)
        heuristic_triggers = self._heuristic_triggers(combined)

        active_phases = heuristic_phases
        trigger_conditions = heuristic_triggers
        skill_type = "execution"
        hard_rules: list[str] = []
        not_for: list[str] = []
        compatibility = compat_flags[0] if compat_flags else "native"
        reason = "确定性关键词映射"

        if use_llm:
            llm_out = await self._llm_classify(
                name, description, body, heuristic_phases, compat_flags,
            )
            if llm_out:
                lp = [p for p in llm_out.get("active_phases", []) if p in _VALID_PHASES]
                if lp:
                    active_phases = lp[: self._policy.get("max_phases", 3)]
                lt = [t for t in llm_out.get("trigger_conditions", []) if t]
                if lt:
                    trigger_conditions = lt[: self._policy.get("max_trigger_conditions", 6)]
                skill_type = llm_out.get("type", skill_type) or skill_type
                hard_rules = llm_out.get("hard_rules", []) or []
                not_for = llm_out.get("not_for", []) or []
                compatibility = llm_out.get("compatibility", compatibility) or compatibility
                reason = llm_out.get("reason", reason) or reason

        if not active_phases:
            active_phases = [self._rules.get("default_phase", "practice")]
        if not trigger_conditions:
            trigger_conditions = [name]

        entry = {
            "name": name,
            "description": description[:500],
            "type": skill_type,
            "version": str(fm.get("version", "1.0.0")),
            "active_phases": active_phases,
            "trigger_conditions": trigger_conditions,
            "hard_rules": hard_rules,
            "not_for": not_for,
            "created_by": "import",
            "created_at": datetime.now().strftime("%Y-%m-%d"),
            "status": self._policy.get("default_status", "active"),
            "validation_count": 0,
            "validation_required": 3,
            "usage_count": 0,
            "success_rate": 0.0,
            "last_used_at": None,
            "file_path": str(skill_md),
            "depends_on": [],
            "import_compatibility": compatibility,
            "import_reason": reason,
        }
        return entry

    # -- 批量导入 -------------------------------------------------

    def _discover(self) -> list[Path]:
        """递归发现 SKILL.md，排除组件子目录，浅层优先（便于同名去重时保留顶层）。"""
        exclude_segments = {
            "references", "templates", "examples", "assets",
            "scripts", "node_modules", "agents", "canvas-fonts",
        }
        found: list[Path] = []
        for skill_md in self.skills_dir.rglob("SKILL.md"):
            rel_parts = skill_md.relative_to(self.skills_dir).parts[:-1]
            if any(seg in exclude_segments for seg in rel_parts):
                continue
            found.append(skill_md)
        found.sort(key=lambda p: (len(p.relative_to(self.skills_dir).parts), str(p)))
        return found

    def _load_registry(self) -> dict:
        if self.registry_path.exists():
            return json.loads(self.registry_path.read_text(encoding="utf-8"))
        return {"version": "1.0.0", "last_updated": "", "skills": [], "drafts": []}

    def _save_registry(self, data: dict) -> None:
        data["last_updated"] = datetime.now().isoformat()
        # 原子写入：先写临时文件、fsync、再 os.replace 原子替换，
        # 避免导入被中断（timeout/kill）时把 registry.json 截断成坏 JSON。
        tmp = self.registry_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.registry_path)

    async def import_all(
        self, use_llm: bool = True, dry_run: bool = False,
        limit: Optional[int] = None, force: bool = False,
    ) -> dict:
        """扫描并导入全部技能。返回报告 dict。"""
        registry = self._load_registry()
        existing = {s.get("name") for s in registry.get("skills", [])}
        skip_registered = self._policy.get("skip_if_registered", True) and not force

        skill_files = self._discover()
        if limit:
            skill_files = skill_files[:limit]

        report = {
            "scanned": len(skill_files),
            "imported": [], "skipped": [], "failed": [],
        }
        seen_this_run: set[str] = set()

        for skill_md in skill_files:
            name = skill_md.parent.name
            try:
                fm, _ = self.parse_skill_file(skill_md)
                real_name = fm.get("name") or name
                if real_name in seen_this_run:
                    report["skipped"].append({"name": real_name, "why": "duplicate name in scan"})
                    continue
                if skip_registered and real_name in existing:
                    report["skipped"].append({"name": real_name, "why": "already registered"})
                    continue

                entry = await self.build_entry(skill_md, use_llm=use_llm)
                if not entry:
                    report["failed"].append({"name": real_name, "why": "build failed"})
                    continue
                seen_this_run.add(entry["name"])

                report["imported"].append({
                    "name": entry["name"],
                    "phases": entry["active_phases"],
                    "triggers": entry["trigger_conditions"],
                    "compatibility": entry["import_compatibility"],
                    "reason": entry["import_reason"],
                })

                if not dry_run:
                    skills = registry.setdefault("skills", [])
                    idx = next((i for i, s in enumerate(skills)
                                if s.get("name") == entry["name"]), None)
                    if idx is not None:
                        skills[idx] = entry
                    else:
                        skills.append(entry)
                    existing.add(entry["name"])
                log.info("skill_importer.imported", skill=entry["name"],
                         phases=entry["active_phases"], dry_run=dry_run)
            except Exception as e:
                log.warning("skill_importer.failed", skill=name, error=str(e))
                report["failed"].append({"name": name, "why": str(e)[:120]})

        if not dry_run:
            self._save_registry(registry)

        report["registry_total"] = len(registry.get("skills", []))
        return report
