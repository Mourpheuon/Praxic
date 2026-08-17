"""
Praxic Agent —— 开发者追踪模块
在开发者模式下记录每个阶段 LLM 的原始输出。

输出通道：
1. 控制台（rich 格式化面板）
2. 结构化日志文件（JSONL，按 session_id 分文件）
3. UI 回调（供桌面应用实时展示）
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

import structlog

from ..llm.base import BaseLLM, LLMResponse

log = structlog.get_logger(__name__)

PHASE_LABELS = {
    "investigation":  "调查研究",
    "contradiction":  "矛盾分析",
    "rational":        "理性认识",
    "practice":        "实践检验",
    "reflection":      "反思复盘",
}

PHASE_EMOJI = {
    "investigation":  "🔍",
    "contradiction":  "⚡",
    "rational":        "🧠",
    "practice":        "⚙️",
    "reflection":      "🔄",
}


class DevTracer:
    """开发者追踪器 —— 记录各阶段 LLM 输出到多个通道。"""

    def __init__(
        self,
        enabled: bool = False,
        log_dir: str | Path = "./logs",
        console_output: bool = True,
        session_id: str = "",
    ):
        self.enabled = enabled
        self.log_dir = Path(log_dir)
        self.console_output = console_output
        self.session_id = session_id
        self._log_file: Optional[Path] = None
        self._listeners: list[Callable[[dict], None]] = []
        self._trace_count = 0

    def set_session(self, session_id: str):
        self.session_id = session_id
        self._log_file = None  # reset so next trace creates new file
        self._trace_count = 0

    def _ensure_log_file(self):
        if self._log_file is not None:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        sid = self.session_id or "unknown"
        self._log_file = self.log_dir / f"dev_trace_{ts}_{sid}.jsonl"

    def trace(self, phase: str, output: str, *, tag: str = "") -> None:
        """记录一次 LLM 调用输出。

        Args:
            phase: 阶段标识（investigation/contradiction/...）
            output: LLM 原始输出文本
            tag: 可选的子标签（如 practice 的 "plan_round1" 等）
        """
        if not self.enabled:
            return

        self._trace_count += 1
        timestamp = datetime.now().isoformat()
        label = PHASE_LABELS.get(phase, phase)
        emoji = PHASE_EMOJI.get(phase, "📝")

        # Build trace record
        record = {
            "seq": self._trace_count,
            "phase": phase,
            "tag": tag,
            "timestamp": timestamp,
            "session_id": self.session_id,
            "output": output,
        }

        # Channel 1: Console (rich formatted)
        if self.console_output:
            self._console_render(phase, label, emoji, output, tag, self._trace_count)

        # Channel 2: JSONL log file
        self._ensure_log_file()
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            log.warning("dev_tracer.file_write_error", exc_info=True)

        # Channel 3: UI listeners
        for listener in self._listeners:
            try:
                listener(record)
            except Exception:
                log.warning("dev_tracer.listener_error", exc_info=True)

    def on_trace(self, callback: Callable[[dict], None]) -> None:
        """注册 UI 回调。每次 trace 时调用 callback(record)。"""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[dict], None]) -> None:
        """移除之前注册的 UI 回调。"""
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _console_render(
        self, phase: str, label: str, emoji: str, output: str,
        tag: str, seq: int,
    ) -> None:
        """用 rich 在控制台格式化打印输出。"""
        header = f" {emoji} [{label}]"
        if tag:
            header += f" · {tag}"
        header += f"  (#{seq})"

        width = 88
        sep = "─" * width

        # Truncate very long outputs for console readability
        display = output
        max_display = 4000
        if len(display) > max_display:
            display = display[:max_display] + f"\n\n... [截断，共 {len(output)} 字符]"

        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.text import Text

            console = Console()
            phase_color = {
                "investigation": "cyan", "contradiction": "yellow",
                "rational": "blue", "practice": "bright_yellow",
                "reflection": "red",
            }.get(phase, "white")

            text = Text(display)
            console.print(
                Panel(text, title=header, border_style=phase_color, width=width)
            )
        except ImportError:
            # Fallback without rich
            print(f"\n{sep}")
            print(f"{header}")
            print(sep)
            print(display)
            print(sep)


class TracingLLMWrapper(BaseLLM):
    """LLM 包装器 —— 拦截 call/stream 并将输出发送到 DevTracer。"""

    def __init__(self, inner: BaseLLM, tracer: DevTracer, phase: str, tag: str = ""):
        self._inner = inner
        self._tracer = tracer
        self._phase = phase
        self._tag = tag

    @property
    def provider_name(self):
        return getattr(self._inner, "provider_name", "unknown")

    @property
    def supports_prompt_cache(self):
        return bool(getattr(self._inner, "supports_prompt_cache", False))

    def cache_capabilities(self) -> dict:
        if hasattr(self._inner, "cache_capabilities"):
            return self._inner.cache_capabilities()
        return super().cache_capabilities()

    def cache_stats(self) -> dict:
        if hasattr(self._inner, "cache_stats"):
            return self._inner.cache_stats()
        return super().cache_stats()

    async def call(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
        result = await self._inner.call(
            messages, system=system, temperature=temperature,
            max_tokens=max_tokens, **kwargs,
        )
        self._tracer.trace(self._phase, result.content, tag=self._tag)
        return result

    async def stream(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        **kwargs,
    ) -> AsyncIterator[str]:
        collected: list[str] = []
        async for chunk in self._inner.stream(
            messages, system=system, temperature=temperature,
            max_tokens=max_tokens, **kwargs,
        ):
            collected.append(chunk)
            yield chunk
        full = "".join(collected)
        self._tracer.trace(self._phase, full, tag=f"{self._tag}(stream)" if self._tag else "stream")
