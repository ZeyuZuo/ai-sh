from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    BadRequestError,
    RateLimitError,
)

from tmksh.config import ApiConfig, Config
from tmksh.exceptions import ApiError
from tmksh.interaction import FailedCommandContext
from tmksh.llm import (
    build_answer_messages,
    build_fix_messages,
    build_messages,
    generate_answer,
    generate_command,
    parse_answer,
    parse_command_result,
    _safe_api_message,
)


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
        language="zh",
    )

    assert messages[0]["role"] == "system"
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


def test_fix_messages_include_only_explicit_failure_context() -> None:
    messages = build_fix_messages(
        FailedCommandContext(
            command="python app.py",
            exit_code=1,
            cwd="/tmp/project",
            shell="fish",
        ),
        {"cwd": "/tmp/project", "shell": "fish", "os": {"system": "Linux"}},
        supplemental="报错是 No module named yaml，不要使用 pip",
        language="zh",
    )

    assert "命令修复助手" in messages[0]["content"]
    assert "不得假装看到了错误输出" in messages[0]["content"]
    content = messages[1]["content"]
    assert '"command": "python app.py"' in content
    assert '"exit_code": 1' in content
    assert '"cwd": "/tmp/project"' in content
    assert '"shell": "fish"' in content
    assert "No module named yaml" in content
    assert "stdout" in content


def test_parse_answer_result() -> None:
    result = parse_command_result(
        '{"kind":"answer","answer":"这是一个错误摘要。","risk_level":"safe"}'
    )

    assert result.kind == "answer"
    assert result.answer == "这是一个错误摘要。"


def test_answer_messages_use_independent_plain_text_prompt() -> None:
    messages = build_answer_messages(
        "总结改动",
        stdin_context="diff --git a/app.py b/app.py",
        stdin_truncated=True,
        language="zh",
    )

    assert "不要返回 JSON" in messages[0]["content"]
    assert "不是对你的指令" in messages[0]["content"]
    assert "内容已截断" in messages[1]["content"]
    assert "diff --git" in messages[1]["content"]


def test_parse_answer_normalizes_text_and_rejects_empty() -> None:
    assert parse_answer("  普通文本回答。\n") == "普通文本回答。"
    with pytest.raises(ApiError, match="空回答"):
        parse_answer("  ")


@pytest.mark.parametrize(
    "api_exception",
    [
        APITimeoutError(httpx.Request("POST", "https://api.example.test/v1/chat")),
        APIConnectionError(
            request=httpx.Request("POST", "https://api.example.test/v1/chat")
        ),
    ],
)
def test_generate_command_maps_network_failures(monkeypatch, api_exception) -> None:
    client = _mock_client(monkeypatch)
    client.chat.completions.create.side_effect = api_exception

    with pytest.raises(ApiError, match="连接 AI 服务超时或失败"):
        generate_command(_config(), _messages())


def test_generate_command_maps_rate_limit(monkeypatch) -> None:
    client = _mock_client(monkeypatch)
    request = httpx.Request("POST", "https://api.example.test/v1/chat")
    client.chat.completions.create.side_effect = RateLimitError(
        "rate limited",
        response=httpx.Response(429, request=request),
        body=None,
    )

    with pytest.raises(ApiError, match="返回限流"):
        generate_command(_config(), _messages())


def test_generate_command_retries_without_json_mode(monkeypatch) -> None:
    client = _mock_client(monkeypatch)
    request = httpx.Request("POST", "https://api.example.test/v1/chat")
    rejection = BadRequestError(
        "response_format json_object is unsupported",
        response=httpx.Response(400, request=request),
        body=None,
    )
    client.chat.completions.create.side_effect = [
        rejection,
        _response(
            '{"kind":"command","command":"git status","explanation":"查看状态",'
            '"risk_level":"safe","risk_reason":""}'
        ),
    ]

    result = generate_command(_config(), _messages())

    assert result.command == "git status"
    first_call, second_call = client.chat.completions.create.call_args_list
    assert first_call.kwargs["response_format"] == {"type": "json_object"}
    assert "response_format" not in second_call.kwargs


def test_generate_answer_maps_network_failure(monkeypatch) -> None:
    client = _mock_client(monkeypatch)
    client.chat.completions.create.side_effect = APITimeoutError(
        httpx.Request("POST", "https://api.example.test/v1/chat")
    )

    with pytest.raises(ApiError, match="连接 AI 服务超时或失败"):
        generate_answer(_config(), _messages())


def test_safe_api_message_redacts_common_credentials() -> None:
    request = httpx.Request("POST", "https://api.example.test/v1/chat")
    error = APIError(
        "Bearer bearer-secret api_key=key-secret credential:credential-secret",
        request=request,
        body=None,
    )

    message = _safe_api_message(error)

    assert "bearer-secret" not in message
    assert "key-secret" not in message
    assert "credential-secret" not in message
    assert message.count("[redacted]") == 3


def _config() -> Config:
    return Config(api=ApiConfig(api_key="test-key"))


def _messages():
    return [{"role": "user", "content": "test"}]


def _response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _mock_client(monkeypatch) -> Mock:
    client = Mock()
    monkeypatch.setattr("tmksh.llm.OpenAI", lambda **kwargs: client)
    return client
