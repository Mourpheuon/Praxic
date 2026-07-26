"""
思悟 Agent —— 对话 & 项目管理路由
GET    /api/v1/conversations                 列出所有对话
GET    /api/v1/conversations/{conversation_id}  获取对话历史
POST   /api/v1/conversations                 创建新对话
PATCH  /api/v1/conversations/{conversation_id}  重命名对话
DELETE /api/v1/conversations/{conversation_id}  删除对话
GET    /api/v1/projects                      列出项目
"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...config import settings
from ...memory.episodic_memory import EpisodicMemory

router = APIRouter(prefix="/api/v1", tags=["conversations"])

_episodic: Optional[EpisodicMemory] = None


def _get_episodic() -> EpisodicMemory:
    """延迟初始化 EpisodicMemory，避免模块导入时触发数据库初始化。"""
    global _episodic
    if _episodic is None:
        _episodic = EpisodicMemory()
    return _episodic


# ── Models ───────────────────────────────────────────────────

class TurnItem(BaseModel):
    session_id: str
    question: str
    summary: str = ""
    action_items: list[str] = []
    created_at: str = ""


class ConversationSummary(BaseModel):
    id: str
    name: str = ""
    question_count: int = 0
    last_question: str = ""
    last_active: str = ""


class ConversationDetail(BaseModel):
    conversation_id: str
    name: str = ""
    turns: list[TurnItem] = []


class CreateConversationRequest(BaseModel):
    name: str = ""
    project_id: str = ""


class RenameRequest(BaseModel):
    name: str


class ProjectSummary(BaseModel):
    id: str = ""
    workspace_dir: str = ""
    data_dir: str = ""
    name: str = "默认项目"
    conversation_count: int = 0
    last_active: str = ""
    local_path: str = ""    # 关联的本地路径（新建项目为空）


class CreateProjectRequest(BaseModel):
    name: str
    folder_path: str = ""   # 非空时关联现有目录，为空时新建


# ── Routes ───────────────────────────────────────────────────

@router.get("/conversations")
async def list_conversations(project_id: Optional[str] = None):
    """列出对话（按最近活动排序）。project_id 省略=全部；''=默认项目；'x'=指定项目。"""
    episodic = _get_episodic()
    rows = episodic.list_conversations(project_id=project_id)
    conversations = []
    for row in rows:
        cid = row.get("conversation_id", "")
        if not cid:
            continue
        name = episodic.get_conversation_name(cid)
        conversations.append(ConversationSummary(
            id=cid,
            name=name,
            question_count=row.get("question_count", 0),
            last_question=row.get("last_question", "") or "",
            last_active=row.get("last_active", ""),
        ))
    return {"conversations": conversations}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """获取单个对话的全部历史轮次。"""
    episodic = _get_episodic()
    turns_data = episodic.get_conversation_turns(conversation_id)
    name = episodic.get_conversation_name(conversation_id) or conversation_id[:8]

    turns = [
        TurnItem(
            session_id=t.get("session_id", ""),
            question=t.get("question", ""),
            summary=t.get("summary", ""),
            action_items=t.get("action_items", []),
            created_at=t.get("created_at", ""),
        )
        for t in turns_data
    ]
    return ConversationDetail(conversation_id=conversation_id, name=name, turns=turns)


@router.post("/conversations")
async def create_conversation(req: CreateConversationRequest):
    """创建新对话（返回 conversation_id）。"""
    conversation_id = str(uuid.uuid4())[:8]
    name = req.name.strip() if req.name else "新对话"
    episodic = _get_episodic()
    episodic.set_conversation_name(conversation_id, name)
    # 立即把新对话归到当前项目（project_id="" 即默认项目），使侧栏按项目筛选时立刻可见
    episodic.set_conversation_project(conversation_id, req.project_id or "")
    return {
        "conversation_id": conversation_id,
        "name": name,
        "project_id": req.project_id or "",
        "created_at": datetime.now().isoformat(),
    }


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(conversation_id: str, req: RenameRequest):
    """重命名对话。"""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="名称不能为空")
    _get_episodic().set_conversation_name(conversation_id, req.name.strip())
    return {"ok": True, "conversation_id": conversation_id, "name": req.name.strip()}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """删除对话及其全部历史记录。"""
    ok = _get_episodic().delete_conversation(conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="对话不存在或已删除")
    return {"ok": True, "conversation_id": conversation_id}


@router.get("/projects")
async def list_projects():
    """列出所有项目（默认项目 + 用户创建项目），含对话数与最近活动。"""
    episodic = _get_episodic()
    db_projects = {p.get("project_id", ""): p for p in episodic.list_projects()}
    projects = []
    seen = set()

    # 默认项目（project_id=''）
    default_info = db_projects.get("", {})
    projects.append(ProjectSummary(
        id="",
        workspace_dir=str(settings.workspace_dir.resolve()),
        data_dir=str(settings.data_dir.resolve()),
        name="默认项目",
        conversation_count=default_info.get("conversation_count", 0),
        last_active=default_info.get("last_active", "") or "",
    ))
    seen.add("")

    # 用户创建的项目：扫描 projects_dir，合并 DB 统计
    if settings.projects_dir.exists():
        for d in sorted(settings.projects_dir.iterdir()):
            if not d.is_dir():
                continue
            pid = d.name
            seen.add(pid)
            info = db_projects.get(pid, {})
            name_file = d / ".name"
            disp = name_file.read_text(encoding="utf-8").strip() if name_file.exists() else pid
            local_path_file = d / ".localpath"
            local_path = local_path_file.read_text(encoding="utf-8").strip() if local_path_file.exists() else ""
            workspace = Path(local_path) if local_path else d / "workspace"
            projects.append(ProjectSummary(
                id=pid,
                workspace_dir=str(workspace.resolve()),
                data_dir=str(settings.data_dir.resolve()),
                name=disp,
                conversation_count=info.get("conversation_count", 0),
                last_active=info.get("last_active", "") or "",
                local_path=local_path,
            ))

    # DB 有归属但目录尚未建立的项目
    for pid, info in db_projects.items():
        if pid in seen:
            continue
        projects.append(ProjectSummary(
            id=pid,
            workspace_dir=str((settings.projects_dir / pid / "workspace").resolve()),
            data_dir=str(settings.data_dir.resolve()),
            name=pid,
            conversation_count=info.get("conversation_count", 0),
            last_active=info.get("last_active", "") or "",
            local_path="",
        ))

    return {"projects": projects}


@router.post("/projects")
async def create_project(req: CreateProjectRequest):
    """创建新项目：支持新建 workspace 或关联现有本地文件夹。返回 project_id。"""
    import re
    pid = re.sub(r"[^\w\-]", "_", req.name.strip().lower())
    if not pid:
        raise HTTPException(status_code=400, detail="项目名称无效")
    project_dir = settings.projects_dir / pid
    if project_dir.exists():
        raise HTTPException(status_code=409, detail=f"项目 '{pid}' 已存在")

    if req.folder_path.strip():
        # 模式2：关联现有文件夹
        local = Path(req.folder_path.strip()).resolve()
        if not local.is_dir():
            raise HTTPException(status_code=400, detail=f"目录不存在：{local}")
        project_dir.mkdir(parents=True)
        (project_dir / ".name").write_text(req.name.strip(), encoding="utf-8")
        (project_dir / ".localpath").write_text(str(local), encoding="utf-8")
        workspace = local
    else:
        # 模式1：新建 workspace 子目录
        (project_dir / "workspace").mkdir(parents=True)
        (project_dir / ".name").write_text(req.name.strip(), encoding="utf-8")
        workspace = project_dir / "workspace"

    return {"project_id": pid, "name": req.name.strip(), "workspace_dir": str(workspace)}
