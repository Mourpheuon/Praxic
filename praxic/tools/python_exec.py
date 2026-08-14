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

from .base import ActionKind, BaseTool, ChangeRecord, ToolResult, ToolStatus, head_tail_truncate

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
    category = "code"
    description = "执行 Python 代码片段，返回 stdout、stderr、exit_code 和解析后的结构化数据。数据分析请用标准库 csv/json/statistics，不要 import pandas（未安装）；可只读 open 工作区内文件（写模式禁止）"
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
        "setattr",
        "vars",
    }
    # 内置 open() 允许只读（数据分析读文件的基础），写模式由 _check_safety 拦截。
    _OPEN_WRITE_MODES = {"w", "a", "x", "+"}
    _SAFE_IMPORTS = {
        "array",
        "base64",
        "bisect",
        "collections",
        "csv",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "fractions",
        "functools",
        "glob",
        "hashlib",
        "heapq",
        "io",
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
                            failure_class="timeout",
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
                    failure_class="timeout",
                )

            stdout_s = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_s = stderr.decode("utf-8", errors="replace") if stderr else ""
            exit_code = proc.returncode or 0

            # C1: 输出超限分类——模型应裁剪打印量，而非改逻辑
            output_cap = 2_000_000
            output_limit_hit = exit_code == 0 and len(stdout_s) > output_cap

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
            if output_limit_hit:
                stdout_s = head_tail_truncate(stdout_s, head_chars=4000, tail_chars=2000)
            result = ToolResult(
                status=status,
                content=stdout_s,
                data={
                    "exit_code": exit_code,
                    "stdout": stdout_s if output_limit_hit else stdout_s,
                    "stderr": stderr_s,
                    "parsed": parsed,
                },
                error=stderr_s if exit_code != 0 else "",
                action_kind=action_kind,
                change=change,
                metadata=metadata,
                failure_class=(
                    "output_limit"
                    if output_limit_hit
                    else ("tool_error" if exit_code != 0 else "")
                ),
                # A1: 回填摘要复用解析后的 data，不给全量 stdout
                summary=(
                    f"exit_code={exit_code}，输出超限已截断至 {len(stdout_s)} 字符"
                    if output_limit_hit
                    else f"exit_code={exit_code}，parsed={'有' if parsed is not None else '无'}，stdout {len(stdout_s)} 字符"
                ),
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
            # 内置 open() 只允许只读模式（数据分析读文件基础）；写模式拦截。
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                mode = self._open_mode_arg(node)
                if mode is None:
                    # 无法静态确定 mode（如变量）→ 保守拦截
                    return False, "open() 的 mode 必须显式为只读（如 'r'），不允许变量或省略"
                if any(m in mode for m in self._OPEN_WRITE_MODES):
                    return False, f"open() 写模式被禁止：mode={mode!r}"
            # open 被赋值给变量会绕过 mode 检查（writer = open），禁止此类别名。
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and isinstance(node.value, ast.Name) and node.value.id == "open":
                        return False, "禁止将 open 赋值给变量（会绕过只读检查）"

        return True, ""

    @staticmethod
    def _open_mode_arg(call_node: ast.Call):
        """提取 open() 的 mode 参数（第 2 个位置参数或 mode= 关键字）。"""
        args = list(call_node.args)
        if len(args) >= 2:
            arg = args[1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
            return None
        for kw in call_node.keywords:
            if kw.arg == "mode":
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    return kw.value.value
                return None
        # 未提供 mode：默认 'r'，允许
        return "r"

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
