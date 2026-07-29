"""
思悟 Agent —— Python 代码执行工具
在受控沙箱中执行 Python 代码片段，返回结构化结果。
"""
from __future__ import annotations
import ast, asyncio, json, os, sys, tempfile
from pathlib import Path

import structlog

from .base import BaseTool, ToolResult, ToolStatus

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

    # AST 黑名单：禁止直接调用这些函数/属性
    _BLOCKED_ATTRS = {
        "system", "popen", "Popen", "run", "check_output", "check_call",
        "call", "getoutput", "getstatusoutput",
        "exec", "eval", "compile",
        "remove", "unlink", "rmdir", "removedirs",
        "chmod", "chown", "kill", "send_signal",
        "listen", "bind", "connect",
    }
    _BLOCKED_NAMES = {
        "os", "subprocess", "shutil", "signal", "ctypes",
        "multiprocessing", "threading", "socket",
    }

    def __init__(self, workspace_dir: str | Path = "", relaxed_sandbox: bool = False):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()
        self.relaxed_sandbox = relaxed_sandbox

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
        # ── AST 安全检查 ──
        safe, msg = self._check_safety(code)
        if not safe:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"安全检查未通过: {msg}",
            )

        # ── 自动注入编码头 ──
        code = self._inject_headers(code)

        # ── 写入临时文件 ──
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir=str(self.workspace_dir),
            delete=False, encoding="utf-8",
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
                        sys.executable, "-m", "pip", "install", pkg,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await proc.communicate()

            # ── 执行 ──
            proc = await asyncio.create_subprocess_exec(
                sys.executable, tmp_path,
                cwd=str(self.workspace_dir),
                env=child_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="",
                    error=f"执行超时 ({timeout_seconds}s)",
                    data={"exit_code": -1, "stdout": "", "stderr": ""},
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
            )
            return result

        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"执行异常: {e}",
            )
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _check_safety(self, code: str) -> tuple[bool, str]:
        """AST 安全检查：禁止危险调用。"""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"语法错误: {e}"

        for node in ast.walk(tree):
            # 禁止调用 .system() .popen() 等危险方法
            if isinstance(node, ast.Attribute):
                if node.attr in self._BLOCKED_ATTRS:
                    return False, f"禁止调用 {node.attr}()"
            # 禁止 import 危险模块
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in self._BLOCKED_NAMES:
                        return False, f"禁止 import {alias.name}"
            if isinstance(node, ast.ImportFrom):
                if node.module in self._BLOCKED_NAMES:
                    return False, f"禁止 import {node.module}"

        return True, ""

    def _inject_headers(self, code: str) -> str:
        """自动注入编码头和 stdout 编码配置。"""
        lines = code.split("\n")
        has_encoding = any("# -*- coding: utf-8" in l for l in lines[:3])
        has_reconfigure = any("stdout.reconfigure" in l for l in lines[:5])

        header_lines = []
        if not has_encoding:
            header_lines.append("# -*- coding: utf-8 -*-")
        if not has_reconfigure:
            header_lines.append("import sys; sys.stdout.reconfigure(encoding='utf-8')")

        if header_lines:
            code = "\n".join(header_lines) + "\n" + code
        return code
