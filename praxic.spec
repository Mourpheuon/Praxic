# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for praxic-backend — 平台感知单文件打包"""

import sys
from pathlib import Path

# SPECPATH is injected by PyInstaller
_root = Path(SPECPATH)

# ── 平台感知 ──────────────────────────────────────────────────
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform.startswith("darwin")

# 后端可执行文件名：Windows 带 .exe，macOS/Linux 无扩展名
BACKEND_NAME = "praxic-backend.exe" if IS_WIN else "praxic-backend"

# 图标：Windows 用 ico，macOS 用 icns（由 CI 的 iconutil 从 iconset 生成），Linux 用 png
if IS_WIN:
    _icon = str(_root / "assets" / "icon.ico") if (_root / "assets" / "icon.ico").exists() else None
elif IS_MAC:
    _icon = str(_root / "assets" / "icon.icns") if (_root / "assets" / "icon.icns").exists() else None
else:
    _icon = None  # Linux EXE 不支持图标，由 electron-builder 设置

# 收集 tiktoken 数据文件（Rust 扩展模型文件）
try:
    from PyInstaller.utils.hooks import collect_data_files
    tiktoken_datas = collect_data_files('tiktoken')
    tiktoken_ext_datas = collect_data_files('tiktoken_ext')
except Exception:
    tiktoken_datas = []
    tiktoken_ext_datas = []

# ── 收集数据文件 ──────────────────────────────────────────────
datas = []

# web 前端 (index.html)
web_index = _root / "praxic" / "web" / "index.html"
if web_index.exists():
    datas.append((str(web_index), "praxic/web"))

# prompts 目录（如果存在）
prompts_dir = _root / "prompts"
if prompts_dir.is_dir():
    for md_file in prompts_dir.glob("*.md"):
        datas.append((str(md_file), "prompts"))

# 默认 config.toml.example（包内兜底配置，首次运行复制到工作目录并提示用户填写 key）
config_example = _root / "config.toml.example"
if config_example.exists():
    datas.append((str(config_example), "."))

# 合并 tiktoken 数据
datas.extend(tiktoken_datas)
datas.extend(tiktoken_ext_datas)

# 隐藏导入 —— 确保动态加载的模块被打包
hiddenimports = [
    # === praxic 内部模块 ===
    "praxic",
    "praxic.api",
    "praxic.api.routes",
    "praxic.api.routes.agent",
    "praxic.api.routes.setup",
    "praxic.api.routes.conversations",
    "praxic.api.schemas",
    "praxic.api.schemas.models",
    "praxic.core",
    "praxic.core.cognitive_loop",
    "praxic.core.investigation",
    "praxic.core.contradiction",
    "praxic.core.rational",
    "praxic.core.practice",
    "praxic.core.question_preprocessing",
    "praxic.core.reflection",
    "praxic.core.autonomy",
    "praxic.core.credibility_chain",
    "praxic.core.dev_tracer",
    "praxic.core.loop_controller",
    "praxic.llm",
    "praxic.llm.openai_compatible",
    "praxic.llm.claude",
    "praxic.llm.base",
    "praxic.memory",
    "praxic.memory.episodic_memory",
    "praxic.memory.working_memory",
    "praxic.memory.semantic_memory",
    "praxic.tools",
    "praxic.tools.filesystem",
    "praxic.tools.web_search",
    "praxic.ui",
    "praxic.config",
    "praxic.cli",

    # === uvicorn / asyncio ===
    "uvicorn",
    "uvicorn.config",
    "uvicorn.server",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.logging",
    "asyncio",
    "concurrent.futures",
    "concurrent.futures.thread",

    # === FastAPI / Starlette ===
    "fastapi",
    "fastapi.middleware",
    "fastapi.middleware.cors",
    "starlette",
    "starlette.responses",

    # === Pydantic ===
    "pydantic",
    "pydantic.deprecated",
    "pydantic.deprecated.decorator",

    # === HTTP / AI ===
    "httpx",
    "httpx._transports",
    "httpx._transports.default",
    "openai",
    "tiktoken",
    "tiktoken_ext",
    "tiktoken_ext.openai_public",

    # === 其他三方 ===
    "structlog",
    "dotenv",
    "tomllib",
    "tomli",
    "anyio",
    "anyio._backends",
    "anyio._backends._asyncio",
    "anyio._core",
    "anyio._core._eventloop",
    "rich",
    "rich.console",
    "typer",

    # === 可选依赖（import 失败时会跳过）===
    "aiosqlite",
    "sqlalchemy",
    "chromadb",
    "networkx",
    "flet",
]

a = Analysis(
    [str(_root / "praxic" / "__main__.py")],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(_root / "runtime_hook.py")],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=BACKEND_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)
