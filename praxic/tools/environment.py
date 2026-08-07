"""
Praxic Agent —— 环境与网络工具

- env_tool      环境信息查询（observe，全档自动）
- time_tool     当前时间（observe，全档自动）
- http_request  HTTP 请求（external，按权限模式分级：READ_ONLY 拒 / ASK 询问 /
                AUTO_REVIEW 语义审核 / FULL 放行）

http_request 是外部网络动作，requires_network=True；权限分级由
PermissionPolicy 按四档统一处理。
"""

from __future__ import annotations

import asyncio
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import structlog

from ..config import settings
from .base import (
    ActionKind, BaseTool, ChangeRecord, ToolResult, ToolStatus,
    VerificationResult, VerificationStatus,
)
from .filesystem import _safe_path, _digest

log = structlog.get_logger(__name__)

DEFAULT_WORKSPACE = settings.data_dir / "workspace"

# http_request 白名单：允许的协议与端口
_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {80, 443, 8080, 8000, 3000, 5000}
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2MB
_DEFAULT_TIMEOUT = 30.0

# env_tool 允许暴露的环境变量白名单（敏感变量不暴露）
_ENV_WHITELIST = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "TEMP",
    "TMP",
    "PWD",
    "OS",
    "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS",
    "PRAXIC_",
)


class EnvTool(BaseTool):
    """查询系统环境信息（工作区路径、平台、Python 版本、环境变量白名单）"""

    name = "env_tool"
    category = "system"
    description = "查看当前环境：平台、Python 版本、工作区路径、环境变量（白名单）"
    requires_network = False
    action_kind = ActionKind.OBSERVE
    parameter_schema = {"key": {"type": "string", "default": "", "description": "环境变量名（空=返回摘要）"}}

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()

    async def run(self, key: str = "") -> ToolResult:
        try:
            if key:
                # 单键查询：只允许白名单前缀
                if not any(key.startswith(p) for p in _ENV_WHITELIST):
                    return ToolResult(
                        status=ToolStatus.ERROR,
                        content="",
                        error=f"环境变量 {key} 不在允许暴露的白名单内",
                    )
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    content=f"{key}={os.environ.get(key, '（未设置）')}",
                    data={"key": key, "value": os.environ.get(key, "")},
                )
            info = {
                "platform": platform.system(),
                "platform_release": platform.release(),
                "python_version": sys.version.split()[0],
                "workspace": str(self.workspace),
                "cwd": str(Path.cwd()),
                "env_keys": sorted(
                    k for k in os.environ if any(k.startswith(p) for p in _ENV_WHITELIST)
                ),
            }
            lines = [
                f"平台：{info['platform']} {info['platform_release']}",
                f"Python：{info['python_version']}",
                f"工作区：{info['workspace']}",
                f"当前目录：{info['cwd']}",
                f"环境变量（白名单）：{', '.join(info['env_keys']) if info['env_keys'] else '（无）'}",
            ]
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content="\n".join(lines),
                data=info,
            )
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"环境查询失败：{e}")


class TimeTool(BaseTool):
    """查询当前时间与时区"""

    name = "time_tool"
    category = "system"
    description = "查看当前 UTC 时间、本地时间和时区偏移"
    requires_network = False
    action_kind = ActionKind.OBSERVE

    async def run(self) -> ToolResult:
        now = datetime.now()
        now_utc = datetime.now(timezone.utc)
        offset = now.astimezone().utcoffset() or timezone.utc.utcoffset(None) or __import__("datetime").timedelta(0)
        info = {
            "local": now.strftime("%Y-%m-%d %H:%M:%S"),
            "utc": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "tz_offset_hours": offset.total_seconds() / 3600,
            "epoch": int(time.time()),
        }
        lines = [
            f"本地时间：{info['local']}",
            f"UTC 时间：{info['utc']}",
            f"时区偏移：{info['tz_offset_hours']:+.1f}h",
            f"Epoch：{info['epoch']}",
        ]
        return ToolResult(status=ToolStatus.SUCCESS, content="\n".join(lines), data=info)


class HttpRequestTool(BaseTool):
    """HTTP 请求（external 类，按权限模式分级）。"""

    name = "http_request"
    category = "network"
    description = "发起 HTTP GET/POST 请求到外部 URL，返回状态码与正文（外部网络动作）"
    requires_network = True
    action_kind = ActionKind.EXTERNAL
    requires_authorization = True
    sandbox_safe = False
    parameter_schema = {
        "url": {"type": "string", "description": "完整 URL（仅 http/https）"},
        "method": {"type": "string", "default": "GET", "description": "GET | POST"},
        "headers": {"type": "object", "default": {}, "description": "请求头（敏感头会被过滤）"},
        "body": {"type": "string", "default": "", "description": "POST 请求体"},
        "timeout_seconds": {"type": "number", "default": 30},
    }

    def __init__(self):
        self._session = None

    def _validate_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValueError(f"仅允许 http/https，收到：{parsed.scheme}")
        if parsed.port and parsed.port not in _ALLOWED_PORTS:
            raise ValueError(f"端口 {parsed.port} 不在允许清单内")
        if not parsed.hostname:
            raise ValueError("URL 缺少主机名")
        # 禁止指向本机管理端口（防 SSRF 内网探测常见目标）
        host = parsed.hostname.lower()
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            raise ValueError("禁止请求本机地址（SSRF 防护）")
        return url

    async def run(
        self,
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        body: str = "",
        timeout_seconds: float = 30.0,
    ) -> ToolResult:
        try:
            url = self._validate_url(url)
            timeout_seconds = min(float(timeout_seconds), 60.0)
            import httpx
            # 过滤敏感请求头
            safe_headers = {
                str(k): str(v) for k, v in (headers or {}).items()
                if not any(s in str(k).lower() for s in ("authorization", "api-key", "token", "secret", "cookie", "x-api-key"))
            }
            method = method.upper()
            if method not in ("GET", "POST"):
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"仅支持 GET/POST，收到 {method}")

            async with httpx.AsyncClient(
                timeout=timeout_seconds,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=4),
            ) as client:
                if method == "GET":
                    resp = await client.get(url, headers=safe_headers)
                else:
                    resp = await client.post(url, headers=safe_headers, content=body.encode("utf-8") if body else None)

            content = resp.content
            if len(content) > _MAX_RESPONSE_BYTES:
                content = content[:_MAX_RESPONSE_BYTES]
                truncated = True
            else:
                truncated = False
            text = content.decode("utf-8", errors="replace")
            ctype = resp.headers.get("content-type", "")
            if truncated:
                text += "\n...[响应超 2MB 已截断]"
            return ToolResult(
                status=ToolStatus.SUCCESS if resp.status_code < 400 else ToolStatus.ERROR,
                content=text[:8000],
                data={
                    "status_code": resp.status_code,
                    "content_type": ctype,
                    "url": url,
                    "bytes": len(content),
                    "truncated": truncated,
                },
                error="" if resp.status_code < 400 else f"HTTP {resp.status_code}",
            )
        except ValueError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"HTTP 请求失败：{e}")


class ProcessListTool(BaseTool):
    """列出当前进程（只读诊断，observe）"""

    name = "process_list"
    category = "system"
    description = "查看当前运行的进程（PID、名称、内存），只读诊断"
    requires_network = False
    action_kind = ActionKind.OBSERVE
    parameter_schema = {
        "name": {"type": "string", "default": "", "description": "按进程名过滤"},
        "limit": {"type": "number", "default": 30},
    }

    async def run(self, name: str = "", limit: int = 30) -> ToolResult:
        try:
            import psutil
        except ImportError:
            return ToolResult(status=ToolStatus.ERROR, content="", error="psutil 未安装，无法列进程")
        try:
            procs = []
            for p in psutil.process_iter(["pid", "name", "memory_info"]):
                try:
                    pname = p.info["name"] or ""
                    if name and name.lower() not in pname.lower():
                        continue
                    mem = (p.info["memory_info"] or {}).rss if p.info.get("memory_info") else 0
                    procs.append({"pid": p.info["pid"], "name": pname, "rss_mb": round(mem / 1024 / 1024, 1)})
                except Exception:
                    continue
            procs = sorted(procs, key=lambda x: x["rss_mb"], reverse=True)[:max(1, min(int(limit), 100))]
            lines = [f"{p['pid']:>7}  {p['rss_mb']:>9.1f}MB  {p['name']}" for p in procs]
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content="\n".join(lines) if lines else "（无匹配进程）",
                data={"processes": procs, "count": len(procs)},
                metadata={"count": len(procs)},
            )
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"进程查询失败：{e}")


class DiskInfoTool(BaseTool):
    """查询磁盘空间（observe）"""

    name = "disk_info"
    category = "system"
    description = "查看磁盘使用情况：总量、已用、剩余"
    requires_network = False
    action_kind = ActionKind.OBSERVE
    parameter_schema = {"path": {"type": "string", "default": ".", "description": "要查询的目录（相对工作区）"}}

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run(self, path: str = ".") -> ToolResult:
        try:
            target = Path(path) if Path(path).is_absolute() else (self.workspace / path)
            import shutil as _shutil
            usage = _shutil.disk_usage(str(target))
            gb = 1024 ** 3
            info = {
                "total_gb": round(usage.total / gb, 1),
                "used_gb": round(usage.used / gb, 1),
                "free_gb": round(usage.free / gb, 1),
                "used_pct": round(usage.used / usage.total * 100, 1) if usage.total else 0,
            }
            lines = [
                f"总量：{info['total_gb']} GB",
                f"已用：{info['used_gb']} GB（{info['used_pct']}%）",
                f"剩余：{info['free_gb']} GB",
            ]
            return ToolResult(status=ToolStatus.SUCCESS, content="\n".join(lines), data=info)
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"磁盘查询失败：{e}")


class FileDownloadTool(BaseTool):
    """从 URL 下载文件到工作区（external 类，按权限分级）"""

    name = "file_download"
    category = "network"
    description = "从 URL 下载文件到工作区指定路径（外部网络动作）"
    requires_network = True
    action_kind = ActionKind.EXTERNAL
    requires_authorization = True
    sandbox_safe = False
    parameter_schema = {
        "url": {"type": "string", "description": "文件 URL（仅 http/https）"},
        "dest": {"type": "string", "description": "保存路径（相对工作区）"},
        "timeout_seconds": {"type": "number", "default": 60},
    }

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = (workspace or DEFAULT_WORKSPACE).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _validate_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValueError(f"仅允许 http/https，收到：{parsed.scheme}")
        if parsed.port and parsed.port not in _ALLOWED_PORTS:
            raise ValueError(f"端口 {parsed.port} 不在允许清单内")
        host = parsed.hostname.lower() if parsed.hostname else ""
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            raise ValueError("禁止请求本机地址（SSRF 防护）")
        return url

    async def run(self, url: str, dest: str, timeout_seconds: float = 60.0) -> ToolResult:
        try:
            url = self._validate_url(url)
            target = _safe_path(self.workspace, dest)
            if target.exists():
                return ToolResult(status=ToolStatus.ERROR, content="", error=f"目标已存在：{dest}")
            timeout_seconds = min(float(timeout_seconds), 120.0)
            import httpx
            async with httpx.AsyncClient(
                timeout=timeout_seconds, follow_redirects=True,
                limits=httpx.Limits(max_connections=4),
            ) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    size = 0
                    with open(target, "wb") as f:
                        async for chunk in resp.aiter_bytes():
                            f.write(chunk)
                            size += len(chunk)
            log.info("file_download", url=url, dest=dest, size=size)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content=f"下载成功：{url} → {dest}（{size} bytes）",
                source=str(target),
                data={"url": url, "path": str(target), "size": size},
                metadata={"path": str(target), "expected_change": True},
                action_kind=ActionKind.EXTERNAL,
                change=ChangeRecord(
                    target=str(target), operation="download", before_digest="",
                    after_digest=_digest(target), changed=True, reversible=False,
                    details={"url": url, "size": size},
                ),
            )
        except ValueError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except PermissionError as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=str(e))
        except Exception as e:
            return ToolResult(status=ToolStatus.ERROR, content="", error=f"下载失败：{e}")

    async def verify(self, params: dict, result: ToolResult) -> VerificationResult:
        target = Path(result.source) if result.source else _safe_path(self.workspace, params.get("dest", ""))
        passed = target.exists() and target.stat().st_size > 0
        return VerificationResult(
            status=VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
            summary="下载文件已落盘且非空" if passed else "下载文件缺失或为空",
            expected={"exists": True, "nonempty": True},
            observed={"exists": target.exists(), "size": target.stat().st_size if target.exists() else 0},
            checks={"exists": target.exists(), "nonempty": target.stat().st_size > 0 if target.exists() else False},
        )
