"""Command-line entry points for ai-sh."""

from __future__ import annotations

import sys
from getpass import getpass

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from ai_sh.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    Config,
    ensure_default_config,
    load_config,
    validate_api_config,
    write_config,
)
from ai_sh.exceptions import AiShError
from ai_sh.executor import execute_command, summarize_execution
from ai_sh.history import HISTORY_PATH, Conversation, HistoryStore, new_history_entry
from ai_sh.llm import AssistantResult, result_to_assistant_message
from ai_sh.suggestion import create_suggestion, normalize_result
from ai_sh.ui import (
    console,
    edit_command,
    prompt_confirm,
    render_error,
    render_execution_result,
    render_result,
)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("request", nargs=-1)
@click.option("--init-config", is_flag=True, help="Create ~/.ai-sh/config.toml.")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Deprecated compatibility flag; suggestions are never executed.",
)
def ai(request: tuple[str, ...], init_config: bool, dry_run: bool) -> None:
    """Suggest a shell command from natural language without executing it."""

    if init_config:
        path = ensure_default_config()
        console.print(f"已创建配置文件：{path}")
        return

    user_input = " ".join(request).strip()
    if not user_input:
        raise click.UsageError("请提供自然语言请求，例如：ai '找出超过 100MB 的文件'")

    stdin_context = _read_stdin_if_piped()
    _run_suggestion_once(user_input, stdin_context=stdin_context)


@click.group(
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.pass_context
@click.option("--init-config", is_flag=True, help="Create ~/.ai-sh/config.toml.")
def ai_sh(ctx: click.Context, init_config: bool) -> None:
    """Manage ai-sh configuration and shell integration."""

    if init_config:
        path = ensure_default_config()
        console.print(f"已创建配置文件：{path}")
        return
    if ctx.invoked_subcommand is not None:
        return

    console.print(ctx.get_help())
    console.print("\n运行 `ai-sh repl` 可临时使用旧版 REPL。")


@ai_sh.command("repl", context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--dry-run", is_flag=True, help="Generate and inspect without executing.")
def repl(dry_run: bool) -> None:
    """Start the legacy command-executing REPL."""

    try:
        config = load_config()
        validate_api_config(config)
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
        _run_legacy_once(
            user_input,
            stdin_context="",
            dry_run=dry_run,
            config=config,
            history=history,
            conversation=conversation,
        )


@ai_sh.command("config", context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--base-url", help="OpenAI-compatible API base URL.")
@click.option("--model", help="Model name.")
@click.option("--api-key", help="API key. If omitted, an interactive prompt is used.")
@click.option(
    "--show", is_flag=True, help="Show current config without revealing API key."
)
def configure(
    base_url: str | None,
    model: str | None,
    api_key: str | None,
    show: bool,
) -> None:
    """Configure API settings."""

    if show:
        _show_config()
        return

    current = load_config()
    selected_base_url = base_url or _prompt_value(
        "base_url", current.api.base_url or DEFAULT_BASE_URL
    )
    selected_model = model or _prompt_value("model", current.api.model or DEFAULT_MODEL)
    selected_api_key = api_key or getpass("api_key（输入不会显示）: ").strip()

    try:
        path = write_config(
            base_url=selected_base_url,
            model=selected_model,
            api_key=selected_api_key,
            default_confirm=current.behavior.default_confirm,
            history_limit=current.behavior.history_limit,
            context_commands=current.behavior.context_commands,
            language=current.behavior.language,
            hard_block_enabled=current.safety.hard_block_enabled,
        )
    except AiShError as exc:
        render_error(str(exc))
        raise SystemExit(1) from exc

    console.print(f"配置已保存：{path}")
    console.print("API Key 已写入本地配置文件，文件权限已设置为 600。")


def _run_suggestion_once(
    user_input: str,
    *,
    stdin_context: str,
    config: Config | None = None,
    history: HistoryStore | None = None,
) -> None:
    try:
        config = config or load_config()
        validate_api_config(config)
        history = history or HistoryStore(limit=config.behavior.history_limit)
        suggestion = create_suggestion(
            config,
            user_input,
            stdin_context=stdin_context,
        )
        result = suggestion.result
        render_result(result, cwd=str(suggestion.environment.get("cwd", "")))
        if result.kind == "command":
            history.append(
                new_history_entry(user_input, result.command, executed=False)
            )
    except AiShError as exc:
        render_error(str(exc))
    except KeyboardInterrupt:
        console.print("\n已取消。")


def _run_legacy_once(
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
        validate_api_config(config)
        history = history or HistoryStore(limit=config.behavior.history_limit)
        recent_commands = (
            history.recent_commands(config.behavior.context_commands)
            if conversation
            else []
        )
        suggestion = create_suggestion(
            config,
            user_input,
            stdin_context=stdin_context,
            conversation=conversation,
            recent_commands=recent_commands,
        )
        result = suggestion.result
        render_result(result, cwd=str(suggestion.environment.get("cwd", "")))
        if conversation:
            conversation.add_user(user_input)
            conversation.add_assistant(result_to_assistant_message(result)["content"])
        if result.kind == "blocked":
            history.append(new_history_entry(user_input, "", executed=False))
            return
        if result.kind != "command":
            return
        _handle_legacy_result(
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


def _handle_legacy_result(
    user_input: str,
    result: AssistantResult,
    *,
    config: Config,
    history: HistoryStore,
    conversation: Conversation | None,
    dry_run: bool,
) -> None:
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

    choice = prompt_confirm(config.behavior.default_confirm, caution=caution)
    if choice == "n":
        history.append(new_history_entry(user_input, result.command, executed=False))
        console.print("已取消，没有执行任何命令。")
        return
    if choice == "e":
        result = edit_command(result)
        result = normalize_result(result)
        render_result(result)
        if result.kind == "blocked":
            history.append(new_history_entry(user_input, "", executed=False))
            return
        confirm_edited = prompt_confirm(
            "n",
            caution=result.risk_level == "caution",
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
    result: AssistantResult,
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


def _read_stdin_if_piped() -> str:
    if sys.stdin.isatty():
        return ""
    return sys.stdin.read()


def _prompt_value(label: str, default: str) -> str:
    value = click.prompt(label, default=default, show_default=True)
    return str(value).strip()


def _show_config() -> None:
    try:
        config = load_config()
    except AiShError as exc:
        render_error(str(exc))
        raise SystemExit(1) from exc

    api_key_status = "configured" if config.api.api_key else "missing"
    console.print(f"config_path: {config.path}")
    console.print(f"base_url: {config.api.base_url or '[missing]'}")
    console.print(f"model: {config.api.model or '[missing]'}")
    console.print(f"api_key: {api_key_status}")
