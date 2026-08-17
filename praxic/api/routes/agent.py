"""
Praxic Agent —— API 路由（pub/sub 可重连 SSE 架构）

架构：
  GET /run/stream?question=...&conversation_id=...
    - conv_id 未运行 + 有 question → 启动新认知循环并订阅
    - conv_id 正在运行             → 回放已发出事件，续接后续（断线重连）
    - conv_id 已完成               → 回放全部事件（含最终结果）

  GET /run/status/{conv_id}        → 查询流状态
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional, Dict, Any

import structlog
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...core.cognitive_loop import CognitiveLoop
from ...core.loop_controller import get_controller_by_conv
from ...cordis.services.session import SessionScope

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

_scope: Optional[SessionScope] = None
_episodic: Optional[Any] = None
_semantic: Optional[Any] = None


def init_agent_resources() -> None:
    global _scope, _episodic, _semantic
    # host 层（root context）：episodic/semantic memory、skills、settings 进程级单例
    _scope = SessionScope()
    _episodic = _scope.root.get("memory").episodic
    _semantic = _scope.root.get("memory").semantic


def _ensure_scope() -> SessionScope:
    global _scope
    if _scope is None:
        init_agent_resources()
    return _scope


def get_loop(project_id: str = "", conversation_id: str = "") -> CognitiveLoop:
    """返回会话 realm 内的认知循环实例。

    realm label = conversation_id 非空时用它，否则 project_id，否则全局默认
    realm；同 label 幂等复用。会话结束/替换时由 dispose 统一销毁。
    """
    scope = _ensure_scope()
    realm = scope.get_or_create(conversation_id or project_id, project_id=project_id)
    return realm.ctx.get("cognitive-loop").loop


async def adispose_session(conversation_id: str = "", project_id: str = "") -> bool:
    """销毁会话 realm：cancel 后台任务并 await，再逆序清理其余资源（幂等）。"""
    if _scope is None:
        return False
    return await _scope.dispose(conversation_id or project_id or "")


def _find_registry(request_id: str, project_id: str = "", conversation_id: str = ""):
    """Find a pending authorization without exposing the loop internals to UI callers."""
    if _scope is None:
        return None
    candidates = []
    if conversation_id or project_id:
        for realm in _scope.live_realms():
            if realm.label in (conversation_id, project_id):
                candidates.append(realm)
    if not candidates:
        candidates = list(_scope.live_realms())
    seen = set()
    for realm in candidates:
        marker = id(realm.ctx)
        if marker in seen:
            continue
        seen.add(marker)
        try:
            registry = realm.ctx.get("tool-registry").registry
        except Exception:  # noqa: BLE001 - 会话可能未完整装配
            continue
        if registry and registry.authorization_status(request_id) is not None:
            return registry
    return None


def get_episodic():
    if _episodic is None:
        init_agent_resources()
    return _episodic


# ── Pub/Sub Registry ────────────────────────────────────────────────────────
# conv_id -> {
#   "replay":       list of raw event dicts (全量回放缓冲)
#   "subscribers":  list of asyncio.Queue  (当前活跃订阅者)
#   "done":         bool
#   "created_at":   float
#   "completed_at": float (仅 done=True 时)
# }
_registry: Dict[str, Dict[str, Any]] = {}
_REPLAY_TTL = 600  # 完成后保留回放缓冲 10 分钟


def _cleanup_old_entries() -> None:
    now = time.time()
    expired = [
        cid for cid, e in _registry.items()
        if e["done"] and (now - e.get("completed_at", now)) > _REPLAY_TTL
    ]
    for cid in expired:
        log.info("stream_registry.cleanup", conv_id=cid)
        del _registry[cid]


def _broadcast(conv_id: str, event: dict) -> None:
    entry = _registry.get(conv_id)
    if entry is None:
        return
    entry["replay"].append(event)
    for q in list(entry["subscribers"]):
        try:
            q.put_nowait(event)
        except Exception:
            pass


def _create_subscriber(conv_id: str):
    """
    返回 (queue, already_done)。
    立即把回放缓冲里的历史事件填入 queue；
    如果流尚未结束，把 queue 注册到订阅者列表。
    """
    entry = _registry.get(conv_id)
    q: asyncio.Queue = asyncio.Queue()
    if entry is None:
        return q, True
    for event in entry["replay"]:
        q.put_nowait(event)
    if entry["done"]:
        return q, True
    entry["subscribers"].append(q)
    return q, False


def _finish_stream(conv_id: str) -> None:
    entry = _registry.get(conv_id)
    if entry is None:
        return
    entry["done"] = True
    entry["completed_at"] = time.time()
    # 通知所有等待中的订阅者流已结束
    for q in list(entry["subscribers"]):
        try:
            q.put_nowait({"type": "__eof__"})
        except Exception:
            pass
    entry["subscribers"].clear()


async def _run_and_broadcast(
    conv_id: str, question: str, context: str, mode: str, review_strategy: str,
    model: str = "", files: str = "", project_id: str = "", replace_session_id: str = "",
    resume_from: str = "", resume_events=None,
) -> None:
    """后台任务：运行认知循环，将事件广播给所有订阅者。"""
    loop_inst = get_loop(project_id, conv_id)
    if replace_session_id:
        loop_inst.episodic.truncate_conversation_from(conv_id, replace_session_id)
    file_list = [f.strip() for f in files.split(",") if f.strip()] if files else None
    try:
        async for event in loop_inst.stream_run(
            question, context, mode,
            conversation_id=conv_id,
            review_strategy=review_strategy,
            model_override=model,
            files=file_list, project_id=project_id,
            resume_from=resume_from, resume_events=resume_events,
        ):
            _broadcast(conv_id, event)
            if event["type"] == "result":
                break
    except asyncio.CancelledError:
        # 会话 dispose（stop/替换/超时）取消本任务：广播终态后重新抛出
        log.info("stream_broadcast.cancelled", conv_id=conv_id)
        _broadcast(conv_id, {"type": "result", "data": None, "error": "已终止"})
        raise
    except Exception as exc:
        log.error("stream_broadcast.error", conv_id=conv_id, error=str(exc), exc_info=True)
        _broadcast(conv_id, {"type": "result", "data": None, "error": str(exc)})
    finally:
        _finish_stream(conv_id)
        # 会话结束：销毁 realm（cancel 后台任务 + 逆序清理；幂等）
        if _scope is not None:
            await _scope.dispose(conv_id or project_id or "")


def _serialize_event(event: dict) -> Optional[str]:
    """把内部事件 dict 转成 SSE 数据行。返回 None 表示跳过。"""
    t = event.get("type")
    if t in ("phase", "activity"):
        payload: dict = {"phase": event["phase"], "summary": event["summary"]}
        payload["type"] = t
        if event.get("event_type"):
            payload["event_type"] = event["event_type"]
        phase_data = event.get("data")
        if phase_data is not None:
            payload["data"] = (
                phase_data.model_dump(mode="json")
                if hasattr(phase_data, "model_dump")
                else phase_data
            )
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    elif t == "clarification":
        return f"data: {json.dumps({'type': 'clarification', 'questions': event.get('questions', [])}, ensure_ascii=False)}\n\n"
    elif t == "title":
        return f"data: {json.dumps({'title': event['title'], 'conversation_id': event.get('conversation_id', ''), 'type': 'title'}, ensure_ascii=False)}\n\n"
    elif t == "result":
        result = event.get("data")
        error_msg = event.get("error", "")
        payload = {
            "done": True,
            "summary": result.summary if result else "",
            "action_items": result.action_items if result else [],
            "session_id": result.session_id if result else "",
            "conversation_id": result.conversation_id if result else "",
            "generated_files": [
                {"path": f.path, "description": f.description, "size_bytes": f.size_bytes}
                for f in (result.generated_files or [])
            ] if result else [],
            "error": error_msg,
        }
        if result and result.full_trace and result.full_trace.metadata:
            metadata = result.full_trace.metadata
            payload["metadata"] = (
                metadata.model_dump(mode="json")
                if hasattr(metadata, "model_dump")
                else metadata
            )
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    return None  # 跳过 __eof__ 等内部事件


# ── 路由 ──────────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    question: str
    context: str = ""
    mode: str = "standard"
    conversation_id: str = ""
    review_strategy: str = "once"
    model: str = ""
    files: list[str] = []
    project_id: str = ""


class RunResponse(BaseModel):
    session_id: str
    conversation_id: str = ""
    summary: str
    action_items: list[str]
    principal_contradiction: str = ""
    convergence_score: float = 1.0
    iterations: int = 1
    phase_durations: dict[str, float] = {}


@router.post("/run", response_model=RunResponse)
async def run_agent(req: RunRequest):
    """同步运行认知循环。"""
    loop_inst = get_loop(req.project_id, req.conversation_id)
    response = await loop_inst.run(
        question=req.question, context=req.context,
        mode=req.mode, conversation_id=req.conversation_id,
        review_strategy=req.review_strategy,
        files=req.files or None, project_id=req.project_id,
    )
    pc = ""
    if response.full_trace and response.full_trace.contradictions:
        c = response.full_trace.contradictions.principal_contradiction
        if c:
            pc = c.description[:200]
    return RunResponse(
        session_id=response.session_id,
        conversation_id=response.conversation_id or req.conversation_id,
        summary=response.summary,
        action_items=response.action_items,
        principal_contradiction=pc,
        convergence_score=(
            response.full_trace.reflection.convergence_score
            if response.full_trace and response.full_trace.reflection else 1.0
        ),
        iterations=(
            response.full_trace.metadata.iterations if response.full_trace else 1
        ),
        phase_durations=(
            response.full_trace.metadata.phase_durations if response.full_trace else {}
        ),
    )


@router.get("/run/status/{conv_id}")
async def stream_status(conv_id: str):
    """查询对话流状态（用于断线重连前的探测）。"""
    entry = _registry.get(conv_id)
    if entry is None:
        return {"status": "not_found", "events": 0}
    return {
        "status": "done" if entry["done"] else "running",
        "events": len(entry["replay"]),
    }


@router.get("/run/stream")
async def stream_agent(
    question: str = "",
    context: str = "",
    mode: str = "standard",
    conversation_id: str = "",
    review_strategy: str = "once",
    dev_trace: int = 0,
    model: str = "",
    files: str = "",
    project_id: str = "",
    replace_session_id: str = "",
    resume_from: str = "",
):
    """
    SSE 流式端点（支持断线重连 + 断点续跑）。

    行为：
      - conv_id 未在运行 + 有 question → 启动新认知循环并订阅
      - conv_id 正在运行              → 回放已发出事件，续接后续实时事件
      - conv_id 已完成                → 回放全量历史事件（含最终结果）
      - 已完成 + 带新 question        → 新一轮；若带 resume_from，复用中断前的产物从断点继续（不完整重跑）
    """
    conv_id = conversation_id
    _cleanup_old_entries()

    existing = _registry.get(conv_id) if conv_id else None
    resume_events = None

    # 同 conv_id 的上一轮已完成且带来新 question → 视为新一轮
    # 带 resume_from 时，把上一轮 replay 交给续跑重建（内存断点优先），
    # 然后重置缓冲开新一轮；否则完整重跑（现状）。
    if existing is not None and existing.get("done") and question:
        if resume_from:
            # 保留上一个已中断/终止轮次的 replay 供续跑重建
            resume_events = list(existing.get("replay") or [])
        del _registry[conv_id]
        existing = None

    if existing is None:
        # ── 启动新运行 ────────────────────────────────────────────
        if not question:
            raise HTTPException(status_code=400, detail="question 是必填项（启动新运行）")
        if conv_id:
            _registry[conv_id] = {
                "replay": [], "subscribers": [], "done": False,
                "created_at": time.time(),
            }
        # create_task 仅调度任务，不立即执行（asyncio 单线程）
        # 订阅者在下面 _create_subscriber 中注册后，任务才会在第一次 await 时运行
        if conv_id:
            task = asyncio.create_task(
                _run_and_broadcast(conv_id, question, context, mode, review_strategy,
                                   model, files, project_id, replace_session_id,
                                   resume_from, resume_events)
            )
            # 后台任务挂进会话 realm 的 fiber：stop/超时/替换统一走 dispose → cancel + await
            realm = _ensure_scope().get_or_create(conv_id or project_id, project_id=project_id)
            realm.fiber.track_task(task)
        else:
            # 无 conv_id：退化为旧式单次流（向后兼容）
            async def _compat_gen():
                loop_inst = get_loop(project_id)
                file_list = [f.strip() for f in files.split(",") if f.strip()] if files else None
                async for event in loop_inst.stream_run(
                    question, context, mode,
                    conversation_id="", review_strategy=review_strategy,
                    model_override=model,
                    files=file_list, project_id=project_id,
                    resume_from=resume_from,
                ):
                    line = _serialize_event(event)
                    if line:
                        yield line
                    if event["type"] == "result":
                        break
            return StreamingResponse(
                _compat_gen(), media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    # ── 创建订阅者（回放 + 后续事件）─────────────────────────────
    sub_queue, already_done = _create_subscriber(conv_id)
    log.info("stream_agent.subscriber_created",
             conv_id=conv_id, replayed=len(existing["replay"] if existing else []),
             already_done=already_done)

    async def event_generator():
        while True:
            if already_done:
                # 直接消费回放缓冲，不等待
                try:
                    event = sub_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            else:
                try:
                    # 30 秒心跳，防止代理/浏览器超时断连
                    event = await asyncio.wait_for(sub_queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield "data: {\"heartbeat\": true}\n\n"
                    continue
            if event.get("type") == "__eof__":
                break
            line = _serialize_event(event)
            if line:
                yield line
            if event.get("type") == "result":
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ControlRequest(BaseModel):
    conversation_id: str
    action: str = "steer"          # steer | interrupt | stop | resume
    content: str = ""              # steering message (for steer/resume)
    target_phase: str = ""         # optional phase target for steer


class AuthorizationResolutionRequest(BaseModel):
    action: str = "approve"        # approve | deny
    project_id: str = ""
    ttl_seconds: float = Field(default=900.0, gt=0, le=86400.0)


@router.get("/authorizations")
async def list_authorizations(project_id: str = ""):
    """List pending side-effect approvals for the active project."""
    loop_inst = get_loop(project_id)
    registry = getattr(loop_inst, "_registry", None)
    return {
        "requests": [request.to_dict() for request in registry.pending_authorizations]
        if registry else []
    }


@router.post("/authorizations/{request_id}")
async def resolve_authorization(request_id: str, req: AuthorizationResolutionRequest):
    """Approve or reject a paused tool action; approval resumes its original await."""
    registry = _find_registry(request_id, req.project_id)
    if registry is None:
        raise HTTPException(status_code=404, detail="授权请求不存在或已结束")
    action = req.action.lower().strip()
    if action == "approve":
        result = registry.approve_authorization(request_id, ttl_seconds=req.ttl_seconds)
    elif action == "deny":
        result = registry.deny_authorization(request_id)
    else:
        raise HTTPException(status_code=400, detail="action 必须是 approve 或 deny")
    if result is None:
        raise HTTPException(status_code=409, detail="授权请求已经被处理")
    return {"status": "ok", "authorization": result}


@router.post("/control")
async def control_agent(req: ControlRequest):
    """
    运行时控制端点：引导(steer)、打断(interrupt)、终止(stop)、继续(resume)。

    通过 conversation_id 查找正在运行的认知循环控制器并执行对应操作。
    """
    controller = get_controller_by_conv(req.conversation_id)
    if controller is None:
        raise HTTPException(
            status_code=404,
            detail=f"conversation {req.conversation_id} 没有正在运行的认知循环"
        )

    action = req.action.lower()
    if action == "steer":
        controller.steer(req.content, target_phase=req.target_phase)
        if req.content.strip():
            get_episodic().append_conversation_event(
                conversation_id=req.conversation_id,
                session_id=controller.session_id,
                phase=controller.current_phase or req.target_phase or "practice",
                summary="用户插话：" + req.content.strip(),
                event_type="steering",
                data={
                    "event_type": "steering",
                    "content": req.content.strip(),
                    "target_phase": req.target_phase or "",
                },
            )
        log.info("control.steer", conv_id=req.conversation_id, content=req.content[:80])
        return {"status": "ok", "action": "steer", "conversation_id": req.conversation_id}
    elif action == "interrupt":
        controller.interrupt()
        get_episodic().append_conversation_event(
            conversation_id=req.conversation_id,
            session_id=controller.session_id,
            phase=controller.current_phase or "practice",
            summary="用户请求打断当前认知循环",
            event_type="interrupt",
            data={"event_type": "interrupt", "action": "interrupt"},
        )
        log.info("control.interrupt", conv_id=req.conversation_id)
        return {"status": "ok", "action": "interrupt", "conversation_id": req.conversation_id}
    elif action == "stop":
        controller.stop()
        get_episodic().append_conversation_event(
            conversation_id=req.conversation_id,
            session_id=controller.session_id,
            phase=controller.current_phase or "practice",
            summary="用户终止了认知循环",
            event_type="stop",
            data={"event_type": "stop", "action": "stop"},
        )
        # 终止会话：dispose → cancel 后台任务并 await，再逆序清理（幂等）
        await adispose_session(req.conversation_id)
        log.info("control.stop", conv_id=req.conversation_id)
        return {"status": "ok", "action": "stop", "conversation_id": req.conversation_id}
    elif action == "resume":
        controller.resume(steer=req.content or None)
        if req.content.strip():
            get_episodic().append_conversation_event(
                conversation_id=req.conversation_id,
                session_id=controller.session_id,
                phase=controller.current_phase or "practice",
                summary="恢复运行时附带插话：" + req.content.strip(),
                event_type="steering",
                data={
                    "event_type": "steering",
                    "content": req.content.strip(),
                    "action": "resume",
                },
            )
        log.info("control.resume", conv_id=req.conversation_id)
        return {"status": "ok", "action": "resume", "conversation_id": req.conversation_id}
    elif action == "answer":
        controller.submit_clarification(req.content)
        get_episodic().append_conversation_event(
            conversation_id=req.conversation_id,
            session_id=controller.session_id,
            phase=controller.current_phase or "preprocessing",
            summary="用户回答了澄清问题",
            event_type="user_question",
            data={
                "event_type": "user_question",
                "content": req.content or "",
                "action": "answer",
            },
        )
        log.info("control.answer", conv_id=req.conversation_id)
        return {"status": "ok", "action": "answer", "conversation_id": req.conversation_id}
    else:
        raise HTTPException(status_code=400, detail=f"不支持的操作: {action}")


@router.get("/traces")
async def list_traces(limit: int = 10):
    """查询历史认知轨迹摘要。"""
    episodic = get_episodic()
    episodes = episodic.get_recent(limit)
    return {"traces": [
        {
            "session_id": ep.get("session_id", ""),
            "question": ep.get("question", "")[:100],
            "summary": ep.get("summary", "")[:200],
            "created_at": ep.get("created_at", ""),
        }
        for ep in episodes
    ]}


@router.post("/upload-file")
async def upload_file(file: UploadFile = File(...), project_id: str = Form("")):
    """接收文件上传，保存到项目 workspace/uploads/，返回可供 /run 使用的绝对路径。"""
    from pathlib import Path
    from ...config import settings
    if project_id:
        upload_dir = settings.projects_dir / project_id / "workspace" / "uploads"
    else:
        upload_dir = settings.workspace_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    # 只取文件名，防止路径穿越
    safe_name = Path(file.filename or "upload.bin").name
    dest = upload_dir / safe_name
    content = await file.read()
    dest.write_bytes(content)
    return {
        "ok": True,
        "file_path": str(dest.resolve()),
        "file_name": safe_name,
        "size": len(content),
    }
