import pytest

from ai_sh.exceptions import ApiError
from ai_sh.llm import build_messages, parse_command_result


def test_parse_command_result_accepts_json() -> None:
    result = parse_command_result(
        """
        {
          "kind": "command",
          "command": "find . -type f -size +100M",
          "explanation": "查找当前目录下超过 100MB 的文件。",
          "risk_level": "safe",
          "risk_reason": ""
        }
        """
    )

    assert result.command == "find . -type f -size +100M"
    assert result.kind == "command"
    assert result.risk_level == "safe"


def test_parse_command_result_extracts_json_from_text() -> None:
    result = parse_command_result(
        '```json\n{"command":"","explanation":"","risk_level":"safe","clarification":"请提供目录。"}\n```'
    )

    assert result.command == ""
    assert result.kind == "clarification"
    assert result.clarification == "请提供目录。"


def test_parse_command_result_rejects_missing_fields() -> None:
    with pytest.raises(ApiError):
        parse_command_result('{"explanation":"x","risk_level":"safe"}')


def test_build_messages_includes_context_and_stdin() -> None:
    messages = build_messages(
        "总结这次改动",
        {"cwd": "/tmp/project", "shell": "bash"},
        stdin_context="diff --git a/file b/file",
        current_command="git diff --stat",
        conversation=[{"role": "assistant", "content": "previous"}],
        language="zh",
    )

    assert messages[0]["role"] == "system"
    assert messages[-2]["content"] == "previous"
    assert "diff --git" in messages[-1]["content"]
    assert "git diff --stat" in messages[-1]["content"]
    assert "/tmp/project" in messages[-1]["content"]


def test_system_prompt_defines_path_and_scope_semantics() -> None:
    messages = build_messages(
        "统计当前目录的直接子目录",
        {"cwd": "/tmp/project", "shell": "bash"},
    )

    prompt = messages[0]["content"]
    assert "当前目录”“这个文件夹”写成 `.`" in prompt
    assert "不得复制 cwd 的绝对路径" in prompt
    assert "find . -mindepth 1 -maxdepth 1" in prompt
    assert "不得用会漏掉隐藏目录的 `*/`" in prompt
    assert "搜索最大文件等请求默认递归" in prompt
    assert "先汇总完整结果再做一次全局排序" in prompt
    assert "-printf '%T@ %p\\n' | sort -rn" in prompt
    assert "保留原路径、范围、参数和过滤条件" in prompt


def test_parse_answer_result() -> None:
    result = parse_command_result(
        '{"kind":"answer","answer":"这是一个错误摘要。","risk_level":"safe"}'
    )

    assert result.kind == "answer"
    assert result.answer == "这是一个错误摘要。"
