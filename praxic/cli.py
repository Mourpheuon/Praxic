"""
即物穷理 Praxic —— 命令行接口
用法：
  praxic run "你的问题"
  praxic run "你的问题" --mode deep --context "背景"
  praxic serve              # 启动 FastAPI
  praxic config show        # 显示当前配置
"""

from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

app = typer.Typer(
    name="praxic",
    help="即物穷理 Praxic —— 以辩证唯物主义方法论为认知内核的 AI 智能体",
    add_completion=False,
)
console = Console()
config_app = typer.Typer(help="配置管理")
app.add_typer(config_app, name="config")


@app.command("run")
def cmd_run(
    question: str = typer.Argument(..., help="要分析的问题"),
    mode: str = typer.Option("standard", "--mode", "-m",
                              help="运行模式：fast | standard | deep"),
    context: str = typer.Option("", "--context", "-c", help="背景上下文"),
    conversation_id: str = typer.Option("", "--conversation-id", "-cid",
                                         help="多轮对话ID，同ID共享历史上下文"),
    no_trace: bool = typer.Option(False, "--no-trace", help="不输出完整轨迹"),
    autonomy: str = typer.Option("standard", "--autonomy",
                                  help="权限级别：read_only | sandboxed | standard | elevated"),
    review: str = typer.Option("once", "--review", "-rv",
                                help="多视角审查：off | once | iterative"),
    files: str = typer.Option("", "--files", "-f",
                               help="文件路径，逗号分隔，如 'a.pdf,b.docx'"),
    project: str = typer.Option("", "--project", "-p",
                                 help="项目 ID（独立 workspace 与历史分组）"),
):
    """运行认知循环，分析问题"""
    from .core.cognitive_loop import CognitiveLoop
    from .config import settings, AutonomyLevel
    import uuid

    try:
        settings.autonomy_level = AutonomyLevel[autonomy.upper()]
    except KeyError:
        console.print(f"[red]未知权限级别：{autonomy}[/red]")
        raise typer.Exit(1)

    cid = conversation_id or str(uuid.uuid4())[:8]
    phase_order = []

    def on_phase(phase: str, summary: str):
        phase_order.append((phase, summary))
        phase_icons = {
            "investigation": "🔍", "contradiction":  "⚡",
            "rational":       "🧠", "decision":       "🎯",
            "perspectives":   "👥", "reflection":     "🔄",
        }
        icon = phase_icons.get(phase, "•")
        console.print(f"  {icon} [bold]{phase}[/bold] {summary}")

    file_list = [f.strip() for f in files.split(",") if f.strip()] if files else None
    async def _run():
        loop = CognitiveLoop(conversation_id=cid, project_id=project)
        return await loop.run(
            question=question, context=context, mode=mode,
            on_phase=on_phase, conversation_id=cid,
            review_strategy=review,
            files=file_list, project_id=project,
        )

    console.print(Panel(
        f"[bold cyan]{question}[/bold cyan]",
        title="[bold]即物穷理 认知循环[/bold]",
        subtitle=f"模式：{mode} | 对话：{cid}",
    ))
    console.print()

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        console=console, transient=True,
    ) as progress:
        task = progress.add_task("正在运行认知循环…", total=None)
        response = asyncio.run(_run())
        progress.stop_task(task)

    console.print(Panel(Markdown(response.summary),
                  title="[bold green]📋 最终结论[/bold green]"))

    if response.action_items:
        table = Table(title="✅ 具体行动建议", show_header=False, box=None)
        table.add_column("", style="cyan", no_wrap=False)
        for i, item in enumerate(response.action_items, 1):
            table.add_row(f"{i}. {item}")
        console.print(table)

    if not no_trace and response.full_trace:
        trace = response.full_trace
        console.print()
        console.print("[dim]─── 认知轨迹摘要 ───[/dim]")
        if trace.contradictions and trace.contradictions.principal_contradiction:
            pc = trace.contradictions.principal_contradiction
            console.print(f"[bold]主要矛盾：[/bold] {pc.description[:120]}")
        if trace.reflection:
            console.print(
                f"[bold]收敛度：[/bold] {trace.reflection.convergence_score:.2f} | "
                f"[bold]迭代次数：[/bold] {trace.metadata.iterations}")
        durations = trace.metadata.phase_durations
        if durations:
            total = sum(durations.values())
            console.print(
                f"[dim]总耗时：{total:.1f}s  "
                + "  ".join(f"{k}:{v:.1f}s" for k, v in durations.items())
                + "[/dim]")

    console.print(f"\n[dim]Session ID: {response.session_id}[/dim]")


@app.command("serve")
def cmd_serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload"),
):
    """启动 FastAPI REST API 服务"""
    from .api.server import run_server
    console.print(f"[bold]即物穷理 API[/bold] 启动于 http://{host}:{port}")
    console.print(f"  文档：http://{host}:{port}/docs")
    run_server(host=host, port=port, reload=reload)


@config_app.command("show")
def config_show():
    """显示当前配置"""
    from .config import settings
    table = Table(title="即物穷理 配置", show_header=True)
    table.add_column("配置项", style="cyan")
    table.add_column("值", style="white")
    table.add_row("default_model", settings.default_model)
    table.add_row("autonomy_level", settings.autonomy_level.name)
    table.add_row("max_iterations", str(settings.max_iterations))
    table.add_row("data_dir", str(settings.data_dir))
    table.add_row(
        "anthropic_api_key",
        "✓ 已配置" if settings.anthropic_api_key else "✗ 未配置",
    )
    console.print(table)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="配置项名称"),
    value: str = typer.Argument(..., help="配置值"),
):
    """持久化修改配置项（写入 .env 文件）"""
    from pathlib import Path
    from .config import ROOT_DIR

    env_file = ROOT_DIR / ".env"
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []

    env_key = f"PRAXIC_{key.upper()}"
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{env_key}="):
            new_lines.append(f"{env_key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{env_key}={value}")

    env_