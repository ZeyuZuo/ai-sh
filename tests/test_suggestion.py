import pytest

from tmksh.llm import AssistantResult
from tmksh.suggestion import normalize_result


@pytest.mark.parametrize("risk_level", ["safe", "caution"])
def test_normalize_result_allows_non_dangerous_commands(risk_level: str) -> None:
    result = AssistantResult(
        command="rm -rf ./build" if risk_level == "caution" else "git status",
        explanation="test",
        risk_level=risk_level,
    )

    normalized = normalize_result(result)

    assert normalized.kind == "command"
    assert normalized.command == result.command


def test_normalize_result_blocks_ai_danger() -> None:
    normalized = normalize_result(
        AssistantResult(
            command="shutdown now",
            explanation="shuts down",
            risk_level="danger",
            risk_reason="会关闭系统。",
        )
    )

    assert normalized.kind == "blocked"
    assert normalized.command == ""
    assert normalized.risk_reason == "会关闭系统。"


def test_normalize_result_blocks_local_hard_pattern_even_if_ai_marks_safe() -> None:
    normalized = normalize_result(
        AssistantResult(
            command="rm -rf /",
            explanation="dangerously wrong",
            risk_level="safe",
        )
    )

    assert normalized.kind == "blocked"
    assert normalized.command == ""
    assert normalized.risk_level == "danger"
    assert normalized.risk_reason == "删除根目录"


def test_normalize_result_blocks_compound_root_deletion_marked_safe() -> None:
    normalized = normalize_result(
        AssistantResult(
            command="sudo rm -rf /&&echo done",
            explanation="dangerously wrong compound command",
            risk_level="safe",
        )
    )

    assert normalized.kind == "blocked"
    assert normalized.command == ""
    assert normalized.risk_reason == "删除根目录"


def test_normalize_result_preserves_non_command_results() -> None:
    result = AssistantResult(kind="clarification", clarification="请提供目录。")

    assert normalize_result(result) is result
