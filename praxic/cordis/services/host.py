"""host 级服务壳：workspace / memory / permission-policy / skill-manager。

P2 阶段这些服务将挂到 root context 成为进程级单例；P1 阶段它们只是
组合路径下被声明的可解析服务，行为与旧构造路径一致。
"""

from __future__ import annotations

from pydantic import BaseModel

from praxic.cordis import Service


class WorkspaceService(Service):
    """workspace 服务：项目感知目录，语义与 CognitiveLoop 旧逻辑一致。"""

    class Config(BaseModel):
        project_id: str = ""

    def __init__(self, ctx, name=None, config=None):
        super().__init__(ctx, name, config)
        from praxic.config import settings
        from praxic.tools.filesystem import WorkspaceToolkit

        if self.config.project_id:
            ws = settings.projects_dir / self.config.project_id / "workspace"
            ws.mkdir(parents=True, exist_ok=True)
            self.workspace = WorkspaceToolkit(ws)
        else:
            self.workspace = WorkspaceToolkit(settings.workspace_dir)


class MemoryService(Service):
    """memory 服务：episodic + semantic 记忆库（进程级单例，P2 挂 root）。"""

    def __init__(self, ctx, name=None, config=None):
        super().__init__(ctx, name, config)
        from praxic.memory.episodic_memory import EpisodicMemory
        from praxic.memory.semantic_memory import SemanticMemory

        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()


class PermissionPolicyService(Service):
    """permission-policy 服务：构造与旧路径同参的 PermissionPolicy。

    AUTO_REVIEW 模式下挂上 LLM 语义审核器（组合路径用 llm 服务壳的
    原始 LLM，行为等价；dev tracing 差异在 P2 统一）。
    """

    def __init__(self, ctx, name=None, config=None):
        super().__init__(ctx, name, config)
        from praxic.config import settings
        from praxic.core.autonomy import PermissionMode
        from praxic.tools.permissions import PermissionPolicy

        workspace_svc = ctx.get("workspace")
        ws = workspace_svc.workspace if workspace_svc else None
        self.policy = PermissionPolicy(
            permission_mode=settings.permission_mode,
            allowed_roots=(ws.workspace,) if ws else (),
            allow_network=settings.web_search_enabled,
        )
        if settings.permission_mode == PermissionMode.AUTO_REVIEW:
            from praxic.core.reviewer import build_reviewer

            llm_svc = ctx.get("llm")
            self.policy.reviewer = build_reviewer(llm_svc.get())


class SkillManagerService(Service):
    """skill-manager 服务：技能管理器（进程级单例，P2 挂 root）。"""

    def __init__(self, ctx, name=None, config=None):
        super().__init__(ctx, name, config)
        from pathlib import Path

        from praxic.config import settings
        from praxic.core.skill_manager import SkillManager

        skills_dir = getattr(settings, "skills_dir", None)
        if skills_dir is None:
            skills_dir = Path("praxic/skills")
        self.skill_manager = SkillManager(skills_dir)
