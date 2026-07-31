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

from ..config import settings, CONFIG_TOML
from .routes.agent import init_agent_resources, router as agent_router
from .routes.setup import router as setup_router
from .routes.conversations import router as conversations_router

UI_DIR = Path(__file__).parent.parent / "ui"
WEB_DIR = Path(__file__).parent.parent / "web"

log = structlog.get_logger(__name__)


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
        version="0.0.3",
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
        safe = (workspace / file_path).resolve()
        try:
            safe.relative_to(workspace)
        except ValueError:
            raise HTTPException(status_code=403, detail="路径越界")
        if not safe.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        mime, _ = mimetypes.guess_type(str(safe))
        return FileResponse(safe, media_type=mime or "application/octet-stream")

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
