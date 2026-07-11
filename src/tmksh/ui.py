"""Rich terminal rendering and user interaction."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from tmksh.llm import AssistantResult

console = Console()


def render_result(result: AssistantResult, *, cwd: str | None = None) -> None:
    """Render any normalized assistant result."""

    if result.kind == "clarification":
        console.print(
            Panel(Text(result.clarification), title="需要澄清", border_style="yellow")
        )
        return
    if result.kind == "answer":
        console.print(Panel(Text(result.answer), title="回答", border_style="blue"))
        return
    if result.kind == "blocked":
        render_block(result.risk_reason)
        return
    if result.kind == "error":
        render_error(result.error)
        return
    render_command(result, cwd=cwd)


def render_command(result: AssistantResult, *, cwd: str | None = None) -> None:
    """Render a generated command and its metadata."""

    display_cwd = cwd or str(Path.cwd())
    syntax = Syntax(result.command, "bash", word_wrap=True)
    risk_style = {
        "safe": "green",
        "caution": "yellow",
        "danger": "red",
    }[result.risk_level]

    table = Table.grid(padding=(0, 1), expand=True)
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column(ratio=1)
    table.add_row("目录", Text(display_cwd))
    table.add_row("说明", Text(result.explanation))
    table.add_row("风险", Text(_risk_label(result.risk_level), style=risk_style))
    if result.risk_reason:
        table.add_row("原因", Text(result.risk_reason))
    console.print(Panel(syntax, title="建议命令（未执行）", border_style=risk_style))
    console.print(table)


def render_block(reason: str) -> None:
    """Render a local safety block."""

    console.print(Panel(Text(reason), title="已拦截危险命令", border_style="red"))


def render_error(message: str) -> None:
    """Render a user-facing error."""

    console.print(Panel(Text(message), title="错误", border_style="red"))


def _risk_label(risk_level: str) -> str:
    labels = {
        "safe": "safe（只读或低风险）",
        "caution": "caution（需要谨慎确认）",
        "danger": "danger（禁止执行）",
    }
    return labels.get(risk_level, risk_level)
