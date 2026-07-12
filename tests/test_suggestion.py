import pytest

from tmksh.config import ApiConfig, BehaviorConfig, Config
from tmksh.interaction import FailedCommandContext
from tmksh.llm import AssistantResult
from tmksh.suggestion import create_fix_suggestion, normalize_result


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
