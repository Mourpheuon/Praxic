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


_TRUNCATE_MARKER = "[... 中段省略 ...]"


def head_tail_truncate(
    text: object,
    *,
    head_chars: int = 4096,
    tail_chars: int = 1024,
    max_len: int = 0,
) -> str:
    """A2: 保头尾截断，替换只留头的硬截断。

    超阈值时保留头部（关键输出/结构化开头）+ 尾部（错误信息、最新状态），
    中间用 marker 替代。默认阈值为 head+tail+marker；若显式给出 max_len，
    则在守恒约束下等比缩小 head/tail。
    """
    s = str(text or "")
    if max_len and max_len > 0:
        total = max_len
        head, tail = head_chars, tail_chars
        # 阈值守恒：head+tail+marker ≤ total
        if head + tail + len(_TRUNCATE_MARKER) > total:
            scale = (total - len(_TRUNCATE_MARKER)) / (head + tail)
            head = max(1, int(head * scale))
            tail = max(1, int(tail * scale))
    else:
        total = head_chars + tail_chars + len(_TRUNCATE_MARKER)
        head, tail = head_chars, tail_chars
    if len(s) <= total:
        return s
    return s[:head] + _TRUNCATE_MARKER + s[-tail:]


def ensure_summary(result, *, head_chars: int = 300, tail_chars: int = 120) -> str:
    """A1: 从 ToolResult 提取一句话摘要，供回填上下文使用。

    统一处理管道（所有类型输出同一条规则）：
    - error：保头尾错误信息（自纠需求，错误信息常在尾部）；
    - 成功 + 显式 summary：直接用 summary（结论型工具提供，摘要即结论）；
    - 成功 + 无 summary：统一占位指向（内容型自然落入此处，不搬正文）。

    框架不再猜测输出类型（content/conclusion/auto 启发式全部移除）：
    是否可摘要由工具作者在返回点显式声明（给 summary 就可摘要，
    不给就占位）——fail-closed：默认不搬，显式放行才搬。
    """
    if result is None:
        return ""
    explicit = getattr(result, "summary", "") or ""
    if not result.ok:
        return head_tail_truncate(
            getattr(result, "error", "") or getattr(result, "state_classification", "tool_error"),
            head_chars=head_chars,
            tail_chars=tail_chars,
        )
    if explicit:
        return explicit
    content = getattr(result, "content", "") or ""
    if not content:
        return getattr(result, "state_classification", "observed")
    return f"（{len(content)} 字符，见日志/产物）"


@dataclass
class PermissionRecord:
    decision: PermissionDecision
    reason: str = ""
    scope: str = ""
    authorization_id: str = ""
    request_id: str = ""
    requested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # AUTO_REVIEW 模式下硬规则未通过，标记需要语义审核；由调用方决定是否调用 reviewer。
    review_requested: bool = False

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
    # A1: 人类可读的一句话结论。实践阶段回填下一轮上下文时用 summary 替代
    # content 全量，避免模型把前一轮工具原始输出整段抄进规划导致 JSON 超长截断。
    # 统一管道：有 summary 则直接用；无 summary 且成功则占位指向（不搬正文）；
    # 失败则保头尾错误信息。摘要责任在工具作者（给 summary 就可摘要，不给就占位）。
    summary: str = ""

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
    """工具基类 —— 所有工具必须实现这个接口

    category：工具分类（file/data/network/system/code/physical/user/knowledge），
              用于渐进式披露的阶段映射。
    group：同质工具组。组内只披露一个代表，其余按需展开（如 web_search 组）。
    """

    name: str = "base_tool"
    description: str = "基础工具"
    category: str = "misc"
    group: str = ""
    requires_network: bool = False
    action_kind: ActionKind = ActionKind.COMPUTE
    requires_authorization: bool = False
    authorization_reason: str = ""
    sandbox_safe: bool = False
    # B1: 只读工具是否可并行。默认为 False（fail-closed：未显式声明一律串行），
    # 只有 file_read / data_query / web_search 等无副作用工具显式声明为 True。
    is_concurrency_safe: bool = False
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
            "category": self.category,
            "group": self.group,
            "action_kind": self.action_kind.value,
            "requires_network": self.requires_network,
            "requires_authorization": self.requires_authorization,
            "sandbox_safe": self.sandbox_safe,
            "is_concurrency_safe": self.is_concurrency_safe,
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
