"""
Praxic Agent —— 归档解压工具（change 类，沙箱内）

支持 zip / tar / tar.gz / tar.bz2 解压到 workspace 内指定目录。
- 路径全部经 PathGuard 约束在 workspace 内。
- 解压前校验：拒绝路径穿越（zip slip），拒绝超长路径。
- action_kind=CHANGE + sandbox_safe，由权限模式决定放行方式。
"""

from __future__ import annotations

import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Optional

import structlog

from ..config import settings
from .base import ActionKind, BaseTool, ChangeRecord, ToolResult, ToolStatus, VerificationResult, VerificationStatus
from .filesystem import _safe_path, _digest

log = structlog.get_logger(__name__)

DEFAULT_WORKSPACE = settings.data_dir / "workspace"


class ArchiveExtractTool(BaseTool):
    """解压 zip/tar 归档到工作区内"""

    name = "archive_extract"
    category = "file"
    group = "archive"
    description = "解压 zip/tar/tar.gz 归档到工作区指定目录（防路径穿越；path/target_dir 为相对工作区路径）"
    requires_network = False
    action_kind = ActionKind.CHANGE
    requires_authorization = True
    sandbox_safe = True
    parameter_schema = {
        "path": {"type": "string", "description": "归档文件路径（相对工作区）"},
        "target_dir": {"type": "string", "default": ".", "description": "解压目标目录（相对工作区）"},
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(self, path: str, target_dir: str = ".") -> ToolResult:
        try:
            archive = _safe_path(self.workspace, path)
            if not archive.exists() or not archive.is_file():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"归档不存在：{path}")
            target = _safe_path(self.workspace, target_dir)
            target.mkdir(parents=True, exist_ok=True)

            suffix = archive.suffix.lower()
            names: list[str] = []
            if suffix == ".zip" or archive.name.lower().endswith(".zip"):
                names = self._extract_zip(archive, target)
            elif suffix in (".tar", ".gz", ".bz2", ".xz") or tarfile.is_tarfile(str(archive)):
                names = self._extract_tar(archive, target)
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="",
                    error=f"不支持的归档格式：{suffix}（支持 zip / tar / tar.gz / tar.bz2）",
                )

            log.info("archive_extract", path=path, count=len(names))
            # 产物清单返回相对工作区的完整路径（含 target_dir 前缀），供产物台账引用。
            base_prefix = str(target.relative_to(self.workspace)).replace("\\", "/")
            full_names = [
                (base_prefix + "/" + n) if base_prefix not in ("", ".") else n
                for n in names
            ]
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"解压成功：{path} → {target_dir}（{len(names)} 个文件/目录）",
                source=str(archive),
                data={"extracted": full_names[:200], "count": len(names)},
                metadata={"path": str(archive), "target": str(target), "expected_change": True},
                action_kind=ActionKind.CHANGE,
                change=ChangeRecord(
                    target=str(target), operation="extract",
                    before_digest="", after_digest=_digest(target) if target.is_file() else "",
                    changed=True, reversible=False,
                    details={"archive": str(archive), "count": len(names)},
                ),
            )
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"解压失败：{e}")

    def _extract_zip(self, archive: Path, target: Path) -> list[str]:
        names: list[str] = []
        with zipfile.ZipFile(str(archive)) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            # 若所有条目共享同一公共顶层目录（如 data/xxx），剥离它，
            # 避免 target_dir + 条目自带目录叠成两层。
            prefix = self._common_top_dir([i.filename for i in infos])
            for info in infos:
                filename = info.filename
                rel = filename[len(prefix):] if prefix and filename.startswith(prefix) else filename
                member = Path(rel)
                dest = (target / member).resolve()
                # zip slip 防护：解压目标必须在 target 内
                if not str(dest).startswith(str(target.resolve())):
                    raise PermissionError(f"归档包含越界路径：{info.filename}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                names.append(rel)
        return names

    @staticmethod
    def _common_top_dir(filenames: list[str]) -> str:
        """返回所有条目共享的顶层目录（带尾部斜杠）；无共享则空串。

        公共前缀必须被所有条目共享：任何条目（含无目录条目）不满足该前缀
        即视为无公共目录。任何含 .. 的越界条目直接视为无公共目录。
        """
        tops = set()
        for name in filenames:
            norm = name.replace("\\", "/")
            if norm.startswith("../") or norm == ".." or "/../" in norm or norm.endswith("/.."):
                return ""
            if "/" in norm:
                tops.add(norm.split("/", 1)[0] + "/")
            else:
                tops.add("")  # 无目录条目：参与共享判断，作为"无公共目录"信号
        if len(tops) == 1:
            candidate = next(iter(tops))
            if candidate:
                # 双重确认：所有条目确实以该前缀开头
                for name in filenames:
                    norm = name.replace("\\", "/")
                    if not norm.startswith(candidate):
                        return ""
                return candidate
        return ""

    def _extract_tar(self, archive: Path, target: Path) -> list[str]:
        names: list[str] = []
        with tarfile.open(str(archive)) as tf:
            for member in tf.getmembers():
                dest = (target / member.name).resolve()
                if not str(dest).startswith(str(target.resolve())):
                    raise PermissionError(f"归档包含越界路径：{member.name}")
            tf.extractall(str(target))
            names = tf.getnames()
        return names


class ArchiveCreateTool(BaseTool):
    """把工作区内文件/目录压缩为 zip 归档"""

    name = "archive_create"
    category = "file"
    group = "archive"
    description = "把工作区内文件/目录压缩为 zip 归档（paths/archive_path 为相对工作区路径）"
    requires_network = False
    action_kind = ActionKind.CHANGE
    requires_authorization = True
    sandbox_safe = True
    parameter_schema = {
        "paths": {"type": "array", "description": "要压缩的文件/目录列表（相对工作区）"},
        "archive_path": {"type": "string", "description": "输出 zip 路径（相对工作区）"},
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(self, paths: list, archive_path: str) -> ToolResult:
        try:
            if not paths:
                return ToolResult(status=ToolStatus.ERROR, content="", error="paths 不能为空")
            out = _safe_path(self.workspace, archive_path)
            if out.suffix.lower() != ".zip":
                return ToolResult(status=ToolStatus.ERROR, content="", error="输出必须是 .zip 路径")
            if out.exists():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"目标已存在：{archive_path}")
            out.parent.mkdir(parents=True, exist_ok=True)
            added: list[str] = []
            with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
                for raw in paths:
                    p = _safe_path(self.workspace, str(raw))
                    if not p.exists():
                        raise FileNotFoundError(f"源不存在：{raw}")
                    base = p.relative_to(self.workspace)
                    if p.is_dir():
                        for f in p.rglob("*"):
                            if f.is_file():
                                rel = f.relative_to(self.workspace)
                                zf.write(str(f), str(rel))
                                added.append(str(rel))
                    else:
                        zf.write(str(p), str(base))
                        added.append(str(base))
            log.info("archive_create", archive=archive_path, count=len(added))
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"压缩成功：{archive_path}（{len(added)} 个文件）",
                source=str(out),
                data={"added": added[:200], "count": len(added)},
                metadata={"path": str(out), "expected_change": True},
                action_kind=ActionKind.CHANGE,
                change=ChangeRecord(
                    target=str(out), operation="create_archive", before_digest="",
                    after_digest=_digest(out), changed=True, reversible=True,
                    details={"count": len(added)},
                ),
            )
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"压缩失败：{e}")

    async def verify(self, params: dict, result: ToolResult) -> VerificationResult:
        out = Path(result.source) if result.source else _safe_path(self.workspace, params.get("archive_path", ""))
        passed = out.exists() and out.stat().st_size > 0
        return VerificationResult(
            status=VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
            summary="压缩包已生成" if passed else "压缩包缺失或为空",
            expected={"exists": True, "nonempty": True},
            observed={"exists": out.exists(), "size": out.stat().st_size if out.exists() else 0},
            checks={"exists": out.exists(), "nonempty": out.stat().st_size > 0 if out.exists() else False},
        )
