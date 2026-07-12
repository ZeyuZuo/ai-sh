"""Generate and normalize shell command suggestions."""

from __future__ import annotations

from dataclasses import dataclass

from tmksh.config import Config
from tmksh.context import collect_context
from tmksh.interaction import FailedCommandContext
from tmksh.llm import (
    AssistantResult,
    CommandAnalysisKind,
    build_command_analysis_messages,
    build_fix_messages,
    build_messages,
    generate_answer,
    generate_command,
    parse_check_answer,
)
from tmksh.safety import check_command


@dataclass(frozen=True)
class Suggestion:
    """A normalized assistant result with the environment used to generate it."""

    result: AssistantResult
    environment: dict[str, object]


def create_suggestion(
    config: Config,
    request: str,
    *,
    stdin_context: str = "",
    current_command: str = "",
) -> Suggestion:
    """Generate one assistant result and apply the mandatory local safety policy."""

    environment = collect_context()
    messages = build_messages(
        request,
        environment,
        stdin_context=stdin_context,
        current_command=current_command,
        language=config.behavior.language,
    )
    result = normalize_result(generate_command(config, messages))
    return Suggestion(result=result, environment=environment)


def create_fix_suggestion(
    config: Config,
    failed_command: FailedCommandContext,
    *,
    supplemental: str = "",
) -> Suggestion:
    """Generate a safe replacement for one shell-captured failed command."""

    environment = collect_context()
    environment["cwd"] = failed_command.cwd
    environment["shell"] = failed_command.shell
    messages = build_fix_messages(
        failed_command,
        environment,
        supplemental=supplemental,
        language=config.behavior.language,
    )
    result = normalize_result(generate_command(config, messages))
    return Suggestion(result=result, environment=environment)


def create_command_analysis(
    config: Config,
    operation: CommandAnalysisKind,
    command: str,
    *,
    focus: str = "",
) -> Suggestion:
    """Explain or check a command without creating an insertable result."""

    environment = collect_context()
    messages = build_command_analysis_messages(
        operation,
        command,
        environment,
        focus=focus,
        language=config.behavior.language,
    )
    answer = generate_answer(config, messages)
    if operation == "check":
        answer = parse_check_answer(answer, language=config.behavior.language)
    result = AssistantResult(kind="answer", answer=answer, risk_level="safe")
    return Suggestion(result=result, environment=environment)


def normalize_result(result: AssistantResult) -> AssistantResult:
    """Convert AI danger and local hard blocks into non-insertable results."""

    if result.kind != "command":
        return result
    if result.risk_level == "danger":
        return _blocked_result(result.risk_reason or "AI 标记该命令为 danger。")

    verdict = check_command(result.command)
    if verdict.action == "block":
        return _blocked_result(verdict.reason)
    return result


def _blocked_result(reason: str) -> AssistantResult:
    return AssistantResult(
        kind="blocked",
        risk_level="danger",
        risk_reason=reason,
    )
