"""会话作用域管理：SessionScope。

结构（对齐 dsh 双平面）：
- root context 挂 host 级进程单例（memory / skill-manager / settings 只读壳）；
- 每会话（conversation_id 优先，其次 project_id，否则默认 realm）一个
  ``realm``（root 的隔离子作用域）+ 一个 ``Fiber``；
- 会话状态（workspace / permission-policy / tool-registry / 工具行 /
  cognitive-loop）装进 realm，同 label 幂等复用；
- ``dispose(label)`` 幂等：fiber 先 cancel 后台任务并 await，再逆序清理
  其余 disposable（含授权等待过期），并释放 loop controller。

当前 realm 装配采用程序化方式，与 ``praxic/agent.yml`` 的服务行清单
一一对应；后续可改为组合驱动（patch 分层的前置）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import structlog

from praxic.cordis import Context, Fiber, Service
from praxic.core.assembly import CognitiveLoopService

from .host import (
    MemoryService,
    PermissionPolicyService,
    SkillManagerService,
    WorkspaceService,
)
from .tools import ToolRegistryService, ToolService

log = structlog.get_logger(__name__)

# 与 agent.yml 内置工具行一一对应（不增不减）
_TOOL_ROWS = (
    "python-exec",
    "workspace-tools",
    "shell",
    "web-search",
    "web-fetch",
    "user-context",
    "plugin-scan",
)

_DEFAULT_LABEL = "default"


class SettingsService(Service):
    """settings 只读壳：组合内按名解析全局配置（不持有副本）。"""

    def __init__(self, ctx, name=None, config=None):
        super().__init__(ctx, name, config)
        from praxic.config import settings

        self.settings = settings


@dataclass
class Realm:
    """一个会话 realm 及其生命周期容器。"""

    label: str
    ctx: Context
    fiber: Fiber
    project_id: str = ""


class SessionScope:
    """host（root）与 per-session realm 的管理器。"""

    def __init__(self, root_ctx: Context | None = None) -> None:
        self.root = root_ctx or Context()
        self._host_fiber = Fiber(self.root)
        self._realms: dict[str, Realm] = {}
        self._disposed_total = 0
        self._install_host()

    # ------------------------------------------------------------------
    # host 层（进程级单例）
    # ------------------------------------------------------------------
    def _install_host(self) -> None:
        """host 服务：llm / episodic+semantic（memory）/ skills（skill-manager）/ settings。"""
        from .llm import LLMService

        LLMService(self.root, name="llm")
        MemoryService(self.root, name="memory")
        SkillManagerService(self.root, name="skill-manager")
        SettingsService(self.root, name="settings")
        log.info("cordis.scope.host_installed")

    # ------------------------------------------------------------------
    # session 层
    # ------------------------------------------------------------------
    def get_or_create(self, label: str = "", project_id: str = "") -> Realm:
        """获取（或创建）会话 realm。同 label 幂等复用；已销毁则重建。"""
        key = label or project_id or _DEFAULT_LABEL
        realm = self._realms.get(key)
        if realm is None or realm.fiber.disposed:
            if realm is not None:
                self._realms.pop(key, None)
            realm = self._create_realm(key, project_id=project_id, conversation_id=label)
            self._realms[key] = realm
        return realm

    def _create_realm(self, key: str, project_id: str, conversation_id: str) -> Realm:
        realm_ctx = self.root.isolate("session", key)
        fiber = Fiber(realm_ctx)
        self._install_session(realm_ctx, fiber, project_id=project_id, conversation_id=conversation_id)
        return Realm(label=key, ctx=realm_ctx, fiber=fiber, project_id=project_id)

    def _install_session(
        self,
        realm_ctx: Context,
        fiber: Fiber,
        project_id: str,
        conversation_id: str,
    ) -> None:
        """session 服务：workspace / permission-policy / tool-registry / 工具行 / cognitive-loop。

        与 ``praxic/agent.yml`` 的 session 相关行一一对应。
        """
        WorkspaceService(realm_ctx, name="workspace", config={"project_id": project_id})
        PermissionPolicyService(realm_ctx, name="permission-policy")
        ToolRegistryService(realm_ctx, name="tool-registry")
        for tool_id in _TOOL_ROWS:
            ToolService(realm_ctx, name=tool_id)
        CognitiveLoopService(
            realm_ctx,
            name="cognitive-loop",
            config={"conversation_id": conversation_id, "project_id": project_id},
        )
        # dispose 时把悬挂授权等待全部过期（防协程/授权残留）
        fiber.register(lambda: self._expire_pending_authorizations(realm_ctx))

    @staticmethod
    def _expire_pending_authorizations(realm_ctx: Context) -> None:
        try:
            registry = realm_ctx.get("tool-registry").registry
        except Exception:  # noqa: BLE001 - 会话可能未完整装配
            return
        for request in list(registry.pending_authorizations):
            registry.policy.expire_request(request.request_id)
            log.info("cordis.scope.auth_expired", request_id=request.request_id)

    # ------------------------------------------------------------------
    # dispose
    # ------------------------------------------------------------------
    async def dispose(self, label: str = "") -> bool:
        """销毁会话 realm（幂等）。fiber 先 cancel 任务并 await，再逆序清理。"""
        key = label or _DEFAULT_LABEL
        realm = self._realms.pop(key, None)
        if realm is None:
            return False
        await realm.fiber.dispose()
        # loop controller 清理（与 cognitive_loop 内 release_conv_controller 幂等兼容）
        from praxic.core.loop_controller import release_conv_controller

        release_conv_controller(key)
        self._disposed_total += 1
        log.info("cordis.scope.realm_disposed", label=key)
        return True

    # ------------------------------------------------------------------
    # 观察
    # ------------------------------------------------------------------
    def live_count(self) -> int:
        return len(self._realms)

    def live_labels(self) -> list[str]:
        return list(self._realms)

    def live_realms(self) -> list[Realm]:
        return list(self._realms.values())

    @property
    def disposed_count(self) -> int:
        """累计销毁的 realm 数（泄漏断言用）。"""
        return self._disposed_total
