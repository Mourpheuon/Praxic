"""
即物穷理 Praxic —— FastAPI 主服务入口
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import mimetypes
import os

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from ..config import settings, CONFIG_TOML
from .routes.agent import init_agent_resources, router as agent_router
from .routes.setup import router as setup_router
from .routes.conversations import router as conversations_router

UI_DIR = Path(__file__).parent.parent / "ui"
WEB_DIR = Path(__file__).parent.parent / "web"

log = structlog.get_logger(__name__)

_TEXT_FILE_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".css", ".csv", ".go", ".h", ".hpp", ".html",
    ".ini", ".java", ".js", ".json", ".jsx", ".md", ".py", ".rs", ".sh",
    ".sql", ".svg", ".tex", ".toml", ".ts", ".tsx", ".txt", ".vue", ".xml", ".yaml",
    ".yml",
}
_MAX_EDITOR_BYTES = 2 * 1024 * 1024
_MAX_TREE_ENTRIES = 500


class WorkspaceFileUpdateRequest(BaseModel):
    path: str
    content: str
    project_id: str = ""


def _resolve_project_workspace(project_id: str = "") -> Path:
    """Resolve a project workspace without allowing project-id traversal."""
    if not project_id:
        return settings.workspace_dir.resolve()

    projects_root = settings.projects_dir.resolve()
    project_dir = (projects_root / project_id).resolve()
    try:
        project_dir.relative_to(projects_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="项目路径越界") from exc
    if not project_dir.is_dir():
        raise HTTPException(status_code=404, detail="项目不存在")

    local_path_file = project_dir / ".localpath"
    if local_path_file.is_file():
        return Path(local_path_file.read_text(encoding="utf-8").strip()).resolve()
    return (project_dir / "workspace").resolve()


def _resolve_workspace_file(workspace: Path, file_path: str) -> Path:
    raw = Path(file_path)
    safe = (raw if raw.is_absolute() else workspace / raw).resolve()
    try:
        safe.relative_to(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="路径越界") from exc
    return safe


def _is_text_workspace_file(path: Path, mime: str | None) -> bool:
    return path.suffix.lower() in _TEXT_FILE_EXTENSIONS or bool(mime and mime.startswith("text/"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化资源"""
    log.info("praxic_api.starting", debug=settings.debug)
    has_key = bool(settings.llm_api_key or settings.anthropic_api_key or settings.deepseek_api_key)
    if has_key:
        try:
            init_agent_resources()
        except Exception:
            log.warning("agent_init_failed_on_startup", exc_info=True)
    else:
        log.info("praxic_api.no_api_key", msg="Setup screen will prompt for API key")
    yield
    log.info("praxic_api.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="即物穷理 API",
        description=(
            "以辩证唯物主义方法论为认知内核的 AI 智能体。"
            "认知循环：调查研究 → 矛盾分析 → 理性认识 → 实践检验 → 反思复盘"
        ),
        version="0.1.5",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS（开发环境全开，生产请限制 origins）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(agent_router)
    app.include_router(setup_router)
    app.include_router(conversations_router)

    # ── 调试：路径信息（判断当前连的是哪个后端实例）────────────────
    @app.get("/api/v1/debug/info", include_in_schema=False)
    async def debug_info():
        import platform, sys
        return {
            "cwd": str(Path.cwd().resolve()),
            "config_toml": str(CONFIG_TOML.resolve()),
            "data_dir": str(settings.data_dir.resolve()),
            "workspace_dir": str(settings.workspace_dir.resolve()),
            "projects_dir": str(settings.projects_dir.resolve()),
            "python": sys.executable,
            "platform": platform.platform(),
            "pid": os.getpid(),
        }

    # ── 工作空间文件服务 ──
    # 智能体在实践中生成的文件（图表、报告、数据等）通过此端点提供给 UI
    @app.get("/api/v1/workspace/files/{file_path:path}", include_in_schema=False)
    async def serve_workspace_file(file_path: str):
        workspace = settings.workspace_dir.resolve()
        safe = _resolve_workspace_file(workspace, file_path)
        if not safe.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        mime, _ = mimetypes.guess_type(str(safe))
        return FileResponse(safe, media_type=mime or "application/octet-stream")

    @app.get("/api/v1/workspace/file-content", include_in_schema=False)
    async def read_workspace_file(path: str, project_id: str = ""):
        """Read a project workspace text file for the right-hand inspector."""
        workspace = _resolve_project_workspace(project_id)
        safe = _resolve_workspace_file(workspace, path)
        if not safe.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        if safe.stat().st_size > _MAX_EDITOR_BYTES:
            raise HTTPException(status_code=413, detail="文件过大，阅读器最多打开 2 MB")

        mime, _ = mimetypes.guess_type(str(safe))
        editable = _is_text_workspace_file(safe, mime)
        if editable:
            content = safe.read_text(encoding="utf-8", errors="replace")
        else:
            content = ""
        return {
            "path": str(safe),
            "relative_path": str(safe.relative_to(workspace)),
            "content": content,
            "editable": editable,
            "mime": mime or "application/octet-stream",
            "size_bytes": safe.stat().st_size,
        }

    @app.get("/api/v1/workspace/tree", include_in_schema=False)
    async def list_workspace_tree(path: str = "", project_id: str = ""):
        """List one directory in a project workspace for the in-app file browser."""
        workspace = _resolve_project_workspace(project_id)
        safe = _resolve_workspace_file(workspace, path)
        if not safe.exists():
            raise HTTPException(status_code=404, detail="目录不存在")
        if not safe.is_dir():
            raise HTTPException(status_code=400, detail="目标不是目录")

        try:
            children = sorted(
                safe.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.casefold()),
            )
        except OSError as exc:
            raise HTTPException(status_code=403, detail="目录不可读取") from exc

        entries = []
        for child in children[:_MAX_TREE_ENTRIES]:
            try:
                resolved = child.resolve()
                resolved.relative_to(workspace)
                relative = str(child.relative_to(workspace))
                is_dir = child.is_dir()
                stat = child.stat()
                mime, _ = mimetypes.guess_type(str(child))
            except (OSError, ValueError):
                continue
            entries.append({
                "name": child.name,
                "relative_path": relative,
                "kind": "directory" if is_dir else "file",
                "size_bytes": 0 if is_dir else stat.st_size,
                "mime": mime or ("inode/directory" if is_dir else "application/octet-stream"),
                "editable": False if is_dir else _is_text_workspace_file(child, mime),
            })

        return {
            "workspace_name": workspace.name or "workspace",
            "current_path": "" if safe == workspace else str(safe.relative_to(workspace)),
            "entries": entries,
            "truncated": len(children) > _MAX_TREE_ENTRIES,
        }

    @app.put("/api/v1/workspace/file-content", include_in_schema=False)
    async def update_workspace_file(req: WorkspaceFileUpdateRequest):
        """Save an explicitly edited text file inside the active project workspace."""
        if len(req.content.encode("utf-8")) > _MAX_EDITOR_BYTES:
            raise HTTPException(status_code=413, detail="文件过大，最多保存 2 MB")

        workspace = _resolve_project_workspace(req.project_id)
        safe = _resolve_workspace_file(workspace, req.path)
        if not safe.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        mime, _ = mimetypes.guess_type(str(safe))
        if not _is_text_workspace_file(safe, mime):
            raise HTTPException(status_code=415, detail="该文件不是可编辑的文本文件")

        safe.write_text(req.content, encoding="utf-8")
        return {
            "ok": True,
            "path": str(safe),
            "relative_path": str(safe.relative_to(workspace)),
            "size_bytes": safe.stat().st_size,
        }

    # Serve React SPA (self-contained, CDN-based, no build required)
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def root():
        react_file = WEB_DIR / "index.html"
        if react_file.exists():
            return HTMLResponse(content=react_file.read_text(encoding="utf-8"))
        # Fallback to old static HTML
        html_file = UI_DIR / "index.html"
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))

    return app


app = create_app()


def run_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False, open_browser: bool = False):
    import webbrowser, threading
    url = f"http://localhost:{port}"
    print(f"\n  即物穷理已启动 -> {url}")
    print(f"  按 Ctrl+C 停止服务\n")
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        "praxic.api.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )
