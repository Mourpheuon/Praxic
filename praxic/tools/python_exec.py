"""
Praxic Agent —— Python 代码执行工具
在受控沙箱中执行 Python 代码片段，返回结构化结果。
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import structlog

from .base import ActionKind, BaseTool, ChangeRecord, ToolResult, ToolStatus

log = structlog.get_logger(__name__)


class PythonExecTool(BaseTool):
    """
    在 worksapce 内执行 Python 代码片段。

    特性：
    - AST 安全检查（禁止 os.system、subprocess.Popen 等危险操作）
    - 自动注入编码头（utf-8 声明 + stdout reconfigure）
    - 自动 JSON 解析 stdout
    - 超时控制
    - 依赖声明（relaxed 沙盒下自动 pip install）
    """

    name = "python_exec"
    description = "执行 Python 代码片段，返回 stdout、stderr、exit_code 和解析后的结构化数据"
    action_kind = ActionKind.COMPUTE
    requires_authorization = True
    parameter_schema = {
        "code": {"type": "string"},
        "timeout_seconds": {"type": "number", "default": 30},
        "requirements": {"type": "array", "default": []},
    }

    # AST 黑名单：禁止直接调用这些函数/属性
    _BLOCKED_ATTRS = {
        "system",
        "popen",
        "Popen",
        "run",
        "check_output",
        "check_call",
        "call",
        "getoutput",
        "getstatusoutput",
        "exec",
        "eval",
        "compile",
        "remove",
        "unlink",
        "rmdir",
        "removedirs",
        "chmod",
        "chown",
        "kill",
        "send_signal",
        "listen",
        "bind",
        "connect",
        "mkdir",
        "makedirs",
        "open",
        "rename",
        "replace",
        "save",
        "touch",
        "write",
        "writelines",
        "write_bytes",
        "write_text",
        "urlopen",
        "f_builtins",
        "f_globals",
        "f_locals",
        "f_trace",
        "gi_frame",
        "cr_frame",
        "meta_path",
        "modules",
        "path_hooks",
        "setprofile",
        "settrace",
        "tb_frame",
    }
    _BLOCKED_NAMES = {
        "os",
        "subprocess",
        "shutil",
        "signal",
        "ctypes",
        "multiprocessing",
        "threading",
        "socket",
        "aiohttp",
        "ftplib",
        "http",
        "pathlib",
        "requests",
        "smtplib",
        "urllib",
    }
    _BLOCKED_CALL_NAMES = {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
    }
    _SAFE_IMPORTS = {
        "array",
        "bisect",
        "collections",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "fractions",
        "functools",
        "heapq",
        "itertools",
        "json",
        "math",
        "random",
        "re",
        "statistics",
        "string",
        "sys",
        "time",
        "traceback",
        "typing",
    }
    _REQUIREMENT_PATTERN = re.compile(
        r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?"
        r"(?:(?:==|!=|~=|>=|<=|>|<)[A-Za-z0-9.*+_-]+)?$"
    )

    def __init__(self, workspace_dir: str | Path = "", relaxed_sandbox: bool = False):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()
        self.relaxed_sandbox = relaxed_sandbox

    def classify_action(self, params: dict) -> ActionKind:
        return ActionKind.EXTERNAL if params.get("requirements") else ActionKind.COMPUTE

    async def run(
        self,
        code: str,
        timeout_seconds: float = 30.0,
        requirements: list[str] | None = None,
    ) -> ToolResult:
        """
        执行 Python 代码片段。

        1. AST 安全检查
        2. 自动注入编码头
        3. 写入临时文件
        4. pip install 依赖（relaxed 模式）
        5. subprocess 执行
        6. 解析 stdout JSON
        7. 清理临时文件
        """
        requirements = [
            str(package).strip() for package in (requirements or []) if str(package).strip()
        ]
        action_kind = self.classify_action({"requirements": requirements})
        try:
            requirement_imports = self._requirement_import_roots(requirements)
        except ValueError as exc:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=str(exc),
                action_kind=action_kind,
                failure_class="tool_error",
            )
        if requirements and not self.relaxed_sandbox:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error="依赖安装未启用；需要显式启用 relaxed_sandbox 并经过外部行动授权",
                action_kind=action_kind,
                failure_class="tool_error",
            )

        # ── AST 安全检查 ──
        safe, msg = self._check_safety(code, extra_imports=requirement_imports)
        if not safe:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"安全检查未通过: {msg}",
                action_kind=action_kind,
                failure_class="tool_error",
            )

        # ── 自动注入编码头 ──
        code = self._inject_headers(code)

        # ── 写入临时文件 ──
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            dir=str(self.workspace_dir),
            delete=False,
            encoding="utf-8",
        ) as f:
            tmp_path = f.name
            f.write(code)

        # ── 子进程环境 ──
        child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

        try:
            # ── pip install 依赖（relaxed 模式）──
            if requirements and self.relaxed_sandbox:
                for pkg in requirements:
                    proc = await asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        pkg,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    try:
                        install_stdout, install_stderr = await asyncio.wait_for(
                            proc.communicate(),
                            timeout=max(1.0, timeout_seconds),
                        )
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.communicate()
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            content="",
                            error=f"依赖安装超时：{pkg}",
                            action_kind=action_kind,
                            failure_class="tool_error",
                        )
                    if proc.returncode:
                        detail = (install_stderr or install_stdout or b"").decode(
                            "utf-8", "replace"
                        )
                        return ToolResult(
                            status=ToolStatus.ERROR,
                            content="",
                            error=f"依赖安装失败：{pkg}\n{detail[:2000]}",
                            action_kind=action_kind,
                            failure_class="tool_error",
                        )

            # ── 执行 ──
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                tmp_path,
                cwd=str(self.workspace_dir),
                env=child_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="",
                    error=f"执行超时 ({timeout_seconds}s)",
                    data={"exit_code": -1, "stdout": "", "stderr": ""},
                    action_kind=action_kind,
                    failure_class="tool_error",
                )

            stdout_s = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_s = stderr.decode("utf-8", errors="replace") if stderr else ""
            exit_code = proc.returncode or 0

            # ── 解析 JSON ──
            parsed = None
            for line in stdout_s.strip().split("\n"):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        parsed = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue

            status = ToolStatus.SUCCESS if exit_code == 0 else ToolStatus.ERROR
            change = None
            metadata = {"world_changed": False}
            if requirements:
                change = ChangeRecord(
                    target=str(Path(sys.executable).parent),
                    operation="install_python_requirements",
                    changed=None,
                    reversible=False,
                    details={
                        "requirements": requirements,
                        "evidence": "no_independent_environment_readback",
                    },
                )
                metadata = {"world_state_may_have_changed": True}
            result = ToolResult(
                status=status,
                content=stdout_s,
                data={
                    "exit_code": exit_code,
                    "stdout": stdout_s,
                    "stderr": stderr_s,
                    "parsed": parsed,
                },
                error=stderr_s if exit_code != 0 else "",
                action_kind=action_kind,
                change=change,
                metadata=metadata,
                failure_class="tool_error" if exit_code != 0 else "",
            )
            return result

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"执行异常: {e}",
                action_kind=action_kind,
                failure_class="tool_error",
            )
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    @classmethod
    def _requirement_import_roots(cls, requirements: list[str]) -> set[str]:
        roots = set()
        for requirement in requirements:
            compact = requirement.replace(" ", "")
            if not cls._REQUIREMENT_PATTERN.fullmatch(compact):
                raise ValueError(f"依赖声明格式不安全：{requirement}")
            name = re.split(r"[<>=!~\[]", compact, maxsplit=1)[0]
            roots.add(name.replace("-", "_").split(".", 1)[0])
        return roots

    def _check_safety(self, code: str, extra_imports: set[str] | None = None) -> tuple[bool, str]:
        """AST 安全检查：禁止危险调用。"""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"语法错误: {e}"

        allowed_imports = self._SAFE_IMPORTS | set(extra_imports or ())
        for node in ast.walk(tree):
            # 禁止调用 .system() .popen() 等危险方法
            if isinstance(node, ast.Attribute):
                if node.attr.startswith("_") or node.attr in self._BLOCKED_ATTRS:
                    return False, f"禁止调用 {node.attr}()"
            # 普通计算只开放明确的标准库；依赖扩展必须先经过外部行动授权。
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] not in allowed_imports:
                        return False, f"禁止 import {alias.name}"
            if isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".", 1)[0] not in allowed_imports:
                    return False, f"禁止 import {node.module}"
            if isinstance(node, ast.Name):
                if (
                    node.id.startswith("__") and node.id != "__name__"
                ) or node.id in self._BLOCKED_CALL_NAMES:
                    return False, f"禁止引用 {node.id}"

        return True, ""

    def _inject_headers(self, code: str) -> str:
        """自动注入编码头和 stdout 编码配置。"""
        lines = code.split("\n")
        has_encoding = any("# -*- coding: utf-8" in line for line in lines[:3])
        has_reconfigure = any("stdout.reconfigure" in line for line in lines[:5])

        header_lines = []
        if not has_encoding:
            header_lines.append("# -*- coding: utf-8 -*-")
        if not has_reconfigure:
            header_lines.append("import sys; sys.stdout.reconfigure(encoding='utf-8')")

        if header_lines:
            code = "\n".join(header_lines) + "\n" + code
        return code
