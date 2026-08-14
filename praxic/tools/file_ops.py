"""
Praxic Agent —— 文件操作补充工具

- file_copy   复制文件/目录（change，沙箱内）
- file_move   移动/重命名（change，沙箱内）
- file_tail   读文件尾部 N 行（observe，日志查看）

路径全部经 PathGuard 约束在 workspace 内。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import structlog

from ..config import settings
from .base import ActionKind, BaseTool, ChangeRecord, ToolResult, ToolStatus, VerificationResult, VerificationStatus
from .filesystem import _safe_path, _digest

log = structlog.get_logger(__name__)

DEFAULT_WORKSPACE = settings.data_dir / "workspace"


class FileCopyTool(BaseTool):
    """复制工作区内文件/目录"""

    name = "file_copy"
    category = "file"
    description = "复制工作区内文件或目录到新位置（source/dest 为相对工作区路径）"
    requires_network = False
    action_kind = ActionKind.CHANGE
    requires_authorization = True
    sandbox_safe = True
    parameter_schema = {
        "source": {"type": "string", "description": "源路径（相对工作区）"},
        "dest": {"type": "string", "description": "目标路径（相对工作区）"},
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(self, source: str, dest: str) -> ToolResult:
        try:
            src = _safe_path(self.workspace, source)
            dst = _safe_path(self.workspace, dest)
            if not src.exists():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"源不存在：{source}")
            if dst.exists():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"目标已存在：{dest}（如需覆盖请先删除）")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
                kind = "目录"
            else:
                shutil.copy2(src, dst)
                kind = "文件"
            log.info("file_copy", source=source, dest=dest)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"复制成功：{source} → {dest}",
                source=str(dst),
                metadata={"path": str(dst), "expected_change": True},
                action_kind=ActionKind.CHANGE,
                change=ChangeRecord(
                    target=str(dst), operation="copy", before_digest="",
                    after_digest=_digest(dst) if dst.is_file() else "",
                    changed=True, reversible=True, details={"kind": kind},
                ),
            )
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"复制失败：{e}")

    async def verify(self, params: dict, result: ToolResult) -> VerificationResult:
        dst = Path(result.source) if result.source else _safe_path(self.workspace, params.get("dest", ""))
        passed = dst.exists()
        return VerificationResult(
            status=VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
            summary="复制后目标存在" if passed else "复制后目标缺失",
            expected={"exists": True}, observed={"exists": dst.exists()},
            checks={"exists": passed},
        )


class FileMoveTool(BaseTool):
    """移动/重命名工作区内文件"""

    name = "file_move"
    category = "file"
    description = "移动或重命名工作区内文件/目录（source/dest 为相对工作区路径）"
    requires_network = False
    action_kind = ActionKind.CHANGE
    requires_authorization = True
    sandbox_safe = True
    parameter_schema = {
        "source": {"type": "string"},
        "dest": {"type": "string"},
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(self, source: str, dest: str) -> ToolResult:
        try:
            src = _safe_path(self.workspace, source)
            dst = _safe_path(self.workspace, dest)
            if not src.exists():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"源不存在：{source}")
            if dst.exists():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"目标已存在：{dest}")
            before_digest = _digest(src) if src.is_file() else ""
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            log.info("file_move", source=source, dest=dest)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"移动成功：{source} → {dest}",
                source=str(dst),
                metadata={"path": str(dst), "expected_change": True},
                action_kind=ActionKind.CHANGE,
                change=ChangeRecord(
                    target=str(dst), operation="move", before_digest=before_digest,
                    after_digest=_digest(dst) if dst.is_file() else "",
                    changed=True, reversible=True,
                ),
            )
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"移动失败：{e}")

    async def verify(self, params: dict, result: ToolResult) -> VerificationResult:
        dst = Path(result.source) if result.source else _safe_path(self.workspace, params.get("dest", ""))
        src = _safe_path(self.workspace, params.get("source", ""))
        passed = dst.exists() and not src.exists()
        return VerificationResult(
            status=VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
            summary="移动后目标存在且源消失" if passed else "移动结果异常",
            expected={"dest_exists": True, "source_missing": True},
            observed={"dest_exists": dst.exists(), "source_missing": not src.exists()},
            checks={"dest_exists": dst.exists(), "source_missing": not src.exists()},
        )


class FileTailTool(BaseTool):
    """读取文件尾部 N 行（日志查看）"""

    name = "file_tail"
    category = "file"
    group = "read"
    description = "读取文件最后 N 行（适合查看日志、长输出；path 为相对工作区路径）"
    requires_network = False
    action_kind = ActionKind.OBSERVE
    parameter_schema = {
        "path": {"type": "string"},
        "lines": {"type": "number", "default": 50},
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(self, path: str, lines: int = 50) -> ToolResult:
        try:
            target = _safe_path(self.workspace, path)
            if not target.exists() or not target.is_file():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"文件不存在：{path}")
            n = max(1, min(int(lines), 5000))
            # 从尾部读取，避免整文件加载
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                # 简化实现：读全部再取尾（文件通常不大）；大文件场景后续可优化
                all_lines = f.readlines()
            tail = all_lines[-n:]
            content = "".join(tail)
            if not content.endswith("\n"):
                content += "\n"
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=content,
                data={"lines": len(tail), "total_lines": len(all_lines)},
                metadata={"lines": len(tail), "total_lines": len(all_lines)},
            )
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"读取失败：{e}")
