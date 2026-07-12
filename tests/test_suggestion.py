import pytest

from tmksh.config import ApiConfig, BehaviorConfig, Config
from tmksh.interaction import FailedCommandContext
from tmksh.llm import AssistantResult, CommandAnalysisKind
from tmksh.suggestion import (
    create_command_analysis,
    create_fix_suggestion,
    normalize_result,
)


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


def test_create_fix_suggestion_uses_failure_environment_and_safety(
    monkeypatch, tmp_path
) -> None:
    failed = FailedCommandContext(
        command="sudo rm -rf /",
        exit_code=1,
        cwd="/srv/project",
        shell="zsh",
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "tmksh.suggestion.collect_context",
        lambda: {"cwd": "/current", "shell": "bash", "os": {"system": "Linux"}},
    )

    def fake_build(received, environment, *, supplemental, language):
        captured.update(
            failed=received,
            environment=environment.copy(),
            supplemental=supplemental,
            language=language,
        )
        return [{"role": "user", "content": "fix"}]

    monkeypatch.setattr("tmksh.suggestion.build_fix_messages", fake_build)
    monkeypatch.setattr(
        "tmksh.suggestion.generate_command",
        lambda config, messages: AssistantResult(
            command="rm -rf /",
            explanation="unsafe repair",
            risk_level="safe",
        ),
    )
    config = Config(
        api=ApiConfig(api_key="test"),
        behavior=BehaviorConfig(language="zh"),
        path=tmp_path / "config.toml",
    )

    suggestion = create_fix_suggestion(config, failed, supplemental="permission denied")

    assert captured == {
        "failed": failed,
        "environment": {
            "cwd": "/srv/project",
            "shell": "zsh",
            "os": {"system": "Linux"},
        },
        "supplemental": "permission denied",
        "language": "zh",
    }
    assert suggestion.result.kind == "blocked"
    assert suggestion.result.risk_reason == "删除根目录"


@pytest.mark.parametrize("operation", ["explain", "check"])
def test_create_command_analysis_returns_non_insertable_plain_text_result(
    monkeypatch, tmp_path, operation: CommandAnalysisKind
) -> None:
    environment = {
        "cwd": "/workspace",
        "shell": "bash",
        "os": {"system": "Linux"},
    }
    captured: dict[str, object] = {}
    monkeypatch.setattr("tmksh.suggestion.collect_context", lambda: environment)

    def fake_build(received_operation, command, received_environment, **kwargs):
        captured.update(
            operation=received_operation,
            command=command,
            environment=received_environment,
            **kwargs,
        )
        return [{"role": "user", "content": "analyze"}]

    monkeypatch.setattr("tmksh.suggestion.build_command_analysis_messages", fake_build)
    raw_answer = (
        "风险: caution，递归删除文件。\n"
        "正确性: 不会匹配隐藏文件。\n"
        "兼容性: 当前环境支持。\n"
        "建议: 先确认匹配范围。"
        if operation == "check"
        else "纯文本分析结果。"
    )
    monkeypatch.setattr(
        "tmksh.suggestion.generate_answer",
        lambda config, messages: raw_answer,
    )
    monkeypatch.setattr(
        "tmksh.suggestion.check_command",
        lambda command: pytest.fail("text analysis must not enter command safety"),
    )
    config = Config(
        api=ApiConfig(api_key="test"),
        behavior=BehaviorConfig(language="zh"),
        path=tmp_path / "config.toml",
    )

    suggestion = create_command_analysis(
        config,
        operation,
        "rm -rf build/*",
        focus="检查隐藏文件",
    )

    assert captured == {
        "operation": operation,
        "command": "rm -rf build/*",
        "environment": environment,
        "focus": "检查隐藏文件",
        "language": "zh",
    }
    assert suggestion.environment is environment
    expected_answer = (
        "风险      caution，递归删除文件。\n"
        "正确性    不会匹配隐藏文件。\n"
        "兼容性    当前环境支持。\n"
        "建议      先确认匹配范围。"
        if operation == "check"
        else raw_answer
    )
    assert suggestion.result == AssistantResult(
        kind="answer",
        answer=expected_answer,
        risk_level="safe",
    )


def test_create_command_check_uses_the_configured_english_schema(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr("tmksh.suggestion.collect_context", lambda: {})
    monkeypatch.setattr(
        "tmksh.suggestion.generate_answer",
        lambda config, messages: (
            "Risk: safe (read-only).\n"
            "Correctness: Lists changes.\n"
            "Compatibility: Supported by Git.\n"
            "Recommendation: Review the output."
        ),
    )
    config = Config(
        api=ApiConfig(api_key="test"),
        behavior=BehaviorConfig(language="en"),
        path=tmp_path / "config.toml",
    )

    suggestion = create_command_analysis(config, "check", "git status --short")

    assert suggestion.result.answer.startswith("Risk: safe (read-only).")
    assert "Correctness: Lists changes." in suggestion.result.answer
