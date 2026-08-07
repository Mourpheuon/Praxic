"""
Praxic Agent —— 文件查询工具（只读，observe 类）

与 file_read / file_list 互补的只读查询能力：
- file_grep：内容搜索（关键词/正则），跨文件定位
- file_batch_read：一次读多个文件（带截断）
- file_stat：文件元数据（大小/时间/类型/哈希）

三个工具全部为 ActionKind.OBSERVE，自动放行，不触碰授权模型。
路径全部经 PathGuard 约束在 workspace 内，不允许越出沙箱。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

import structlog

from .base import ActionKind, BaseTool, ToolResult, ToolStatus
from .permissions import PathGuard

log = structlog.get_logger(__name__)

# 默认工作区：data_dir/workspace，也可在 config.toml [paths] 配置
from ..config import settings

DEFAULT_WORKSPACE = settings.data_dir / "workspace"


class FileGrepTool(BaseTool):
    """在 workspace 内按内容搜索文件（关键词/正则）"""

    name = "file_grep"
    category = "file"
    group = "search"
    description = "在工作区内搜索包含指定文本或正则的文件，返回匹配的文件与行号"
    requires_network = False
    action_kind = ActionKind.OBSERVE
    parameter_schema = {
        "pattern": {"type": "string", "description": "搜索文本或正则表达式"},
        "path": {"type": "string", "default": ".", "description": "起始目录（默认工作区根）"},
        "glob": {"type": "string", "default": "*", "description": "文件匹配模式，如 *.py"},
        "recursive": {"type": "boolean", "default": True},
        "ignore_case": {"type": "boolean", "default": False},
        "max_matches": {"type": "number", "default": 100},
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        pattern: str,
        path: str = ".",
        glob: str = "*",
        recursive: bool = True,
        ignore_case: bool = False,
        max_matches: int = 100,
    ) -> ToolResult:
        try:
            flags = re.IGNORECASE if ignore_case else 0
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"正则表达式错误：{e}")

        try:
            target = PathGuard((self.workspace,)).resolve(path)
            if not target.is_dir():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"{path} 不是目录")
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))

        matches: list[str] = []
        count = 0
        files_scanned = 0
        truncated = False
        iterator = target.rglob(glob) if recursive else target.glob(glob)
        try:
            for entry in iterator:
                if count >= max_matches:
                    truncated = True
                    break
                if not entry.is_file():
                    continue
                try:
                    rel = str(entry.relative_to(self.workspace)).replace("\\", "/")
                    with entry.open("r", encoding="utf-8", errors="replace") as f:
                        for line_no, line in enumerate(f, 1):
                            if count >= max_matches:
                                truncated = True
                                break
                            if regex.search(line):
                                matches.append(f"{rel}:{line_no}: {line.rstrip()[:160]}")
                                count += 1
                    files_scanned += 1
                except (PermissionError, OSError):
                    continue
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR, content="",
                error=f"搜索失败：{e}",
            )

        content = "\n".join(matches) if matches else f"（无匹配，扫描 {files_scanned} 个文件）"
        if truncated:
            content += f"\n（结果超过 {max_matches} 条，已截断）"
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=content,
            data={
                "matches": matches,
                "match_count": count,
                "files_scanned": files_scanned,
                "truncated": truncated,
            },
            metadata={"match_count": count, "files_scanned": files_scanned},
        )


class FileBatchReadTool(BaseTool):
    """一次读取多个文件（带每文件截断），用于批量审计与对比"""

    name = "file_batch_read"
    category = "file"
    group = "read"
    description = "一次读取工作区内多个文件的内容，每文件按行数截断"
    requires_network = False
    action_kind = ActionKind.OBSERVE
    parameter_schema = {
        "paths": {"type": "array", "description": "要读取的文件路径列表"},
        "max_lines_per_file": {"type": "number", "default": 200},
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        paths: list,
        max_lines_per_file: int = 200,
    ) -> ToolResult:
        if not paths:
            return ToolResult(status=ToolStatus.ERROR, content="", error="paths 不能为空")

        sections: list[str] = []
        per_file: dict[str, dict] = {}
        for raw_path in paths:
            p = str(raw_path)
            try:
                target = PathGuard((self.workspace,)).resolve(p)
                if not target.is_file():
                    sections.append(f"### {p}\n（不存在或不是文件）")
                    per_file[p] = {"exists": False}
                    continue
                lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
                truncated = len(lines) > max_lines_per_file
                body = lines[:max_lines_per_file]
                block = "\n".join(body) if body else "（空文件）"
                if truncated:
                    block += f"\n...[共 {len(lines)} 行，仅显示前 {max_lines_per_file} 行]"
                sections.append(f"### {p}\n{block}")
                per_file[p] = {"exists": True, "lines": len(lines), "truncated": truncated}
            except Exception as e:
                sections.append(f"### {p}\n（读取失败：{e}）")
                per_file[p] = {"exists": False, "error": str(e)}

        return ToolResult(
            status=ToolStatus.SUCCESS,
            content="\n\n".join(sections),
            data={"files": per_file},
            metadata={"file_count": len(paths)},
        )


class FileStatTool(BaseTool):
    """读取文件/目录元数据（大小、修改时间、类型、摘要）"""

    name = "file_stat"
    category = "file"
    group = "read"
    description = "查看工作区内文件或目录的元数据：大小、修改时间、类型、SHA256 摘要"
    requires_network = False
    action_kind = ActionKind.OBSERVE
    parameter_schema = {"path": {"type": "string"}}

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(self, path: str) -> ToolResult:
        try:
            target = PathGuard((self.workspace,)).resolve(path)
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))

        if not target.exists():
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"不存在：{path}")

        import time as _time
        stat = target.stat()
        info = {
            "path": str(target),
            "kind": "directory" if target.is_dir() else "file",
            "size_bytes": stat.st_size,
            "mtime": _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(stat.st_mtime)),
            "sha256": self._digest(target) if target.is_file() else "",
        }
        lines = [
            f"路径：{path}",
            f"类型：{info['kind']}",
            f"大小：{info['size_bytes']} bytes",
            f"修改时间：{info['mtime']}",
        ]
        if info["sha256"]:
            lines.append(f"SHA256：{info['sha256'][:16]}...")
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content="\n".join(lines),
            data=info,
            metadata={"path": str(target)},
        )

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
