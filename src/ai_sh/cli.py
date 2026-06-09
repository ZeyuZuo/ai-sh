"""Command-line entry points for ai-sh."""

from __future__ import annotations

import sys
from dataclasses import replace

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from ai_sh.config import Config, ensure_default_config, load_config
from ai_sh.context import collect_context
from ai_sh.exceptions import AiShError
from ai_sh.executor import execute_command, summarize_execution
from ai_sh.history import HISTORY_PATH, Conversation, HistoryStore, new_history_entry
from ai_sh.llm import (
    CommandResult,
    build_messages,
    generate_command,
    result_to_assistant_message,
)
from ai_sh.safety import SafetyVerdict, check_command
from ai_sh.ui import (
    console,
    edit_command,
    prompt_confirm,
    render_block,
    render_command,
    render_error,
    render_execution_result,
)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("request", nargs=-1)
@click.option("--init-config", is_flag=True, help="Create ~/.ai-sh/config.toml.")
@click.option("--dry-run", is_flag=True, help="Generate and inspect without executing.")
def ai(request: tuple[str, ...], init_config: bool, dry_run: bool) -> None:
    """Generate a shell command from natural language."""

    if init_config:
        path = ensure_default_config()
        console.print(f"已创建配置文件：{path}")
        return

    user_input = " ".join(request).strip()
    if not user_input:
        raise click.UsageError("请提供自然语言请求，例如：ai '找出超过 100MB 的文件'")

    stdin_context = _read_stdin_if_piped()
    _run_once(user_input, stdin_context=stdin_context, dry_run=dry_run)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--init-config", is_flag=True, help="Create ~/.ai-sh/config.toml.")
@click.option("--dry-run", is_flag=True, help="Generate and inspect without executing.")
def ai_sh(init_config: bool, dry_run: bool) -> None:
    """Start the ai-sh REPL."""

    if init_config:
        path = ensure_default_config()
        console.print(f"已创建配置文件：{path}")
        return

    try:
        config = load_config()
        history = HistoryStore(limit=config.behavior.history_limit)
    except AiShError as exc:
        render_error(str(exc))
        raise SystemExit(1) from exc

    conversation = Conversation(max_messages=20)
    HISTORY_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    prompt_history = FileHistory(str(HISTORY_PATH.parent / "repl.txt"))
    session: PromptSession[str] = PromptSession(history=prompt_history)
    console.print(
        "[bold]ai-sh[/bold] REPL 已启动。输入自然语言请求；输入 exit 或 quit 退出。"
    )

    while True:
        try:
            user_input = session.prompt("ai> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if not user_input:
            continue
        if user_input in {"exit", "quit"}:
            return
        _run_once(
            user_input,
            stdin_context="",
            dry_run=dry_run,
            config=config,
            history=history,
            conversation=conversation,
        )


def _run_once(
    user_input: str,
    *,
    stdin_context: str,
    dry_run: bool,
    config: Config | None = None,
    history: HistoryStore | None = None,
    conversation: Conversation | None = None,
) -> None:
    try:
        config = config or load_config()
        history = history or HistoryStore(limit=config.behavior.history_limit)
        recent_commands = (
            history.recent_commands(config.behavior.context_commands)
            if conversation
            else []
        )
        env_context = collect_context(recent_commands=recent_commands)
        messages = build_messages(
            user_input,
            env_context,
            stdin_context=stdin_context,
            conversation=conversation.messages if conversation else None,
            language=config.behavior.language,
        )
        result = generate_command(config, messages)
        render_command(result, cwd=str(env_context.get("cwd", "")))
        if conversation:
            conversation.add_user(user_input)
            conversation.add_assistant(result_to_assistant_message(result)["content"])
        if not result.command:
            return
        _handle_result(
            user_input,
            result,
            config=config,
            history=history,
            conversation=conversation,
            dry_run=dry_run,
        )
    except AiShError as exc:
        render_error(str(exc))
    except KeyboardInterrupt:
        console.print("\n已取消。")


def _handle_result(
    user_input: str,
    result: CommandResult,
    *,
    config: Config,
    history: HistoryStore,
    conversation: Conversation | None,
    dry_run: bool,
) -> None:
    verdict = check_command(
        result.command, hard_block_enabled=config.safety.hard_block_enabled
    )
    verdict = _merge_ai_risk(result.risk_level, result.risk_reason, verdict)
    if verdict.action == "block":
        render_block(verdict.reason)
        history.append(new_history_entry(user_input, result.command, executed=False))
        return

    if dry_run:
        history.append(new_history_entry(user_input, result.command, executed=False))
        console.print("dry-run：已生成并检查命令，没有执行。")
        return

    caution = result.risk_level == "caution"
    if result.risk_level == "safe":
        console.print("safe：自动执行只读或低风险命令。")
        _execute_and_record(
            user_input,
            result,
            history=history,
            conversation=conversation,
        )
        return

    if caution and result.risk_reason:
        console.print(f"[yellow]注意：{result.risk_reason}[/yellow]")

    choice = prompt_confirm(
        config.behavior.default_confirm,
        caution=caution,
        alternatives_count=len(result.alternatives),
    )
    if isinstance(choice, int):
        result = _switch_to_alternative(result, choice)
        render_command(result)
        _handle_result(
            user_input,
            result,
            config=config,
            history=history,
            conversation=conversation,
            dry_run=dry_run,
        )
        return
    if choice == "n":
        history.append(new_history_entry(user_input, result.command, executed=False))
        console.print("已取消，没有执行任何命令。")
        return
    if choice == "e":
        result = edit_command(result)
        render_command(result)
        edited_verdict = check_command(
            result.command, hard_block_enabled=config.safety.hard_block_enabled
        )
        edited_verdict = _merge_ai_risk(
            result.risk_level, result.risk_reason, edited_verdict
        )
        if edited_verdict.action == "block":
            render_block(edited_verdict.reason)
            history.append(
                new_history_entry(user_input, result.command, executed=False)
            )
            return
        confirm_edited = prompt_confirm(
            "n",
            caution=result.risk_level == "caution",
            alternatives_count=len(result.alternatives),
        )
        if confirm_edited != "y":
            history.append(
                new_history_entry(user_input, result.command, executed=False)
            )
            console.print("已取消，没有执行任何命令。")
            return

    _execute_and_record(
        user_input,
        result,
        history=history,
        conversation=conversation,
    )


def _execute_and_record(
    user_input: str,
    result: CommandResult,
    *,
    history: HistoryStore,
    conversation: Conversation | None,
) -> None:
    execution = execute_command(result.command)
    render_execution_result(execution)
    history.append(
        new_history_entry(
            user_input,
            result.command,
            executed=True,
            exit_code=execution.exit_code,
        )
    )
    if conversation:
        conversation.add_execution_summary(summarize_execution(execution))


def _merge_ai_risk(
    risk_level: str, risk_reason: str, local_verdict: SafetyVerdict
) -> SafetyVerdict:
    if local_verdict.action == "block":
        return local_verdict
    if risk_level == "danger":
        return SafetyVerdict("block", risk_reason or "AI 标记该命令为 danger。")
    return local_verdict


def _switch_to_alternative(result: CommandResult, index: int) -> CommandResult:
    command = result.alternatives[index - 1]
    remaining = [
        alternative
        for position, alternative in enumerate(result.alternatives, start=1)
        if position != index
    ]
    return replace(
        result,
        command=command,
        explanation=f"已切换到备选命令 {index}。请重新确认后执行。",
        alternatives=[result.command, *remaining],
    )


def _read_stdin_if_piped() -> str:
    if sys.stdin.isatty():
        return ""
    return sys.stdin.read()
