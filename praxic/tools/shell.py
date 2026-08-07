"""Structured subprocess tool for scoped real-world inspection and actions."""

from __future__ import annotations

import asyncio
import os
import shlex
import time
from pathlib import Path

from .base import (
    ActionKind,
    BaseTool,
    ChangeRecord,
    ToolResult,
    ToolStatus,
    VerificationResult,
    VerificationStatus,
)
from .permissions import PathGuard


class ShellTool(BaseTool):
    """Run an argv command without a shell, inside an allowed working root.

    The command is intentionally represented as argv.  Shell metacharacters,
    command chaining and redirection are rejected before process creation.
    Mutating or network-like commands are classified as external actions and
    therefore reach the registry authorization gate.
    """

    name = "shell_exec"
    category = "code"
    description = "在允许的工作目录中执行结构化命令并返回 stdout、stderr 和退出码"
    requires_network = False
    action_kind = ActionKind.COMPUTE
    requires_authorization = True
    sandbox_safe = True
    parameter_schema = {
        "command": {"type": "array", "description": "程序及参数，例如 ['python', '-V']"},
        "cwd": {"type": "string", "default": ""},
        "timeout_seconds": {"type": "number", "default": 30},
    }

    _READ_COMMANDS = {
        "cat",
        "dir",
        "echo",
        "git",
        "ls",
        "node",
        "npm",
        "npm.cmd",
        "python",
        "python.exe",
        "py",
        "py.exe",
        "pwd",
        "rg",
        "rg.exe",
        "type",
        "where",
        "whoami",
    }
    _MUTATING_SUBCOMMANDS = {
        "add",
        "apply",
        "checkout",
        "clean",
        "clone",
        "commit",
        "config",
        "delete",
        "install",
        "mv",
        "push",
        "remove",
        "reset",
        "rm",
        "rmdir",
        "run",
        "set",
        "start",
        "stop",
        "uninstall",
        "write",
    }
    _NETWORK_WORDS = {"curl", "wget", "Invoke-WebRequest", "fetch", "push", "clone", "pull"}
    _BLOCKED_TOKENS = {"&&", "||", ";", "|", ">", ">>", "<", "&", "`", "$", "\n", "\r"}
    _INTERPRETERS = {"node", "node.exe", "python", "python.exe", "py", "py.exe"}
    _INLINE_CODE_FLAGS = {"-c", "-e", "--eval", "--print"}
    _VERSION_FLAGS = {"-v", "--version", "-h", "--help"}
    _GIT_READ_ONLY_SUBCOMMANDS = {
        "blame",
        "cat-file",
        "describe",
        "diff",
        "for-each-ref",
        "grep",
        "log",
        "ls-files",
        "ls-tree",
        "merge-base",
        "name-rev",
        "rev-parse",
        "shortlog",
        "show",
        "show-ref",
        "status",
    }
    _GIT_OPTIONS_WITH_VALUE = {
        "-c",
        "-C",
        "--config-env",
        "--git-dir",
        "--namespace",
        "--super-prefix",
        "--work-tree",
    }
    _OUTPUT_OPTIONS = {"-o", "--output"}

    def __init__(
        self,
        allowed_roots: list[str | Path] | tuple[str | Path, ...] = (),
        allowed_commands: set[str] | None = None,
        environment: dict[str, str] | None = None,
    ):
        self.path_guard = PathGuard(allowed_roots)
        self.allowed_commands = {c.lower() for c in (allowed_commands or self._READ_COMMANDS)}
        self.environment = environment or {}

    def _argv(self, command: list[str] | tuple[str, ...] | str) -> list[str]:
        if isinstance(command, str):
            if any(token in command for token in self._BLOCKED_TOKENS):
                raise ValueError("命令包含 shell 链接、管道或重定向符号")
            command = shlex.split(command, posix=False)
        argv = [str(part) for part in command]
        if not argv or not argv[0].strip():
            raise ValueError("command 不能为空")
        if any(any(token in part for token in self._BLOCKED_TOKENS) for part in argv):
            raise ValueError("命令参数包含不允许的 shell 控制符")
        executable = Path(argv[0]).name.lower()
        if executable not in self.allowed_commands:
            raise PermissionError(f"命令未列入允许清单，已阻止执行：{executable}")
        return argv

    def classify_action(self, params: dict) -> ActionKind:
        try:
            return self.classify_command(self._argv(params.get("command", [])))
        except (ValueError, PermissionError):
            return self.action_kind

    @classmethod
    def classify_command(cls, argv: list[str]) -> ActionKind:
        exe = Path(argv[0]).name.lower()
        lower = {part.lower() for part in argv[1:]}
        if exe in cls._INTERPRETERS:
            return (
                ActionKind.COMPUTE if lower and lower <= cls._VERSION_FLAGS else ActionKind.EXTERNAL
            )
        if exe in {"npm", "npm.cmd"}:
            return (
                ActionKind.COMPUTE if lower and lower <= cls._VERSION_FLAGS else ActionKind.EXTERNAL
            )
        if exe in {word.lower() for word in cls._NETWORK_WORDS} or lower & {
            word.lower() for word in cls._NETWORK_WORDS
        }:
            return ActionKind.EXTERNAL
        if exe == "git":
            subcommand = cls._git_subcommand(argv[1:])
            writes_output = any(
                part in cls._OUTPUT_OPTIONS or part.startswith("--output=") for part in argv[1:]
            )
            if subcommand in cls._GIT_READ_ONLY_SUBCOMMANDS and not writes_output:
                return ActionKind.OBSERVE
            if not subcommand and lower and lower <= cls._VERSION_FLAGS:
                return ActionKind.COMPUTE
            return ActionKind.EXTERNAL
        if lower & cls._MUTATING_SUBCOMMANDS and exe in {
            "npm",
            "npm.cmd",
            "python",
            "python.exe",
            "py",
            "py.exe",
        }:
            return ActionKind.EXTERNAL
        return (
            ActionKind.OBSERVE
            if exe in {"git", "rg", "ls", "dir", "cat", "type", "where", "whoami", "pwd"}
            else ActionKind.COMPUTE
        )

    @classmethod
    def _git_subcommand(cls, args: list[str]) -> str:
        index = 0
        while index < len(args):
            part = args[index]
            if part in cls._GIT_OPTIONS_WITH_VALUE:
                index += 2
                continue
            if any(
                part.startswith(option + "=")
                for option in cls._GIT_OPTIONS_WITH_VALUE
                if option.startswith("--")
            ):
                index += 1
                continue
            if part.startswith("-"):
                index += 1
                continue
            return part.lower()
        return ""

    def _validate_interpreter(self, argv: list[str], run_cwd: Path) -> None:
        executable = Path(argv[0]).name.lower()
        if executable not in self._INTERPRETERS:
            return
        lower = {part.lower() for part in argv[1:]}
        if lower & self._INLINE_CODE_FLAGS:
            raise PermissionError("Shell 不执行解释器内联代码；请改用 python_exec 等受控工具")
        for argument in argv[1:]:
            candidate = argument.strip("\"'")
            if candidate.startswith("-"):
                continue
            if Path(candidate).suffix.lower() not in {".py", ".js", ".cjs", ".mjs"}:
                continue
            script_path = Path(candidate)
            if not script_path.is_absolute():
                script_path = run_cwd / script_path
            self.path_guard.resolve(script_path, allow_missing=False)
            break

    async def run(
        self,
        command: list[str] | tuple[str, ...] | str,
        cwd: str = "",
        timeout_seconds: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> ToolResult:
        try:
            argv = self._argv(command)
            action_kind = self.classify_command(argv)
            run_cwd = self.path_guard.resolve(
                cwd or (self.path_guard.roots[0] if self.path_guard.roots else Path.cwd())
            )
            self._validate_interpreter(argv, run_cwd)
        except (ValueError, PermissionError, OSError) as exc:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=str(exc),
                action_kind=self.action_kind,
                failure_class="tool_error",
            )

        child_env = os.environ.copy()
        child_env.update(self.environment)
        if env:
            child_env.update({str(k): str(v) for k, v in env.items()})
        started = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(run_cwd),
                env=child_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return ToolResult(
                    status=ToolStatus.ERROR,
                    content="",
                    error=f"执行超时 ({timeout_seconds}s)",
                    data={"argv": argv, "cwd": str(run_cwd), "exit_code": -1},
                    action_kind=action_kind,
                    metadata={
                        "expected_change": action_kind in (ActionKind.CHANGE, ActionKind.EXTERNAL)
                    },
                    failure_class="tool_error",
                )
            out = (stdout or b"").decode("utf-8", "replace")
            err = (stderr or b"").decode("utf-8", "replace")
            code = proc.returncode or 0
            status = ToolStatus.SUCCESS if code == 0 else ToolStatus.ERROR
            change = None
            if action_kind in (ActionKind.CHANGE, ActionKind.EXTERNAL):
                change = ChangeRecord(
                    target=str(run_cwd),
                    operation=" ".join(argv),
                    changed=None,
                    reversible=False,
                    details={"exit_code": code, "evidence": "no_independent_readback"},
                )
            return ToolResult(
                status=status,
                content=out,
                data={
                    "argv": argv,
                    "cwd": str(run_cwd),
                    "exit_code": code,
                    "stdout": out,
                    "stderr": err,
                },
                error=err if code else "",
                source=str(run_cwd),
                action_kind=action_kind,
                change=change,
                metadata={
                    "expected_change": action_kind in (ActionKind.CHANGE, ActionKind.EXTERNAL),
                    "world_state_may_have_changed": action_kind
                    in (ActionKind.CHANGE, ActionKind.EXTERNAL),
                },
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
        except Exception as exc:
            return ToolResult(
                status=ToolStatus.ERROR,
                content="",
                error=f"命令执行异常：{exc}",
                data={"argv": argv, "cwd": str(run_cwd)},
                action_kind=action_kind,
                failure_class="tool_error",
            )

    async def verify(self, params: dict, result: ToolResult) -> VerificationResult:
        if result.status == ToolStatus.ERROR:
            return VerificationResult(
                status=VerificationStatus.FAILED, summary="命令失败，无法验证"
            )
        if result.action_kind in (ActionKind.CHANGE, ActionKind.EXTERNAL):
            return VerificationResult(
                status=VerificationStatus.SKIPPED,
                summary="命令退出码为 0，但没有独立回读证据，世界状态变化未证实",
                expected={"exit_code": 0, "independent_readback": True},
                observed={
                    "exit_code": (result.data or {}).get("exit_code"),
                    "independent_readback": False,
                },
                checks={
                    "exit_code": (result.data or {}).get("exit_code") == 0,
                    "independent_readback": False,
                },
            )
        return VerificationResult(
            status=VerificationStatus.PASSED,
            summary="只读或计算命令退出码为 0",
            expected={"exit_code": 0},
            observed=(result.data or {}).get("exit_code"),
            checks={"exit_code": (result.data or {}).get("exit_code") == 0},
        )
