import pytest

from ai_sh.exceptions import ApiError
from ai_sh.llm import build_messages, parse_command_result


def test_parse_command_result_accepts_json() -> None:
    result = parse_command_result(
        """
        {
          "command": "find . -type f -size +100M",
          "explanation": "查找当前目录下超过 100MB 的文件。",
          "risk_level": "safe",
          "risk_reason": "",
          "alternatives": ["du -ah . | sort -h"]
        }
        """
    )

    assert result.command == "find . -type f -size +100M"
    assert result.risk_level == "safe"
    assert result.alternatives == ["du -ah . | sort -h"]


def test_parse_command_result_extracts_json_from_text() -> None:
    result = parse_command_result(
        '```json\n{"command":"","explanation":"","risk_level":"safe","clarification":"请提供目录。"}\n```'
    )

    assert result.command == ""
    assert result.clarification == "请提供目录。"


def test_parse_command_result_rejects_missing_fields() -> None:
    with pytest.raises(ApiError):
        parse_command_result('{"explanation":"x","risk_level":"safe"}')


def test_build_messages_includes_context_and_stdin() -> None:
    messages = build_messages(
        "总结这次改动",
        {"cwd": "/tmp/project", "shell": "bash"},
        stdin_context="diff --git a/file b/file",
        conversation=[{"role": "assistant", "content": "previous"}],
        language="zh",
    )

    assert messages[0]["role"] == "system"
    assert messages[-2]["content"] == "previous"
    assert "diff --git" in messages[-1]["content"]
    assert "/tmp/project" in messages[-1]["content"]
