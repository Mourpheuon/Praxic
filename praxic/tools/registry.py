"""
Praxic Agent —— 工具注册中心
管理所有可用工具的注册、查找和调用。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

import structlog

from .base import (
    ActionKind,
    BaseTool,
    PermissionDecision,
    ToolCallRecord,
    ToolResult,
    ToolStatus,
)
from .permissions import AuthorizationRequest, PermissionPolicy

log = structlog.get_logger(__name__)


class ToolRegistry:
    """全局工具注册表。"""

    def __init__(
        self,
        policy: PermissionPolicy | None = None,
        event_sink: Callable[[dict], None] | None = None,
        authorization_timeout_seconds: float = 900.0,
    ):
        self._tools: dict[str, BaseTool] = {}
        self.policy = policy or PermissionPolicy()
        self.event_sink = event_sink
        self.authorization_timeout_seconds = authorization_timeout_seconds
        self._records: list[ToolCallRecord] = []
        self._authorization_events: dict[str, asyncio.Event] = {}

    def register(self, tool: BaseTool) -> None:
        """注册一个工具实例。"""
        self._tools[tool.name] = tool
        log.info("tool_registry.registered", name=tool.name, cls=tool.__class__.__name__)

    def get(self, name: str) -> BaseTool | None:
        """按名称查找工具。"""
        return self._tools.get(name)

    def get_names(self) -> list[str]:
        """返回所有已注册的工具名。"""
        return list(self._tools.keys())

    @property
    def records(self) -> list[ToolCallRecord]:
        return list(self._records)

    def clear_records(self) -> None:
        self._records.clear()

    def issue_authorization(self, scope: str = "", ttl_seconds: float = 900.0, **metadata):
        return self.policy.issue_grant(scope, ttl_seconds, **metadata)

    def revoke_authorization(self, grant_id: str) -> bool:
        return self.policy.revoke_grant(grant_id)

    @property
    def pending_authorizations(self) -> list[AuthorizationRequest]:
        return self.policy.pending_requests()

    def authorization_status(self, request_id: str) -> dict | None:
        request = self.policy.get_request(request_id)
        return request.to_dict() if request else None

    def approve_authorization(self, request_id: str, ttl_seconds: float = 900.0) -> dict | None:
        request = self.policy.get_request(request_id)
        if request is None or request.status != "pending":
            return None
        grant = self.policy.resolve_request(request_id, approved=True, ttl_seconds=ttl_seconds)
        request = self.policy.get_request(request_id)
        if request is None or grant is None:
            return None
        event = self._authorization_events.get(request_id)
        if event:
            event.set()
        payload = request.to_dict()
        self._emit(
            {
                "event_type": "authorization_resolved",
                "request_id": request_id,
                "summary": "授权已批准，继续执行原行动",
                "authorization": payload,
            }
        )
        return payload

    def deny_authorization(self, request_id: str) -> dict | None:
        request = self.policy.get_request(request_id)
        if request is None or request.status != "pending":
            return None
        self.policy.resolve_request(request_id, approved=False)
        request = self.policy.get_request(request_id)
        if request is None or request.status != "denied":
            return None
        event = self._authorization_events.get(request_id)
        if event:
            event.set()
        payload = request.to_dict()
        self._emit(
            {
                "event_type": "authorization_resolved",
                "request_id": request_id,
                "summary": "授权已拒绝，行动不会执行",
                "authorization": payload,
            }
        )
        return payload

    def _emit(self, event: dict) -> None:
        if self.event_sink is None:
            return
        try:
            self.event_sink(event)
        except Exception:
            log.warning("tool_registry.event_sink_error", exc_info=True)

    def call_sync(self, name: str, **params) -> ToolResult:
        """
        同步调用工具（内部用 asyncio.run 包裹）。
        当调用方本身不在 async 上下文时使用。
        """
        import asyncio

        return asyncio.run(self.call(name, **params))

    async def call(self, name: str, **params) -> ToolResult:
        """异步调用工具。"""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"未知工具: {name}，可用工具: {', '.join(self._tools.keys())}",
            )

        call_id = uuid4().hex
        started_at = datetime.now(timezone.utc).isoformat()
        started = perf_counter()
        params = dict(params)
        authorization_id = str(params.pop("_authorization_id", ""))
        authorization_timeout = float(
            params.pop("_authorization_timeout_seconds", self.authorization_timeout_seconds)
        )
        # Runtime-only values are never included in authorization requests or
        # tool records. The practice phase uses this channel to pass the
        # already-held background text after approval without exposing it while
        # the request is waiting in the UI.
        runtime_user_context = params.pop("_user_context", None)
        tool_params = dict(params)
        if runtime_user_context is not None:
            tool_params["_user_context"] = runtime_user_context
        action_kind = (
            tool.classify_action(params)
            if hasattr(tool, "classify_action")
            else getattr(tool, "action_kind", ActionKind.COMPUTE)
        )
        if not isinstance(action_kind, ActionKind):
            action_kind = ActionKind(str(action_kind))
        safe_params = _redact_params(params)
        permission = self.policy.check(
            tool_name=name,
            action_kind=action_kind,
            params=params,
            sandbox_safe=getattr(tool, "sandbox_safe", False),
            requires_authorization=getattr(tool, "requires_authorization", False),
            authorization_reason=getattr(tool, "authorization_reason", ""),
            requires_network=getattr(tool, "requires_network", False),
            authorization_id=authorization_id,
        )
        if permission.decision == PermissionDecision.REQUIRE_AUTHORIZATION:
            request = self.policy.create_authorization_request(
                tool_name=name,
                action_kind=action_kind,
                params=safe_params,
                scope=str(params.get("path") or params.get("target") or params.get("cwd") or ""),
                reason=permission.reason,
            )
            permission.request_id = request.request_id
            request_id = request.request_id
            event = asyncio.Event()
            self._authorization_events[request.request_id] = event
            self._emit(
                {
                    "event_type": "authorization_requested",
                    "request_id": request.request_id,
                    "tool": name,
                    "summary": "等待授权后执行 " + name,
                    "authorization": request.to_dict(),
                }
            )
            try:
                try:
                    if authorization_timeout > 0:
                        await asyncio.wait_for(event.wait(), timeout=authorization_timeout)
                    else:
                        await event.wait()
                except asyncio.CancelledError:
                    expired = self.policy.expire_request(request_id)
                    resolved_request = self.policy.get_request(request_id)
                    if expired and resolved_request is not None:
                        self._emit(
                            {
                                "event_type": "authorization_resolved",
                                "request_id": resolved_request.request_id,
                                "summary": "授权等待已取消，行动不会执行",
                                "authorization": resolved_request.to_dict(),
                            }
                        )
                    raise
                except asyncio.TimeoutError:
                    expired = self.policy.expire_request(request_id)
                    resolved_request = self.policy.get_request(request_id)
                    if expired and resolved_request is not None:
                        self._emit(
                            {
                                "event_type": "authorization_resolved",
                                "request_id": resolved_request.request_id,
                                "summary": "授权等待已超时，行动不会执行",
                                "authorization": resolved_request.to_dict(),
                            }
                        )
                    if resolved_request is None or resolved_request.status != "approved":
                        permission = self.policy.record_decision(
                            PermissionDecision.DENY,
                            "授权等待超时，行动未执行",
                            resolved_request.scope if resolved_request else "",
                            request_id=(
                                resolved_request.request_id if resolved_request else request_id
                            ),
                        )
                        result = ToolResult(
                            status=ToolStatus.ERROR,
                            content="",
                            error=permission.reason,
                            action_kind=action_kind,
                            permission=permission,
                            call_id=call_id,
                            started_at=started_at,
                            failure_class="authorization_expired",
                        )
                        self._finish_record(name, safe_params, action_kind, result, started)
                        return result
                resolved_request = self.policy.get_request(request_id)
                if resolved_request is None or resolved_request.status != "approved":
                    permission = self.policy.record_decision(
                        PermissionDecision.DENY,
                        "授权已拒绝，行动未执行",
                        resolved_request.scope if resolved_request else "",
                        request_id=resolved_request.request_id if resolved_request else "",
                    )
                    result = ToolResult(
                        status=ToolStatus.ERROR,
                        content="",
                        error=permission.reason,
                        action_kind=action_kind,
                        permission=permission,
                        call_id=call_id,
                        started_at=started_at,
                        failure_class="permission_denied",
                    )
                    self._finish_record(name, safe_params, action_kind, result, started)
                    return result
                permission = self.policy.check(
                    tool_name=name,
                    action_kind=action_kind,
                    params=params,
                    sandbox_safe=getattr(tool, "sandbox_safe", False),
                    requires_authorization=getattr(tool, "requires_authorization", False),
                    authorization_reason=getattr(tool, "authorization_reason", ""),
                    requires_network=getattr(tool, "requires_network", False),
                    authorization_id=resolved_request.grant_id,
                )
                permission.request_id = request_id
                if permission.decision != PermissionDecision.ALLOW:
                    result = ToolResult(
                        status=ToolStatus.ERROR,
                        content="",
                        error=permission.reason,
                        action_kind=action_kind,
                        permission=permission,
                        call_id=call_id,
                        started_at=started_at,
                        failure_class="permission_denied",
                    )
                    self._finish_record(name, safe_params, action_kind, result, started)
                    return result
            finally:
                self._authorization_events.pop(request_id, None)
        if permission.decision != PermissionDecision.ALLOW:
            result = ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=permission.reason,
                action_kind=action_kind,
                permission=permission,
                call_id=call_id,
                started_at=started_at,
                failure_class="permission_denied",
            )
            self._finish_record(name, safe_params, action_kind, result, started)
            return result
        try:
            result = await tool.run(**tool_params)
            if not isinstance(result, ToolResult):
                result = ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=str(result),
                    data=result,
                )
            result.action_kind = action_kind
            result.permission = permission
            result.call_id = call_id
            result.started_at = started_at
            result.duration_ms = round((perf_counter() - started) * 1000, 3)
            try:
                result.verification = await tool.verify(params, result)
            except Exception as exc:
                log.warning("tool_registry.verification_error", tool=name, error=str(exc))
                from .base import VerificationResult, VerificationStatus

                result.verification = VerificationResult(
                    status=VerificationStatus.FAILED,
                    summary=f"回读验证异常：{exc}",
                )
                result.failure_class = "verification_failed"
            if result.status == ToolStatus.ERROR and not result.failure_class:
                result.failure_class = "tool_error"
            self._finish_record(name, safe_params, action_kind, result, started)
            return result
        except Exception as e:
            log.warning("tool_registry.call_error", tool=name, error=str(e))
            result = ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"工具 {name} 调用失败: {e}",
                action_kind=action_kind,
                permission=permission,
                call_id=call_id,
                started_at=started_at,
                duration_ms=round((perf_counter() - started) * 1000, 3),
                failure_class="tool_error",
            )
            self._finish_record(name, safe_params, action_kind, result, started)
            return result

    def _finish_record(
        self,
        name: str,
        params: dict,
        action_kind: ActionKind,
        result: ToolResult,
        started: float,
    ) -> None:
        result.duration_ms = result.duration_ms or round((perf_counter() - started) * 1000, 3)
        record = ToolCallRecord.from_result(name, params, action_kind, result)
        self._records.append(record)
        result.metadata = dict(result.metadata or {})
        result.metadata.update(
            {
                "call_id": result.call_id,
                "tool": name,
                "action_kind": action_kind.value,
                "state_classification": result.state_classification,
            }
        )
        self._emit(
            {
                "event_type": "tool_call",
                "call_id": result.call_id,
                "tool": name,
                "summary": _result_summary(name, result),
                "record": record.to_dict(),
            }
        )

    def tool_descriptions(self) -> list[dict]:
        """返回所有工具的 JSON 描述列表，供 LLM 规划工具调用时参考。"""
        descs = []
        for name, tool in self._tools.items():
            if hasattr(tool, "describe"):
                descs.append(tool.describe())
                continue
            desc = {"name": name, "description": getattr(tool, "description", "")}
            # 尝试获取参数类型信息（BaseTool 子类可通过 run 方法的签名暴露参数）
            import inspect

            sig = inspect.signature(tool.run)
            params = {}
            for pname, param in sig.parameters.items():
                if pname == "self" or pname == "kwargs":
                    continue
                ptype = "string"
                if param.annotation is not inspect.Parameter.empty:
                    ann = str(param.annotation)
                    if "int" in ann:
                        ptype = "integer"
                    elif "float" in ann:
                        ptype = "number"
                    elif "bool" in ann:
                        ptype = "boolean"
                    elif "list" in ann:
                        ptype = "array"
                    elif "dict" in ann:
                        ptype = "object"
                default = None
                if param.default is not inspect.Parameter.empty:
                    default = param.default
                params[pname] = {
                    "type": ptype,
                    "default": None if default is inspect.Parameter.empty else default,
                }
            desc["parameters"] = params
            descs.append(desc)
        return descs

    def format_for_prompt(self) -> str:
        """格式化为 LLM 可读的工具列表字符串。"""
        lines = ["## 可用工具\n"]
        for name, tool in self._tools.items():
            lines.append(f"### {name}")
            lines.append(f"{getattr(tool, 'description', '')}")
            kind = getattr(tool, "action_kind", ActionKind.COMPUTE)
            kind = kind.value if isinstance(kind, ActionKind) else str(kind)
            lines.append(f"行动类型：{kind}")
            if getattr(tool, "requires_authorization", False):
                lines.append("授权：需要授权（限定工作区的沙箱变更可由策略自动允许）")
            import inspect

            sig = inspect.signature(tool.run)
            sig_params = [p for p in sig.parameters if p not in ("self", "kwargs")]
            if sig_params:
                lines.append("参数：")
                for pname in sig_params:
                    param = sig.parameters[pname]
                    default = ""
                    if param.default is not inspect.Parameter.empty:
                        default = f" (默认={param.default})"
                    lines.append(f"  - {pname}{default}")
            lines.append("")
        return "\n".join(lines)


_SENSITIVE_PARTS = (
    "api_key",
    "apikey",
    "access_key",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
    "session_key",
    "token",
)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_PARTS)


def _redact_sequence(values: list) -> list:
    redacted = []
    redact_next = False
    for value in values:
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            continue
        if isinstance(value, str):
            option, separator, _ = value.partition("=")
            if _is_sensitive_key(option):
                if separator:
                    redacted.append(option + "=[REDACTED]")
                else:
                    redacted.append(value)
                    redact_next = True
                continue
        redacted.append(_redact_value(value))
    return redacted


def _redact_value(value: Any, key: object = "") -> Any:
    if key and _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact_value(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return _redact_sequence(list(value))
    if isinstance(value, set):
        return _redact_sequence(sorted(value, key=str))
    if isinstance(value, str) and len(value) > 12000:
        return value[:12000] + "...[truncated]"
    return value


def _redact_params(params: dict) -> dict:
    return {str(key): _redact_value(value, key) for key, value in params.items()}


def _result_summary(name: str, result: ToolResult) -> str:
    if result.status == ToolStatus.ERROR:
        return f"{name} 失败：{result.error[:180]}"
    classification = result.state_classification
    text = (result.content or "").replace("\n", " ").strip()[:180]
    return f"{name} 完成（{classification}）：{text}"
