"""Permission and path-scope primitives for real-world actions.

The policy deliberately keeps observation separate from mutation.  A tool may
read or compute automatically, while a mutation outside an explicitly scoped
workspace needs an authorization grant that can be shown in the activity log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import time
from uuid import uuid4

from ..core.autonomy import AutonomyLevel
from .base import (
    ActionKind,
    PermissionDecision,
    PermissionRecord,
)


class PathGuard:
    """Resolve paths without allowing traversal outside configured roots."""

    def __init__(self, roots: list[str | Path] | tuple[str | Path, ...] = ()):
        self.roots = tuple(Path(root).resolve() for root in roots)

    def resolve(self, path: str | Path, *, allow_missing: bool = True) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            if not self.roots:
                raise PermissionError("未配置允许的路径根目录")
            candidate = self.roots[0] / candidate
        target = candidate.resolve(strict=False)
        if not self.is_allowed(target):
            roots = ", ".join(str(root) for root in self.roots) or "(none)"
            raise PermissionError(f"路径越界：{path!r} 不在允许范围 {roots} 内")
        if not allow_missing and not target.exists():
            raise FileNotFoundError(str(target))
        return target

    def is_allowed(self, path: str | Path) -> bool:
        target = Path(path).resolve(strict=False)
        return any(target == root or root in target.parents for root in self.roots)


@dataclass
class AuthorizationGrant:
    grant_id: str = field(default_factory=lambda: "grant_" + uuid4().hex)
    scope: str = ""
    expires_at: float = 0.0
    metadata: dict = field(default_factory=dict)

    def active(self) -> bool:
        return self.expires_at > time()


@dataclass
class AuthorizationRequest:
    """A pending approval request that can be rendered and audited by the UI."""

    request_id: str = field(default_factory=lambda: "authreq_" + uuid4().hex)
    tool_name: str = ""
    action_kind: ActionKind = ActionKind.EXTERNAL
    parameters: dict = field(default_factory=dict)
    scope: str = ""
    reason: str = ""
    status: str = "pending"  # pending | approved | denied | expired
    grant_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: str = ""

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "action_kind": self.action_kind.value,
            "parameters": dict(self.parameters),
            "scope": self.scope,
            "reason": self.reason,
            "status": self.status,
            "grant_id": self.grant_id,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


@dataclass
class PermissionPolicy:
    """Central decision point used by the tool registry."""

    autonomy_level: AutonomyLevel = AutonomyLevel.STANDARD
    allowed_roots: tuple[str | Path, ...] = ()
    auto_authorize_sandbox: bool = True
    allow_network: bool = True
    _grants: dict[str, AuthorizationGrant] = field(default_factory=dict, init=False)
    _records: list[PermissionRecord] = field(default_factory=list, init=False)
    _requests: dict[str, AuthorizationRequest] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.path_guard = PathGuard(self.allowed_roots)

    @property
    def records(self) -> list[PermissionRecord]:
        return list(self._records)

    @property
    def requests(self) -> list[AuthorizationRequest]:
        return list(self._requests.values())

    def get_request(self, request_id: str) -> AuthorizationRequest | None:
        return self._requests.get(request_id)

    def pending_requests(self) -> list[AuthorizationRequest]:
        return [request for request in self._requests.values() if request.status == "pending"]

    def issue_grant(
        self, scope: str = "", ttl_seconds: float = 900.0, **metadata
    ) -> AuthorizationGrant:
        ttl_seconds = float(ttl_seconds)
        if ttl_seconds <= 0:
            raise ValueError("授权有效期必须大于 0 秒")
        grant = AuthorizationGrant(
            scope=scope,
            expires_at=time() + ttl_seconds,
            metadata=metadata,
        )
        self._grants[grant.grant_id] = grant
        return grant

    def revoke_grant(self, grant_id: str) -> bool:
        return self._grants.pop(grant_id, None) is not None

    def create_authorization_request(
        self,
        *,
        tool_name: str,
        action_kind: ActionKind,
        params: dict,
        scope: str,
        reason: str,
    ) -> AuthorizationRequest:
        request = AuthorizationRequest(
            tool_name=tool_name,
            action_kind=action_kind,
            parameters=dict(params),
            scope=scope,
            reason=reason,
        )
        self._requests[request.request_id] = request
        return request

    def resolve_request(
        self,
        request_id: str,
        *,
        approved: bool,
        ttl_seconds: float = 900.0,
    ) -> AuthorizationGrant | None:
        request = self._requests.get(request_id)
        if request is None or request.status != "pending":
            return None
        request.resolved_at = datetime.now(timezone.utc).isoformat()
        if not approved:
            request.status = "denied"
            return None
        grant = self.issue_grant(
            scope=request.scope,
            ttl_seconds=ttl_seconds,
            tool_name=request.tool_name,
            action_kind=request.action_kind.value,
            request_id=request.request_id,
        )
        request.status = "approved"
        request.grant_id = grant.grant_id
        return grant

    def expire_request(self, request_id: str) -> bool:
        request = self._requests.get(request_id)
        if request is None or request.status != "pending":
            return False
        request.status = "expired"
        request.resolved_at = datetime.now(timezone.utc).isoformat()
        return True

    def _record(
        self,
        decision: PermissionDecision,
        reason: str,
        scope: str,
        authorization_id: str = "",
        request_id: str = "",
    ) -> PermissionRecord:
        record = PermissionRecord(
            decision=decision,
            reason=reason,
            scope=scope,
            authorization_id=authorization_id,
            request_id=request_id,
        )
        self._records.append(record)
        return record

    def record_decision(
        self,
        decision: PermissionDecision,
        reason: str,
        scope: str = "",
        *,
        authorization_id: str = "",
        request_id: str = "",
    ) -> PermissionRecord:
        """Record a terminal decision for an authorization lifecycle."""
        return self._record(
            decision,
            reason,
            scope,
            authorization_id=authorization_id,
            request_id=request_id,
        )

    def check(
        self,
        *,
        tool_name: str,
        action_kind: ActionKind,
        params: dict,
        sandbox_safe: bool = False,
        requires_authorization: bool = False,
        requires_network: bool = False,
        authorization_id: str = "",
    ) -> PermissionRecord:
        target = str(params.get("path") or params.get("target") or params.get("cwd") or "")

        if requires_network and not self.allow_network:
            return self._record(PermissionDecision.DENY, "网络工具已被策略禁用", target)

        if action_kind in (ActionKind.OBSERVE, ActionKind.COMPUTE, ActionKind.VERIFY):
            return self._record(PermissionDecision.ALLOW, "读取、计算或验证操作自动允许", target)

        grant = self._grants.get(authorization_id) if authorization_id else None
        if grant is not None and grant.active():
            tool_matches = not grant.metadata.get("tool_name") or (
                grant.metadata["tool_name"] == tool_name
            )
            action_matches = not grant.metadata.get("action_kind") or (
                grant.metadata["action_kind"] == action_kind.value
            )
            scope_matches = self._scope_matches(grant.scope, target)
            if tool_matches and action_matches and scope_matches:
                return self._record(
                    PermissionDecision.ALLOW, "使用了有效授权", target, authorization_id
                )

        if (
            action_kind == ActionKind.CHANGE
            and sandbox_safe
            and self.auto_authorize_sandbox
            and self.allowed_roots
        ):
            if target:
                try:
                    self.path_guard.resolve(target)
                except (PermissionError, OSError) as exc:
                    return self._record(PermissionDecision.DENY, str(exc), target)
            if self.autonomy_level >= AutonomyLevel.SANDBOXED:
                return self._record(PermissionDecision.ALLOW, "限定在工作区内的沙箱变更", target)

        reason = "外部副作用需要授权" if action_kind == ActionKind.EXTERNAL else "变更操作需要授权"
        if requires_authorization or action_kind in (ActionKind.CHANGE, ActionKind.EXTERNAL):
            return self._record(PermissionDecision.REQUIRE_AUTHORIZATION, reason, target)

        return self._record(PermissionDecision.DENY, "当前自主级别不允许该操作", target)

    @staticmethod
    def _scope_matches(scope: str, target: str) -> bool:
        if not scope:
            return True
        if scope == target:
            return True
        normal_scope = scope.replace("/", "\\").rstrip("\\")
        normal_target = target.replace("/", "\\")
        return normal_target.startswith(normal_scope + "\\")
