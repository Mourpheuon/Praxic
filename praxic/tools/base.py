"""
即物穷理 Praxic —— 工具基类
定义所有工具的统一接口
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"


class ActionKind(str, Enum):
    """The kind of contact a tool has with the world."""

    OBSERVE = "observe"
    COMPUTE = "compute"
    CHANGE = "change"
    EXTERNAL = "external"
    VERIFY = "verify"


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_AUTHORIZATION = "require_authorization"


class VerificationStatus(str, Enum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


def _jsonable(value: Any) -> Any:
    """Convert result data to deterministic, JSON-safe primitives."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {
            str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def stable_digest(value: Any) -> str:
    """Return a stable digest for evidence and change records."""
    payload = json.dumps(
        _jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class PermissionRecord:
    decision: PermissionDecision
    reason: str = ""
    scope: str = ""
    authorization_id: str = ""
    request_id: str = ""
    requested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return _jsonable(self)


@dataclass
class ChangeRecord:
    target: str = ""
    operation: str = ""
    before_digest: str = ""
    after_digest: str = ""
    changed: Optional[bool] = None
    reversible: bool = False
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _jsonable(self)


@dataclass
class VerificationResult:
    status: VerificationStatus = VerificationStatus.NOT_RUN
    summary: str = ""
    expected: Any = None
    observed: Any = None
    checks: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in (VerificationStatus.PASSED, VerificationStatus.SKIPPED)

    def to_dict(self) -> dict:
        return _jsonable(self)


@dataclass
class ToolResult:
    status: ToolStatus
    content: str  # 主要结果文本（供 LLM 消费）
    data: Any = None  # 结构化数据（可选）
    error: str = ""
    source: str = ""  # 来源 URL 或路径
    metadata: dict = field(default_factory=dict)
    action_kind: ActionKind = ActionKind.COMPUTE
    permission: Optional[PermissionRecord] = None
    change: Optional[ChangeRecord] = None
    verification: Optional[VerificationResult] = None
    call_id: str = ""
    started_at: str = ""
    duration_ms: float = 0.0
    failure_class: str = ""

    @property
    def ok(self) -> bool:
        return self.status != ToolStatus.ERROR

    @property
    def world_changed(self) -> Optional[bool]:
        if self.change is not None:
            return self.change.changed
        value = self.metadata.get("world_changed")
        return value if isinstance(value, bool) else None

    @property
    def state_classification(self) -> str:
        """Classify an outcome without conflating execution and world state."""
        if self.permission:
            if self.permission.decision == PermissionDecision.REQUIRE_AUTHORIZATION:
                return "authorization_pending"
            if self.permission.decision == PermissionDecision.DENY:
                if self.failure_class == "authorization_expired":
                    return "authorization_expired"
                return "permission_denied"
        if self.status == ToolStatus.ERROR:
            return self.failure_class or "tool_error"
        if self.verification and self.verification.status == VerificationStatus.FAILED:
            return "verification_failed"
        if (
            self.action_kind in (ActionKind.CHANGE, ActionKind.EXTERNAL)
            and self.world_changed is None
        ):
            return "change_unverified"
        if (
            self.action_kind in (ActionKind.CHANGE, ActionKind.EXTERNAL)
            and self.world_changed is False
        ):
            return "world_unchanged"
        if self.world_changed is True:
            return "world_changed"
        return "observed"

    def to_dict(self) -> dict:
        """Stable structured representation for logs, SSE and later analysis."""
        payload = _jsonable(self)
        payload["ok"] = self.ok
        payload["world_changed"] = self.world_changed
        payload["state_classification"] = self.state_classification
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def __str__(self) -> str:
        if not self.ok:
            return f"[ERROR] {self.error}"
        return self.content


class BaseTool(ABC):
    """工具基类 —— 所有工具必须实现这个接口"""

    name: str = "base_tool"
    description: str = "基础工具"
    requires_network: bool = False
    action_kind: ActionKind = ActionKind.COMPUTE
    requires_authorization: bool = False
    authorization_reason: str = ""
    sandbox_safe: bool = False
    parameter_schema: dict[str, dict[str, Any]] = {}

    @abstractmethod
    async def run(self, **kwargs) -> ToolResult:
        """执行工具，返回 ToolResult"""
        ...

    async def verify(self, params: dict, result: ToolResult) -> VerificationResult:
        """Read back a side effect when the tool can provide independent evidence."""
        return VerificationResult(status=VerificationStatus.SKIPPED, summary="工具未定义回读验证")

    def target_from_params(self, params: dict) -> str:
        for key in ("path", "url", "cwd", "target"):
            value = params.get(key)
            if value:
                return str(value)
        return ""

    def classify_action(self, params: dict) -> ActionKind:
        return self.action_kind

    def describe(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "action_kind": self.action_kind.value,
            "requires_network": self.requires_network,
            "requires_authorization": self.requires_authorization,
            "sandbox_safe": self.sandbox_safe,
            "parameters": _jsonable(self.parameter_schema),
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name})"


@dataclass
class ToolCallRecord:
    call_id: str = field(default_factory=lambda: uuid4().hex)
    tool: str = ""
    parameters: dict = field(default_factory=dict)
    action_kind: ActionKind = ActionKind.COMPUTE
    status: ToolStatus = ToolStatus.ERROR
    started_at: str = ""
    duration_ms: float = 0.0
    result: Optional[ToolResult] = None

    @classmethod
    def from_result(
        cls,
        tool: str,
        parameters: dict,
        action_kind: ActionKind,
        result: ToolResult,
    ) -> "ToolCallRecord":
        return cls(
            call_id=result.call_id,
            tool=tool,
            parameters=parameters,
            action_kind=action_kind,
            status=result.status,
            started_at=result.started_at,
            duration_ms=result.duration_ms,
            result=result,
        )

    def to_dict(self) -> dict:
        payload = _jsonable(self)
        if self.result is not None:
            payload["result"] = self.result.to_dict()
        return payload
