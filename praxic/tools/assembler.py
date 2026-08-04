"""
Praxic Agent —— 工具装配器（单一注册源）

cognitive_loop 与 practice 共用同一套工具装配逻辑，消除两处重复注册：
- register_workspace_tools(): 注册所有依赖 workspace 的工具
- 外部/独立工具（python_exec、shell_exec、read_user_context）由调用方按其
  上下文单独注册，避免装配器对它们的构造参数做假设。

新增工具时只改这里的 register_workspace_tools()，两个调用方自动生效。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog

from ..config import settings
from .registry import ToolRegistry

log = structlog.get_logger(__name__)


def register_workspace_tools(registry: ToolRegistry, workspace: Path) -> None:
    """把全部依赖 workspace 的工具注册进 registry（单一来源）。"""
    from .filesystem import (
        FileReadTool, FileWriteTool, FileEditTool,
        FileListTool, FileDeleteTool,
    )
    from .file_query import FileGrepTool, FileBatchReadTool, FileStatTool
    from .data_query import DataQueryTool
    from .environment import (
        EnvTool, TimeTool, HttpRequestTool,
        ProcessListTool, DiskInfoTool, FileDownloadTool,
    )
    from .file_ops import FileCopyTool, FileMoveTool, FileTailTool
    from .archive import ArchiveExtractTool, ArchiveCreateTool

    # ── 文件系统 ──
    registry.register(FileReadTool(workspace))
    registry.register(FileWriteTool(workspace))
    registry.register(FileEditTool(workspace))
    registry.register(FileListTool(workspace))
    registry.register(FileDeleteTool(workspace))
    # ── 查询 ──
    registry.register(FileGrepTool(workspace))
    registry.register(FileBatchReadTool(workspace))
    registry.register(FileStatTool(workspace))
    registry.register(DataQueryTool(workspace))
    # ── 环境 / 网络 ──
    registry.register(EnvTool(workspace))
    registry.register(TimeTool())
    registry.register(HttpRequestTool())
    registry.register(ProcessListTool())
    registry.register(DiskInfoTool(workspace))
    registry.register(FileDownloadTool(workspace))
    # ── 文件操作 / 归档 ──
    registry.register(FileCopyTool(workspace))
    registry.register(FileMoveTool(workspace))
    registry.register(FileTailTool(workspace))
    registry.register(ArchiveExtractTool(workspace))
    registry.register(ArchiveCreateTool(workspace))

    log.debug("tool_assembler.registered", count=len(registry.get_names()))
