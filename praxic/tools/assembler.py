"""
Praxic Agent —— 工具装配器（单一注册源）

cognitive_loop 与 practice 共用同一套工具装配逻辑，消除两处重复注册。

档 2（声明式）：新增核心工具时，在 TOOL_SPECS 加一行即可，不用改注册序列。
档 3（插件）：register_plugins() 从 data_dir/plugins 扫描 manifest 注册。

- register_workspace_tools(): 按 TOOL_SPECS 注册依赖 workspace 的工具
- register_plugins(): 扫描并注册用户/第三方插件
- 外部/独立工具（python_exec、shell_exec、read_user_context）由调用方按其
  上下文单独注册，避免装配器对它们的构造参数做假设。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog

from ..config import settings
from .registry import ToolRegistry

log = structlog.get_logger(__name__)


def register_workspace_tools(registry: ToolRegistry, workspace: Path) -> None:
    """按 TOOL_SPECS 注册全部依赖 workspace 的工具（档 2 声明式）。"""
    from .filesystem import (
        FileReadTool, FileWriteTool, FileEditTool,
        FileListTool, FileDeleteTool,
    )
    from .file_query import FileGrepTool, FileBatchReadTool, FileStatTool
    from .data_query import DataQueryTool
    from .sqlite_query import SqliteQueryTool
    from .pdf_extract import PdfExtractTool
    from .environment import (
        EnvTool, TimeTool, HttpRequestTool,
        ProcessListTool, DiskInfoTool, FileDownloadTool,
    )
    from .file_ops import FileCopyTool, FileMoveTool, FileTailTool
    from .archive import ArchiveExtractTool, ArchiveCreateTool

    # 声明式注册表：新增工具在此加一行 (工具类, 需要 workspace)。
    # 需要 workspace 的工具传 workspace 参数；不需要的（如 TimeTool）传空。
    TOOL_SPECS = [
        # ── 文件系统 ──
        (FileReadTool, True),
        (FileWriteTool, True),
        (FileEditTool, True),
        (FileListTool, True),
        (FileDeleteTool, True),
        # ── 查询 ──
        (FileGrepTool, True),
        (FileBatchReadTool, True),
        (FileStatTool, True),
        (DataQueryTool, True),
        (SqliteQueryTool, True),
        (PdfExtractTool, True),
        # ── 环境 / 网络 ──
        (EnvTool, True),
        (TimeTool, False),
        (HttpRequestTool, False),
        (ProcessListTool, False),
        (DiskInfoTool, True),
        (FileDownloadTool, True),
        # ── 文件操作 / 归档 ──
        (FileCopyTool, True),
        (FileMoveTool, True),
        (FileTailTool, True),
        (ArchiveExtractTool, True),
        (ArchiveCreateTool, True),
    ]
    for tool_cls, needs_workspace in TOOL_SPECS:
        registry.register(tool_cls(workspace) if needs_workspace else tool_cls())

    log.debug("tool_assembler.registered", count=len(registry.get_names()))


def register_plugins(registry: ToolRegistry, plugins_dir: str | Path | None = None) -> int:
    """扫描并注册插件（档 3），返回注册数量。plugins_dir 缺省为 data_dir/plugins。"""
    from .plugin import load_plugins
    directory = plugins_dir if plugins_dir is not None else settings.data_dir / "plugins"
    return load_plugins(registry, directory)
