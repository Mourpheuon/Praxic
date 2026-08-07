"""
Praxic Agent —— 文件系统工具
在 workspace_dir 范围内进行读写操作，不允许越出沙箱。
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Optional

import structlog

from .base import (
    ActionKind,
    BaseTool,
    ChangeRecord,
    ToolResult,
    ToolStatus,
    VerificationResult,
    VerificationStatus,
)
from ..config import settings
from .permissions import PathGuard

log = structlog.get_logger(__name__)

# 默认工作区：data_dir/workspace，也可在 config.toml [paths] 配置
DEFAULT_WORKSPACE = settings.data_dir / "workspace"


def _safe_path(workspace: Path, rel_path: str) -> Path:
    """
    将相对路径解析为绝对路径，确保不逃出 workspace。
    如果路径尝试逃出 workspace，抛出 PermissionError。
    """
    return PathGuard((workspace,)).resolve(rel_path)


def _digest(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FileReadTool(BaseTool):
    """读取 workspace 内的文件内容"""

    name = "file_read"
    category = "file"
    description = "读取工作区内指定文件的内容"
    requires_network = False
    action_kind = ActionKind.OBSERVE
    parameter_schema = {"path": {"type": "string"}, "encoding": {"type": "string", "default": "utf-8"}}

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(self, path: str, encoding: str = "utf-8") -> ToolResult:
        try:
            target = _safe_path(self.workspace, path)
            if not target.exists():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="",
                    error=f"文件不存在：{path}",
                )
            if not target.is_file():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="",
                    error=f"{path} 不是文件",
                )
            content = target.read_text(encoding=encoding, errors="replace")
            log.info("file_read", path=path, size=len(content))
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=content,
                source=str(target),
                metadata={"size": len(content), "path": str(target)},
            )
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"读取失败：{e}")


class FileWriteTool(BaseTool):
    """在 workspace 内写入/追加文件内容"""

    name = "file_write"
    category = "file"
    description = "在工作区内写入或追加文件内容"
    requires_network = False
    action_kind = ActionKind.CHANGE
    requires_authorization = True
    sandbox_safe = True
    parameter_schema = {
        "path": {"type": "string"},
        "content": {"type": "string"},
        "mode": {"type": "string", "default": "write"},
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        path: str,
        content: str,
        mode: str = "write",        # "write" | "append"
        encoding: str = "utf-8",
    ) -> ToolResult:
        try:
            target = _safe_path(self.workspace, path)
            before_exists = target.exists()
            before_digest = _digest(target)
            target.parent.mkdir(parents=True, exist_ok=True)

            if mode == "append":
                with open(target, "a", encoding=encoding) as f:
                    f.write(content)
                action = "追加"
            else:
                target.write_text(content, encoding=encoding)
                action = "写入"

            log.info("file_write", path=path, size=len(content), mode=mode)
            after_digest = _digest(target)
            changed = (not before_exists) or before_digest != after_digest
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"{action}成功：{path}（{len(content)} 字符）",
                source=str(target),
                metadata={"path": str(target), "size": len(content), "expected_change": True},
                action_kind=ActionKind.CHANGE,
                change=ChangeRecord(
                    target=str(target), operation=action, before_digest=before_digest,
                    after_digest=after_digest, changed=changed, reversible=True,
                    details={"mode": mode, "before_exists": before_exists},
                ),
            )
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"写入失败：{e}")

    async def verify(self, params: dict, result: ToolResult) -> VerificationResult:
        target = Path(result.source) if result.source else _safe_path(self.workspace, params.get("path", ""))
        expected = result.change.after_digest if result.change else ""
        observed = _digest(target)
        passed = bool(expected) and expected == observed and target.is_file()
        return VerificationResult(
            status=VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
            summary="写入后回读摘要匹配" if passed else "写入后回读摘要不匹配",
            expected=expected,
            observed=observed,
            checks={"exists": target.is_file(), "digest_matches": passed},
        )


class FileListTool(BaseTool):
    """列出 workspace 内目录的文件"""

    name = "file_list"
    category = "file"
    description = "列出工作区内指定目录下的文件和子目录"
    requires_network = False
    action_kind = ActionKind.OBSERVE

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        path: str = ".",
        recursive: bool = False,
        pattern: str = "*",
    ) -> ToolResult:
        try:
            target = _safe_path(self.workspace, path)
            if not target.is_dir():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="",
                    error=f"{path} 不是目录",
                )
            if recursive:
                entries = list(target.rglob(pattern))
            else:
                entries = list(target.glob(pattern))

            lines = []
            for e in sorted(entries):
                rel = e.relative_to(self.workspace)
                tag = "[DIR] " if e.is_dir() else "[FILE]"
                size = f" ({e.stat().st_size}B)" if e.is_file() else ""
                lines.append(f"{tag} {rel}{size}")

            content = "\n".join(lines) if lines else "（空目录）"
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=content,
                data={"entries": [str(e.relative_to(self.workspace)) for e in entries]},
                metadata={"count": len(entries)},
            )
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"列出失败：{e}")


class FileEditTool(BaseTool):
    """在工作区内精确编辑文件：old_text → new_text 替换，避免整文件重写。

    - old_text 必须在文件中唯一匹配，否则报错并提示加上下文。
    - 支持可选 count 限制替换次数（默认替换全部匹配需显式声明）。
    - 写回后回读摘要验证，保证变更可审计。
    """

    name = "file_edit"
    category = "file"
    description = "在工作区内精确替换文件内容（old_text→new_text），old_text 必须唯一匹配"
    requires_network = False
    action_kind = ActionKind.CHANGE
    requires_authorization = True
    sandbox_safe = True
    parameter_schema = {
        "path": {"type": "string"},
        "old_text": {"type": "string"},
        "new_text": {"type": "string", "default": ""},
        "count": {"type": "integer", "default": 0},  # 0=替换所有匹配
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        path: str,
        old_text: str,
        new_text: str = "",
        count: int = 0,
        encoding: str = "utf-8",
    ) -> ToolResult:
        try:
            target = _safe_path(self.workspace, path)
            if not target.exists():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"文件不存在：{path}")
            if not target.is_file():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"{path} 不是文件")
            before_digest = _digest(target)
            content = target.read_text(encoding=encoding, errors="replace")

            match_count = content.count(old_text)
            if match_count == 0:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="",
                    error=f"old_text 在文件中未找到：{old_text[:120]!r}",
                )
            if match_count > 1 and count == 0:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="",
                    error=(
                        f"old_text 匹配 {match_count} 处，不唯一。"
                        f"请补充上下文使 old_text 唯一，或显式指定 count={match_count} 替换全部。"
                    ),
                )
            if count > 0:
                if count > match_count:
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content="",
                        error=f"count={count} 超过实际匹配数 {match_count}",
                    )
                new_content = content.replace(old_text, new_text, count)
                replaced = count
            else:
                new_content = content.replace(old_text, new_text)
                replaced = match_count

            if new_content == content:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="",
                    error="替换后内容无变化（old_text 与 new_text 相同）",
                )
            target.write_text(new_content, encoding=encoding)
            log.info("file_edit", path=path, replaced=replaced)
            after_digest = _digest(target)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"替换成功：{path}（{replaced} 处）",
                source=str(target),
                metadata={
                    "path": str(target),
                    "replaced": replaced,
                    "expected_change": True,
                },
                action_kind=ActionKind.CHANGE,
                change=ChangeRecord(
                    target=str(target), operation="edit", before_digest=before_digest,
                    after_digest=after_digest, changed=True, reversible=True,
                    details={"replaced": replaced, "old_text": old_text[:200], "new_text": new_text[:200]},
                ),
            )
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"编辑失败：{e}")

    async def verify(self, params: dict, result: ToolResult) -> VerificationResult:
        target = Path(result.source) if result.source else _safe_path(self.workspace, params.get("path", ""))
        expected = result.change.after_digest if result.change else ""
        observed = _digest(target)
        passed = bool(expected) and expected == observed and target.is_file()
        return VerificationResult(
            status=VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
            summary="编辑后回读摘要匹配" if passed else "编辑后回读摘要不匹配",
            expected=expected,
            observed=observed,
            checks={"exists": target.is_file(), "digest_matches": passed},
        )


class FileDeleteTool(BaseTool):
    """删除 workspace 内的文件（READ_ONLY 权限模式下不可用）"""

    name = "file_delete"
    category = "file"
    description = "删除工作区内的文件（需要高权限）"
    requires_network = False
    action_kind = ActionKind.CHANGE
    requires_authorization = True
    sandbox_safe = True

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()

    async def run(self, path: str) -> ToolResult:
        from ..config import settings
        from ..tools.permissions import PermissionMode
        if settings.permission_mode == PermissionMode.READ_ONLY:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"只读权限模式下禁止删除操作，当前：{settings.permission_mode.name}",
            )
        try:
            target = _safe_path(self.workspace, path)
            if not target.exists():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"不存在：{path}")
            before_digest = _digest(target)
            before_kind = "directory" if target.is_dir() else "file"
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            log.info("file_delete", path=path)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"已删除：{path}",
                source=str(target),
                metadata={"path": str(target), "expected_change": True},
                action_kind=ActionKind.CHANGE,
                change=ChangeRecord(
                    target=str(target), operation="delete", before_digest=before_digest,
                    after_digest="", changed=True, reversible=False,
                    details={"kind": before_kind},
                ),
            )
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"删除失败：{e}")

    async def verify(self, params: dict, result: ToolResult) -> VerificationResult:
        target = Path(result.source) if result.source else _safe_path(self.workspace, params.get("path", ""))
        passed = not target.exists()
        return VerificationResult(
            status=VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
            summary="删除后回读确认目标不存在" if passed else "删除后仍能读取目标",
            expected={"exists": False},
            observed={"exists": target.exists()},
            checks={"missing": passed},
        )


class WorkspaceToolkit:
    """
    工作区工具套件 —— 统一入口
    初始化后可直接使用 read / write / list / delete 方法。
    workspace_dir 默认为 data/workspace，可通过构造函数传入自定义路径。
    """

    def __init__(self, workspace_dir: Optional[Path] = None):
        ws = Path(workspace_dir).resolve() if workspace_dir else DEFAULT_WORKSPACE
        ws.mkdir(parents=True, exist_ok=True)
        self.workspace = ws
        self.read   = FileReadTool(ws)
        self.write  = FileWriteTool(ws)
        self.list   = FileListTool(ws)
        self.delete = FileDeleteTool(ws)
        log.info("workspace.init", path=str(ws))

    def __repr__(self) -> str:
        return f"WorkspaceToolkit(workspace={self.workspace})"
