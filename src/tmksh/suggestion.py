"""Generate and normalize shell command suggestions."""

from __future__ import annotations

from dataclasses import dataclass

from tmksh.config import Config
from tmksh.context import collect_context
from tmksh.llm import AssistantResult, build_messages, generate_command
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
