# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for 即物穷理.exe — 单文件打包"""

import sys
from pathlib import Path

# SPECPATH is injected by PyInstaller
_root = Path(SPECPATH)

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
web_index = _root / "siwu" / "web" / "index.html"
if web_index.exists():
    datas.append((str(web_index), "siwu/web"))

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
    # === siwu 内部模块 ===
    "siwu",
    "siwu.api",
    "siwu.api.routes",
    "siwu.api.routes.agent",
    "siwu.api.routes.setup",
    "siwu.api.routes.conversations",
    "siwu.api.schemas",
    "siwu.api.schemas.models",
    "siwu.core",
    "siwu.core.cognitive_loop",
    "siwu.core.investigation",
    "siwu.core.contradiction",
    "siwu.core.rational",
    "siwu.core.decision",
    "siwu.core.perspectives",
    "siwu.core.practice",
    "siwu.core.question_preprocessing",
    "siwu.core.reflection",
    "siwu.core.autonomy",
    "siwu.core.credibility_chain",
    "siwu.core.dev_tracer",
    "siwu.core.loop_controller",
    "siwu.llm",
    "siwu.llm.openai_compatible",
    "siwu.llm.claude",
    "siwu.llm.base",
    "siwu.memory",
    "siwu.memory.episodic_memory",
    "siwu.memory.working_memory",
    "siwu.memory.semantic_memory",
    "siwu.tools",
    "siwu.tools.filesystem",
    "siwu.tools.web_search",
    "siwu.ui",
    "siwu.config",
    "siwu.cli",

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
    [str(_root / "siwu" / "__main__.py")],
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
    name="即物穷理",
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
    icon=None,  # 图标 —— 可后续添加 .ico 文件: str(_root / "assets" / "praxic.ico")
)
