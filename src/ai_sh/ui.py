"""Rich terminal rendering and user interaction."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from typing import Literal

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ai_sh.executor import ExecutionResult
from ai_sh.llm import CommandResult

ConfirmChoice = Literal["y", "e", "n"]

console = Console()


def render_command(result: CommandResult) -> None:
    """Render a generated command and its metadata."""

    if result.clarification and not result.command:
        console.print(
            Panel(Text(result.clarification), title="需要澄清", border_style="yellow")
        )
        return

    syntax = Syntax(result.command, "bash", word_wrap=True)
    risk_style = {
        "safe": "green",
        "caution": "yellow",
        "danger": "red",
    }[result.risk_level]

    table = Table.grid(padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("风险", f"[{risk_style}]{result.risk_level}[/{risk_style}]")
    table.add_row("说明", Text(result.explanation))
    if result.risk_reason:
        table.add_row("原因", Text(result.risk_reason))
    if result.alternatives:
        table.add_row("备选", Text("\n".join(result.alternatives)))

    console.print(Panel(syntax, title="生成的命令", border_style=risk_style))
    console.print(table)


def render_block(reason: str) -> None:
    """Render a local safety block."""

    console.print(Panel(Text(reason), title="已拦截危险命令", border_style="red"))


def render_error(message: str) -> None:
    """Render a user-facing error."""

    console.print(Panel(Text(message), title="错误", border_style="red"))


def render_execution_result(result: ExecutionResult) -> None:
    """Render a command execution result."""

    if result.timed_out:
        status = f"命令超过限制时间后已停止，退出码 {result.exit_code}"
        style = "yellow"
    elif result.exit_code == 0:
        status = f"命令已成功执行，退出码 {result.exit_code}"
        style = "green"
    else:
        status = f"命令执行失败，退出码 {result.exit_code}"
        style = "red"

    if not result.stdout and not result.stderr:
        status += "\n没有输出。对于查找类命令，这通常表示没有匹配结果。"

    console.print(Panel(Text(status), title="执行结果", border_style=style))
    if result.stdout:
        console.print(Panel(Text(result.stdout), title="stdout", border_style="blue"))
    if result.stderr:
        console.print(Panel(Text(result.stderr), title="stderr", border_style="yellow"))


def prompt_confirm(
    default: Literal["y", "n"] = "n", *, caution: bool = False
) -> ConfirmChoice:
    """Ask the user whether to execute, edit, or cancel."""

    suffix = "；该命令有风险，执行前还会二次确认" if caution else ""
    default_label = "执行" if default == "y" else "取消"
    prompt = (
        "\n请选择下一步："
        "[y] 执行  [e] 编辑命令  [n] 取消"
        f"（直接回车：{default_label}）{suffix}\n> "
    )
    answer = _read_answer(prompt)
    if not answer:
        return default
    if answer in {"y", "e", "n"}:
        return answer  # type: ignore[return-value]
    console.print("输入无效，已取消。请输入 y、e 或 n。")
    return "n"


def prompt_caution_confirm() -> bool:
    """Ask for a second explicit confirmation for caution commands."""

    answer = _read_answer("该命令存在风险。再次输入 y 确认执行: ")
    return answer == "y"


def edit_command(result: CommandResult) -> CommandResult:
    """Open the generated command in an editor and return the edited result."""

    editor = os.getenv("EDITOR", "vi")
    with tempfile.NamedTemporaryFile("w+", suffix=".sh", delete=False) as temp_file:
        temp_file.write(result.command)
        temp_file.flush()
        path = temp_file.name
    try:
        subprocess.run([editor, path], check=False)
        with open(path, encoding="utf-8") as edited_file:
            command = edited_file.read().strip()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return replace(result, command=command)


def _read_answer(prompt: str) -> str:
    console.print(Text(prompt), end="")
    try:
        value = sys.stdin.readline()
    except KeyboardInterrupt:
        console.print("\n未收到确认，已取消。")
        return ""
    if value == "":
        console.print("\n未收到确认，已取消。")
        return ""
    return value.strip().lower()
